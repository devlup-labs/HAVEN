#!/bin/bash

set -e #command to make it stop if any command fails to run

cleanup() {
    echo
    echo "[launcher] Shutting down HAVEN..."

    if [ -n "$RENODE_PID" ]; then
        kill "$RENODE_PID" 2>/dev/null || true
    fi

    if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    fi

    if [ -n "$BRIDGE_PID" ]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
    fi

    echo "[launcher] HAVEN stopped."
}

trap cleanup INT TERM

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)" #directory where this file lives in

#remove all stale files
rm -f /tmp/haven_server.pid /tmp/haven_bridge.pid

echo "======================================"
echo "        HAVEN Test Environment"
echo "======================================"
echo


#Build the firmware
echo "[launcher] Building firmware..."
"$PROJECT_ROOT/firmware/build.sh"
echo


# Start TCP server
echo "[launcher] Starting TCP server..."
SERVER_PID_FILE="/tmp/haven_server.pid"

gnome-terminal -- bash -c "echo \$\$ > '$SERVER_PID_FILE'; exec python3 '$PROJECT_ROOT/bridge/tcp_test_server.py'" &
SERVER_TERMINAL_PID=$!

while [ ! -f "$SERVER_PID_FILE" ]; do
    sleep 0.1
done

SERVER_PID=$(cat "$SERVER_PID_FILE")



#Start renode
echo "[launcher] Starting Renode..."
renode "$PROJECT_ROOT/renode/haven.resc" &

sleep 1

RENODE_PID=$(pgrep -n -f "dotnet /opt/renode/bin/Renode.dll $PROJECT_ROOT/renode/haven.resc")

echo "[launcher] Renode PID: $RENODE_PID"


# Start TCP bridge
echo "[launcher] Starting TCP bridge..."

BRIDGE_PID_FILE="/tmp/haven_bridge.pid"

gnome-terminal -- bash -c "echo \$\$ > '$BRIDGE_PID_FILE'; exec python3 '$PROJECT_ROOT/bridge/uart_tcp_bridge.py'" &
BRIDGE_TERMINAL_PID=$!

while [ ! -f "$BRIDGE_PID_FILE" ]; do
    sleep 0.1
done

BRIDGE_PID=$(cat "$BRIDGE_PID_FILE")


#stoping program
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