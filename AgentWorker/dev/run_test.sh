#!/bin/bash
# Reset a test project from its base copy, queue its task under a unique name, and run the worker once.
# usage: dev/run_test.sh <base-dir> <task-file> <workdir-name> [worker args...]
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$1"; TASK="$2"; NAME="$3"; shift 3
rm -rf "$HERE/workspace/$NAME"
cp -a "$BASE" "$HERE/workspace/$NAME"
STAMP=$(date +%H%M%S)
cp "$TASK" ~/ai-agent-workspace/queue/${NAME}_$STAMP.txt
cd "$HERE"
exec ./venv/bin/python worker.py --once "$@"
