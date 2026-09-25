#!/bin/bash

set -e # Stop on any error

NUM_NODES=${1:-5}

cleanup() {
    echo
    echo "[launcher] Shutting down HAVEN cluster (${NUM_NODES} nodes)..."

    if [ -n "$RENODE_PID" ]; then
        kill "$RENODE_PID" 2>/dev/null || true
    fi

    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi

    if [ -n "$BRIDGE_PID" ]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
    fi

    # Clean up any lingering python bridge/server processes
    pkill -f "uart_tcp_bridge.py" 2>/dev/null || true
    pkill -f "tcp_test_server.py" 2>/dev/null || true

    echo "[launcher] HAVEN stopped."
}

trap cleanup INT TERM

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Clean stale PID files and PTY endpoints
rm -f /tmp/haven_server.pid /tmp/haven_bridge.pid
rm -f /tmp/haven_uart*

echo "=================================================="
echo "        HAVEN Test Environment (${NUM_NODES} Nodes)       "
echo "=================================================="
echo

# 1. Build the firmware
echo "[launcher] Building firmware..."
"$PROJECT_ROOT/firmware/build.sh"
echo

# 2. Generate Renode resc configuration for NUM_NODES
echo "[launcher] Generating Renode script for ${NUM_NODES} nodes..."
python3 "$PROJECT_ROOT/renode/generate_network.py" "$NUM_NODES" "$PROJECT_ROOT/renode/haven.resc"
echo

# 3. Start Network Server / ns-3 Bridge
# If ns3 binary exists, run ns3, otherwise run multi-node mock server
echo "[launcher] Starting Network Server for ${NUM_NODES} nodes..."
SERVER_PID_FILE="/tmp/haven_server.pid"

gnome-terminal -- bash -c "echo \$\$ > '$SERVER_PID_FILE'; exec python3 '$PROJECT_ROOT/bridge/tcp_test_server.py' '$NUM_NODES'" &

while [ ! -f "$SERVER_PID_FILE" ]; do
    sleep 0.1
done
SERVER_PID=$(cat "$SERVER_PID_FILE")

# 4. Start Renode
echo "[launcher] Starting Renode with ${NUM_NODES} virtual nodes..."
renode "$PROJECT_ROOT/renode/haven.resc" &

sleep 2
RENODE_PID=$(pgrep -n -f "Renode.*haven.resc" || true)
echo "[launcher] Renode PID: $RENODE_PID"

# 5. Start Multi-Node TCP Bridge
echo "[launcher] Starting Multi-Node UART-TCP Bridge..."
BRIDGE_PID_FILE="/tmp/haven_bridge.pid"

gnome-terminal -- bash -c "echo \$\$ > '$BRIDGE_PID_FILE'; exec python3 '$PROJECT_ROOT/bridge/uart_tcp_bridge.py' '$NUM_NODES'" &

while [ ! -f "$BRIDGE_PID_FILE" ]; do
    sleep 0.1
done
BRIDGE_PID=$(cat "$BRIDGE_PID_FILE")

echo
echo "[launcher] HAVEN is running with ${NUM_NODES} nodes."
echo "[launcher] Ports ${PROJECT_ROOT}/bridge mapped: 5001..$((5000 + NUM_NODES))"
echo "[launcher] Type 'quit haven' to shut down."
echo

while true; do
    read -r command

    if [ "$command" = "quit haven" ]; then
        cleanup
        sleep 1
        exit 0
    fi
done