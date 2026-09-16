#!/usr/bin/env bash
# Bring the demo up locally and print the one command to put it on a phone.
#
#   ./scripts/run_demo.sh
#
# Creates the venv if needed, installs pinned deps, generates both datasets if
# missing, and serves on 0.0.0.0 so a phone on the same network can reach it.
# Safe to re-run: every step is skipped when its output already exists.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"
PORT="${PORT:-8000}"

cd "$BACKEND"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "creating venv..."
  python3 -m venv "$VENV"
fi

# Retries and a longer timeout: a dropped read from PyPI should not leave a
# half-built venv behind and send someone hunting for a bug in the script.
PIP_ARGS=(--quiet --retries 5 --timeout 60)
if ! "$VENV/bin/python" -c "import fastapi, solders, PIL" 2>/dev/null; then
  echo "installing pinned dependencies..."
  "$VENV/bin/pip" install "${PIP_ARGS[@]}" --upgrade pip
  "$VENV/bin/pip" install "${PIP_ARGS[@]}" -r requirements.txt
else
  echo "dependencies already present"
fi

[[ -f data/pose/manifest.jsonl ]] \
  || { echo "generating ghost-overlay dataset..."; "$VENV/bin/python" -m tapfarm.pose.dataset --out data/pose; }
[[ -f data/tapgrid/manifest.jsonl ]] \
  || { echo "generating tap-grid dataset..."; "$VENV/bin/python" -m tapfarm.generator.dataset --out data/tapgrid --count 2000; }

# The phone needs a routable address; localhost is the laptop, not the device.
LAN_IP="$(python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80)); print(s.getsockname()[0])
except Exception:
    print('127.0.0.1')
finally:
    s.close()
")"

cat <<EOF

==============================================================
  API            http://$LAN_IP:$PORT
  Interactive    http://$LAN_IP:$PORT/docs
  Health         http://$LAN_IP:$PORT/health

  Put it on a phone (same wifi, USB debugging on):

    cd $ROOT/android
    ./gradlew installDebug -PtapfarmApiBase=http://$LAN_IP:$PORT

  Then: Connect wallet -> Ghost overlay -> Practice.
==============================================================

EOF

exec "$VENV/bin/python" -m uvicorn tapfarm.main:app --host 0.0.0.0 --port "$PORT"
