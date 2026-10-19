"""Headless OpenRCT2 instances driven through the rct2loop plugin.

Each instance gets its own network port and shares a project-local user data
directory (``runtime/``) holding a minimal config.ini and the plugin, so the
user's own ~/.config/OpenRCT2 is never touched.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENRCT2 = ROOT / ".vendor" / "OpenRCT2" / "openrct2"
RUNTIME = ROOT / "runtime"
PLUGIN_SRC = ROOT / "plugin" / "rct2loop.js"
PORT_RE = re.compile(r"\[rct2loop\] listening on port (\d+)")
NETWORK_PORT_BASE = 12000

RUNTIME_CONFIG = """\
[general]
debugging_tools = true
autosave = 5
show_fps = false

[network]
listen_address = "127.0.0.1"
advertise = false
log_chat = false
log_server_actions = false
pause_server_if_no_clients = false

[plugin]
enable_hot_reloading = false
"""


def rct2_path() -> Path:
    env = os.environ.get("RCT2_PATH")
    if env:
        return Path(env)
    for c in (
        Path.home() / ".steam/steam/steamapps/common/Rollercoaster Tycoon 2",
        Path.home() / ".local/share/Steam/steamapps/common/Rollercoaster Tycoon 2",
    ):
        if (c / "Data" / "g1.dat").exists():
            return c.resolve()
    raise FileNotFoundError("RCT2 data not found; set RCT2_PATH")


def base_park() -> Path:
    """Flat 256x256 park shipped with pyrct2; any .park works."""
    from pyrct2.scenarios import Scenario

    return Path(Scenario.TEST_PARK_LARGE.value)


def prepare_runtime() -> Path:
    """Create runtime/ with config.ini and only our plugin (refreshed every launch)."""
    plugin_dir = RUNTIME / "plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    cfg = RUNTIME / "config.ini"
    if not cfg.exists():
        cfg.write_text(RUNTIME_CONFIG)
    shutil.copyfile(PLUGIN_SRC, plugin_dir / PLUGIN_SRC.name)
    return RUNTIME


class GameError(RuntimeError):
    pass


class Game:
    """One headless OpenRCT2 process plus a JSON-lines connection to rct2loop."""

    _slot_counter = itertools.count()
    _slot_lock = threading.Lock()

    def __init__(self, park: Path | None = None, slot: int | None = None, launch_timeout: float = 60.0):
        prepare_runtime()
        if slot is None:
            with Game._slot_lock:
                slot = next(Game._slot_counter)
        self.slot = slot
        self.logs: deque[str] = deque(maxlen=500)
        park = park or base_park()
        cmd = [
            str(OPENRCT2), "host", str(park), "--headless",
            "--port", str(NETWORK_PORT_BASE + slot),
            "--address", "127.0.0.1",
            "--user-data-path", str(RUNTIME),
            "--rct2-data-path", str(rct2_path()),
        ]
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        self._port: int | None = None
        self._port_ready = threading.Event()
        threading.Thread(target=self._pump_logs, daemon=True).start()
        if not self._port_ready.wait(launch_timeout) or self._port is None:
            self.close()
            raise GameError(f"rct2loop did not start; last logs:\n" + "\n".join(list(self.logs)[-15:]))
        self.sock = socket.create_connection(("127.0.0.1", self._port), timeout=launch_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._rfile = self.sock.makefile("r", encoding="utf-8")
        self._ids = itertools.count(1)

    def _pump_logs(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            self.logs.append(line)
            m = PORT_RE.search(line)
            if m and self._port is None:
                self._port = int(m.group(1))
                self._port_ready.set()
        self._port_ready.set()

    def call(self, cmd: str, args: dict | None = None, timeout: float = 120.0):
        if self.proc.poll() is not None:
            raise GameError(f"OpenRCT2 exited ({self.proc.returncode})")
        req_id = next(self._ids)
        self.sock.settimeout(timeout)
        self.sock.sendall((json.dumps({"id": req_id, "cmd": cmd, "args": args or {}}) + "\n").encode())
        line = self._rfile.readline()
        if not line:
            raise GameError(f"connection closed during {cmd}")
        msg = json.loads(line)
        if msg.get("id") != req_id:
            raise GameError(f"reply id mismatch: sent {req_id}, got {msg.get('id')}")
        if not msg["ok"]:
            raise GameError(f"{cmd}: {msg['error']}")
        return msg["result"]

    def close(self) -> None:
        try:
            if hasattr(self, "sock"):
                self.sock.close()
        finally:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

    def __enter__(self) -> Game:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def wait_ready(game: Game, timeout: float = 30.0) -> dict:
    """Ping until the park is loaded and ticking state is readable."""
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return game.call("ping", timeout=5)
        except (GameError, OSError) as e:
            last = e
            time.sleep(0.2)
    raise GameError(f"ping failed: {last}")
