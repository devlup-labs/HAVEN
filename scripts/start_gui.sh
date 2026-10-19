#!/bin/bash
#
# HAVEN Co-Simulation Studio & Visualizer Launcher
#
# Usage:
#   ./scripts/start_gui.sh             # Run on default port 8080
#   ./scripts/start_gui.sh --port 3000 # Run on custom port
#

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

PORT=8080
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port|-p) PORT="$2"; shift 2 ;;
        --help|-h) echo "Usage: $0 [--port PORT]"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# Pick Python executable
PYTHON_BIN="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python3"
elif [[ -x "$PROJECT_ROOT/test_simulation/.venv/bin/python3" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/test_simulation/.venv/bin/python3"
fi

export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/test_simulation:$PROJECT_ROOT/bridge:${PYTHONPATH:-}"

echo "=========================================================="
echo "    🛡️ HAVEN Co-Simulation Visualizer & Control Studio"
echo "=========================================================="
echo "  Web Interface:  http://localhost:${PORT}"
echo "  Python Runtime: $PYTHON_BIN"
echo "  Project Root:   $PROJECT_ROOT"
echo "=========================================================="
echo

exec "$PYTHON_BIN" "$PROJECT_ROOT/gui/server.py" --host 0.0.0.0 --port "$PORT"
