"""Route the ride's real footpaths so they run under and over the track.

Proximity scoring (RideRatings.cpp) rewards a footpath on a piece's first tile that touches the
track: PATH_TOUCH_ABOVE (path top at the track base, up to 75 points) and PATH_TOUCH_UNDER (path
resting on the track's clearance, up to 85), each reaching most of its value after a few pieces;
queues have their own items (touch above 40, touch under 45, track over the queue up to +25).
Loose path tiles would score the same, so the planner only builds what a park would have:

- an exit path from the tile in front of the exit to the edge of the area (where the park's paths
  join), detouring through touch spots, and
- a queue line from the tile in front of the entrance that joins the exit path.

Paths are flat or sloped tiles on a (tile, height) grid: a flat tile meets its neighbours at its
height, a sloped tile rises 16 towards its direction and only connects along that axis. Every tile
must be inside the area, on buildable land, at or above ground and water, and must not overlap
track (touching is allowed).
"""

from __future__ import annotations

from collections import deque

from .track import DIR_DELTA, TILE, Layout, Placed, element_clearances, piece_tiles, segments

PATH_CLEAR = 32  # kPathClearance
SLOPE_CLEAR = 48  # a sloped path also covers its rise
STEP = 16  # kPathHeightStep
TOUCH_TARGET = 8  # pieces per touch item: min(x + 10, 20) is 90% of its maximum at 8
MAX_TILES = 140
MAX_BFS = 12_000

Tile = tuple[int, int]
State = tuple[int, int, int, int]  # x, y, base z, slope direction (-1 = flat)


def _unit(d: int) -> Tile:
    dx, dy = DIR_DELTA[d & 3]
    return dx // TILE, dy // TILE


class Planner:
    def __init__(self, layout: Layout, placed: list[Placed]):
        self.layout = layout
        self.env = layout.env
        # Vertical extents of the track on every tile.
        self.track: dict[Tile, list[tuple[int, int]]] = {}
        self.first: list[tuple[Tile, int, int, int]] = []  # (tile, base, clearance, piece index)
        for i, p in enumerate(placed):
            clears = element_clearances(layout.ride_type_name, p.type) or [24] * len(segments()[p.type].elements)
            for (tx, ty, z), c in zip(piece_tiles(p.x, p.y, p.z, p.d, p.type), clears):
                self.track.setdefault((tx, ty), []).append((z, z + c))
            self.first.append(((p.x // TILE, p.y // TILE), p.z, p.z + clears[0], i))
        self.blocked: set[Tile] = set()
        for ax, ay, _ in layout.access_tiles():
            self.blocked.add((ax, ay))
        self.used: dict[Tile, State] = {}
        self._static: dict[State, bool] = {}
        # No route needs to climb above the highest spot that touches the track.
        self.z_max = max([c for _t, _b, c, _i in self.first] + [layout.ground_z]) + STEP

    # ---------------------------------------------------------------- geometry

    def valid(self, s: State) -> bool:
        if (s[0], s[1]) in self.used:
            return False
        ok = self._static.get(s)
        if ok is None:
            ok = self._static[s] = self._geometry_ok(s)
        return ok

    def _geometry_ok(self, s: State) -> bool:
        """Everything about a path state that does not depend on the route built so far."""
        x, y, z, d = s
        t = (x, y)
        info = self.env.tiles.get(t)
        if info is None or t in self.blocked or not self.layout.in_area(x, y):
            return False
        if not self.env.buildable(t) or z % STEP or z < info.floor or z > self.z_max:
            return False
        top = z + (SLOPE_CLEAR if d >= 0 else PATH_CLEAR)
        if any(z < b1 and b0 < top for b0, b1 in info.blocked):
            return False
        return all(not (z < c and b < top) for b, c in self.track.get(t, ()))

    @staticmethod
    def edge(s: State, m: int) -> int | None:
        """Height of the state's edge facing direction m, or None if it does not connect there."""
        _, _, z, d = s
        if d < 0:
            return z
        if m == d:
            return z + STEP
        if m == (d + 2) & 3:
            return z
        return None

    def neighbours(self, s: State):
        for m in range(4):
            h = self.edge(s, m)
            if h is None:
                continue
            ux, uy = _unit(m)
            nx, ny = s[0] + ux, s[1] + uy
            for n in ((nx, ny, h, -1), (nx, ny, h, m), (nx, ny, h - STEP, (m + 2) & 3)):
                if self.valid(n):
                    yield n

    # ---------------------------------------------------------------- routing

    def bfs(self, starts: list[State], goal) -> list[State] | None:
        """Shortest route from any start to a state with goal(state); returns the states after the start."""
        prev: dict[State, State | None] = {s: None for s in starts}
        q = deque(starts)
        n = 0
        while q and n < MAX_BFS:
            s = q.popleft()
            n += 1
            if prev[s] is not None and goal(s):
                out = []
                while prev[s] is not None:
                    out.append(s)
                    s = prev[s]
                out.append(s)
                route = self.untangle(out[::-1])
                if route is not None:
                    return route[1:]
                continue
            for nb in self.neighbours(s):
                if nb not in prev:
                    prev[nb] = s
                    q.append(nb)
        return None

    def connects(self, a: State, b: State) -> bool:
        for m in range(4):
            ux, uy = _unit(m)
            if (a[0] + ux, a[1] + uy) == (b[0], b[1]):
                ha, hb = self.edge(a, m), self.edge(b, (m + 2) & 3)
                return ha is not None and ha == hb
        return False

    def untangle(self, route: list[State]) -> list[State] | None:
        """A route through the state grid may pass one tile twice at different heights, which the
        game cannot build. Cut such loops out where the ends still meet; None if one cannot be cut."""
        while True:
            first: dict[Tile, int] = {}
            dup = None
            for k, s in enumerate(route):
                t = (s[0], s[1])
                if t in first:
                    dup = (first[t], k)
                    break
                first[t] = k
            if dup is None:
                return route
            i, j = dup
            if i > 0 and self.connects(route[i - 1], route[j]):
                route = route[:i] + route[j:]
            elif j + 1 < len(route) and self.connects(route[i], route[j + 1]):
                route = route[: i + 1] + route[j + 1:]
            else:
                return None

    def take(self, route: list[State], queue: bool, out: list[list[int]]) -> None:
        for s in route:
            self.used[(s[0], s[1])] = s
            out.append([s[0], s[1], s[2], s[3], int(queue)])

    def front(self, k: int) -> State:
        """Flat path state in front of the entrance (k = 0) or exit (k = 1), at the station's height."""
        ax, ay, _ = self.layout.access_tiles()[k]
        sx, sy = self.layout.station_tile
        fx, fy = _unit(self.layout.station_dir)
        mid = (self.layout.station_len - 1) // 2
        mx, my = sx + fx * mid, sy + fy * mid
        ox, oy = ax - mx, ay - my
        return (ax + ox, ay + oy, self.layout.ground_z, -1)

    def plan(self) -> list[list[int]]:
        """Exit path through touch spots to the area edge, then a queue line joining it."""
        tiles: list[list[int]] = []
        exit_front = self.front(1)
        if not self.valid(exit_front):
            return []
        self.take([exit_front], False, tiles)
        head = exit_front
        under = {(t, b - PATH_CLEAR) for t, b, c, i in self.first if (b - PATH_CLEAR) % STEP == 0}
        on_top = {(t, c) for t, b, c, i in self.first if c % STEP == 0}
        counts = {"under": 0, "on_top": 0}

        def is_target(s: State) -> bool:
            if s[3] >= 0:
                return False
            key = ((s[0], s[1]), s[2])
            return (key in under and counts["under"] < TOUCH_TARGET) or (key in on_top and counts["on_top"] < TOUCH_TARGET)

        while len(tiles) < MAX_TILES:
            route = self.bfs([head], is_target)
            if not route or len(tiles) + len(route) > MAX_TILES:
                break
            self.take(route, False, tiles)
            head = route[-1]
            key = ((head[0], head[1]), head[2])
            counts["under" if key in under else "on_top"] += 1
            under.discard(key)
            on_top.discard(key)
        # Join the park: run on to the area's edge.
        edge = self.bfs([head], lambda s: any(not self.layout.in_area(s[0] + _unit(m)[0], s[1] + _unit(m)[1])
                                              for m in range(4)) and s[3] < 0)
        if edge:
            self.take(edge, False, tiles)
        exit_tiles = {(t[0], t[1]) for t in tiles}
        # Queue line: from the entrance past the track, then into the exit path.
        entrance_front = self.front(0)
        if self.valid(entrance_front):
            queue: list[list[int]] = []
            self.take([entrance_front], True, queue)
            q_under = {(t, b - PATH_CLEAR) for t, b, c, i in self.first if (b - PATH_CLEAR) % STEP == 0}
            qhead = entrance_front
            if self.layout.paths == "v2":
                # Queue items: touch above (40), touch under (45), track over the queue (up to 4 pieces, +25).
                q_on_top = {(t, c) for t, b, c, i in self.first if c % STEP == 0}
                over_tiles = {t: b for t, b, c, i in self.first}
                want = {"under": 1, "on_top": 1, "over": 4}

                def q_target(s: State) -> bool:
                    key = ((s[0], s[1]), s[2])
                    if s[3] < 0 and want["under"] and key in q_under:
                        return True
                    if s[3] < 0 and want["on_top"] and key in q_on_top:
                        return True
                    b = over_tiles.get((s[0], s[1]))
                    return bool(want["over"]) and b is not None and s[2] + PATH_CLEAR <= b

                while len(queue) < 50:
                    route = self.bfs([qhead], q_target)
                    if not route or len(queue) + len(route) > 50:
                        break
                    self.take(route, True, queue)
                    qhead = route[-1]
                    key = ((qhead[0], qhead[1]), qhead[2])
                    if qhead[3] < 0 and key in q_under and want["under"]:
                        want["under"] -= 1
                    elif qhead[3] < 0 and key in q_on_top and want["on_top"]:
                        want["on_top"] -= 1
                    else:
                        want["over"] = max(0, want["over"] - 1)
                        over_tiles.pop((qhead[0], qhead[1]), None)
                    if not any(want.values()):
                        break
            else:
                route = self.bfs([entrance_front], lambda s: s[3] < 0 and ((s[0], s[1]), s[2]) in q_under)
                if route and len(route) < 30:
                    self.take(route, True, queue)
                    qhead = route[-1]

            def joins(s: State) -> bool:
                for m in range(4):
                    ux, uy = _unit(m)
                    other = self.used.get((s[0] + ux, s[1] + uy))
                    if other is not None and (s[0] + ux, s[1] + uy) in exit_tiles:
                        h = self.edge(s, m)
                        if h is not None and h == self.edge(other, (m + 2) & 3):
                            return True
                return False

            join = self.bfs([qhead], joins)
            if join:
                self.take(join, True, queue)
                tiles.extend(queue)
            else:  # a queue that leads nowhere is not a queue: drop it
                for t in queue:
                    self.used.pop((t[0], t[1]), None)
        return tiles


def plan(layout: Layout, placed: list[Placed]) -> list[list[int]]:
    """Path tiles [x, y, z, slope direction or -1, queue] for the ride's exit path and queue line."""
    if layout.env is None:
        return []
    return Planner(layout, placed).plan()


# Planning is pure Python; with many judge threads it would serialise on the GIL, so a pool of
# processes plans instead. Each process gets the layout once and then only the placed pieces.
_worker_layout: Layout | None = None


def init_worker(layout: Layout) -> None:
    global _worker_layout
    _worker_layout = layout


def plan_in_worker(placed: list[Placed]) -> list[list[int]]:
    return plan(_worker_layout, placed)


def connected(tiles: list[list[int]]) -> tuple[int, int]:
    """(number of separate path networks, tiles) for planned path tiles; one network means every
    tile is reachable from every other along matching edges (no gaps)."""
    states = {(t[0], t[1]): (t[0], t[1], t[2], t[3]) for t in tiles}
    seen: set[Tile] = set()
    parts = 0
    for start in states:
        if start in seen:
            continue
        parts += 1
        stack = [start]
        seen.add(start)
        while stack:
            x, y = stack.pop()
            s = states[(x, y)]
            for m in range(4):
                ux, uy = _unit(m)
                n = (x + ux, y + uy)
                if n in states and n not in seen:
                    h = Planner.edge(s, m)
                    if h is not None and h == Planner.edge(states[n], (m + 2) & 3):
                        seen.add(n)
                        stack.append(n)
    return parts, len(states)
