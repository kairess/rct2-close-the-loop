#!/usr/bin/env bash
# Reproducible dev environment: OpenRCT2 (project-local) + RCT2 data from Steam + pyrct2 bridge.
# Idempotent; safe to re-run. Override the RCT2 location with RCT2_PATH=/path/to/rct2.
set -euo pipefail

OPENRCT2_VERSION="v0.5.6"
OPENRCT2_FLAVOR="resolute"  # Ubuntu 26.04; use noble for 24.04
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/.vendor"
ORCT2="$VENDOR/OpenRCT2"
CONFIG_INI="${XDG_CONFIG_HOME:-$HOME/.config}/OpenRCT2/config.ini"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# 1. RCT2 game data
if [[ -z "${RCT2_PATH:-}" ]]; then
  for c in "$HOME/.steam/steam/steamapps/common/Rollercoaster Tycoon 2" \
           "$HOME/.local/share/Steam/steamapps/common/Rollercoaster Tycoon 2"; do
    [[ -d "$c/Data" ]] && RCT2_PATH="$(readlink -f "$c")" && break
  done
fi
[[ -n "${RCT2_PATH:-}" && -f "$RCT2_PATH/Data/g1.dat" ]] || { echo "RCT2 data not found; set RCT2_PATH" >&2; exit 1; }
log "RCT2 data: $RCT2_PATH"

# 2. OpenRCT2 binary
if [[ ! -x "$ORCT2/openrct2" ]]; then
  log "Downloading OpenRCT2 $OPENRCT2_VERSION ($OPENRCT2_FLAVOR)"
  mkdir -p "$VENDOR"
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/openrct2.tar.gz" \
    "https://github.com/OpenRCT2/OpenRCT2/releases/download/$OPENRCT2_VERSION/OpenRCT2-$OPENRCT2_VERSION-Linux-$OPENRCT2_FLAVOR-x86_64.tar.gz"
  tar xzf "$tmp/openrct2.tar.gz" -C "$VENDOR"
  rm -rf "$tmp"
fi

# The binaries have RUNPATH=$ORIGIN, so a missing libzip5 can sit next to them (no sudo needed).
if ldd "$ORCT2/openrct2" | grep -q "libzip.so.5 => not found"; then
  log "Vendoring libzip5 next to OpenRCT2"
  tmp="$(mktemp -d)"
  (cd "$tmp" && apt-get download libzip5 >/dev/null && dpkg-deb -x libzip5_*.deb x)
  cp -P "$tmp"/x/usr/lib/x86_64-linux-gnu/libzip.so.5* "$ORCT2/"
  rm -rf "$tmp"
fi
log "$("$ORCT2/openrct2-cli" --version | head -1)"

# 3. OpenRCT2 config: game path, localhost-only host, no master-server advert, debug tools (for speed 8)
mkdir -p "$(dirname "$CONFIG_INI")"
python3 - "$CONFIG_INI" "$RCT2_PATH" <<'PY'
import configparser, sys
path, game_path = sys.argv[1], sys.argv[2]
cp = configparser.ConfigParser(interpolation=None)
cp.optionxform = str
cp.read(path)
want = {
    "general": {"game_path": f'"{game_path}"', "debugging_tools": "true"},
    "network": {"listen_address": '"127.0.0.1"', "advertise": "false"},
}
for section, kv in want.items():
    if not cp.has_section(section):
        cp.add_section(section)
    for k, v in kv.items():
        cp.set(section, k, v)
with open(path, "w") as f:
    cp.write(f)
PY
log "Configured $CONFIG_INI"

# 4. Python env + bridge plugin
cd "$ROOT"
uv sync
PYRCT2_OPENRCT2_PATH="$ORCT2/openrct2" uv run pyrct2 setup

log "Done. Try: uv run python scripts/smoke_test.py"
