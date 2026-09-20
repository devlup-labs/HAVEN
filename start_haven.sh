#!/bin/bash

set -e

cleanup() {
    echo
    echo "[launcher] Shutting down HAVEN..."

    if [ -n "$RENODE_PID" ]; then
        kill "$RENODE_PID" 2>/dev/null || true
    fi
    
    if [ -f "/tmp/haven_bridges.pids" ]; then
        while read -r pid; do
            kill "$pid" 2>/dev/null || true
        done < "/tmp/haven_bridges.pids"
    fi

    if [ -n "$NS3_PID" ]; then
        kill "$NS3_PID" 2>/dev/null || true
    fi

    echo "[launcher] HAVEN stopped."
}

trap cleanup INT TERM

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
rm -f /tmp/haven_bridges.pids

NUM_NODES=${1:-3}

echo "======================================"
echo "        HAVEN Multi-Node Test Env"
echo "        Nodes: $NUM_NODES"
echo "======================================"
echo

# Build the firmware
echo "[launcher] Building firmware..."
"$PROJECT_ROOT/firmware/build.sh"
echo

# Generate Renode config
echo "[launcher] Generating Renode script for $NUM_NODES nodes..."
python3 "$PROJECT_ROOT/scripts/generate_renode_multi.py" $NUM_NODES

# Start NS-3
echo "[launcher] Starting NS-3..."
cd /home/akshat/ns-3.46
./ns3 run "scratch/ns3_tcp_bridge --numNodes=$NUM_NODES" &
NS3_PID=$!
cd "$PROJECT_ROOT"

# Wait for NS-3 to start its TCP servers
sleep 2

# Start renode
echo "[launcher] Starting Renode..."
renode "$PROJECT_ROOT/renode/haven_multi.resc" &
sleep 2
RENODE_PID=$(pgrep -n -f "dotnet /opt/renode/bin/Renode.dll $PROJECT_ROOT/renode/haven_multi.resc" || echo $!)
echo "[launcher] Renode PID: $RENODE_PID"

# Start TCP bridges
echo "[launcher] Starting TCP bridges..."
for i in $(seq 1 $NUM_NODES); do
    PORT=$((4999 + i))
    UART="/tmp/haven_uart_$i"
    
    gnome-terminal -- bash -c "python3 '$PROJECT_ROOT/bridge/uart_tcp_bridge.py' --uart '$UART' --port $PORT --node-id $i; sleep 5" &
    BRIDGE_TERMINAL_PID=$!
    # Note: tracking gnome-terminal pid isn't perfect, but we can't easily capture the inner python pid here.
    # In a real setup, running in background without gnome-terminal is easier for tracking, but keeping it for visibility.
    echo "$BRIDGE_TERMINAL_PID" >> /tmp/haven_bridges.pids
done

echo
echo "[launcher] HAVEN is running."
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