#!/bin/bash
set -u
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$APP_DIR/data/server.pid"
if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$PID" ] && kill -0 "$PID" >/dev/null 2>&1; then kill "$PID" >/dev/null 2>&1 || true; fi
  rm -f "$PID_FILE"
fi
pkill -f "$APP_DIR/run.py" >/dev/null 2>&1 || true
echo "YT News Studio stopped."
