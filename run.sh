#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import your_live_eye,requests,msgpack' 2>/dev/null; then
  .venv/bin/python -m pip install -e .
fi
exec .venv/bin/python -m your_live_eye "$@"
