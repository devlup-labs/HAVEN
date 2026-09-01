#!/bin/bash

set -e #command to make it stop if any command fails to run

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)" #directory where this file lives in

echo "======================================"
echo "        HAVEN Test Environment"
echo "======================================"
echo


#Build the firmware
echo "[launcher] Building firmware..."
"$PROJECT_ROOT/build.sh"
echo

#Start TCP server
echo "[launcher] Starting TCP server..."
python3 "$PROJECT_ROOT/bridge/tcp_test_server.py" &
SERVER_PID=$!

echo "[launcher] TCP server Process ID(PID): $SERVER_PID"

#Start renode
echo "[launcher] Starting Renode..."
renode "$PROJECT_ROOT/renode/haven.resc" &
RENODE_PID=$!

echo "[launcher] Renode PID: $RENODE_PID"

#start tcp bridge
echo "[launcher] Starting TCP bridge..."
python3 "$PROJECT_ROOT/bridge/uart_tcp_bridge.py"