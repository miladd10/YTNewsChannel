#!/bin/bash
set -u
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" || exit 1
PORT=8787
URL="http://127.0.0.1:${PORT}"
PID_FILE="$APP_DIR/data/server.pid"
LOG_FILE="$APP_DIR/data/server.log"
VENV_DIR="$APP_DIR/.venv"
REQ_FILE="$APP_DIR/requirements.txt"
mkdir -p "$APP_DIR/data"

if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
    exit 0
  fi
  rm -f "$PID_FILE"
fi

PYTHON="$(command -v python3 || true)"
if [ -z "$PYTHON" ]; then
  echo "Python 3 is required."
  read -r -p 'Press Return to close...'
  exit 1
fi
if [ ! -x "$VENV_DIR/bin/python" ]; then "$PYTHON" -m venv "$VENV_DIR" || exit 1; fi
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check -q -r "$REQ_FILE" || exit 1
YT_NEWS_NO_BROWSER=1 nohup "$VENV_DIR/bin/python" "$APP_DIR/run.py" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
for _ in $(seq 1 60); do
  if curl -fsS "$URL" >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true; echo "YT News Studio is running at $URL"; exit 0; fi
  sleep .25
done
echo "App did not start. See $LOG_FILE"
read -r -p 'Press Return to close...'
