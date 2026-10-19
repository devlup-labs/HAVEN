#!/bin/bash
#
# HAVEN multi-node co-simulation launcher.
#
# Builds one ELF per node in the topology, launches:
# 1. ns-3 discrete-event network simulator (haven_csim)
# 2. UART <-> ZMQ bridge (uart_bridge.py)
# 3. N headless Renode instances (each with its own PTY)
#
#   ./start_haven.sh                         # run with haven_ring.conf / topology.json
#   ./start_haven.sh --topology my_topo.json # run with specific topology
#   ./start_haven.sh --config my.conf        # alternate config
#   ./start_haven.sh --verbose               # verbose frame logging
#   ./start_haven.sh --legacy-switch         # use legacy ring_switch.py instead of ns-3
#
# Press Ctrl-C to shut everything down cleanly.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

CONFIG="$PROJECT_ROOT/haven_ring.conf"
TOPOLOGY_ARG=""
VERBOSE=""
LEGACY_SWITCH=0
LOG_DIR="/tmp/haven_logs"
RUN_SECONDS_ARG=""
STOP_ON_LEADER_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)         CONFIG="$2"; shift 2 ;;
        --topology)       TOPOLOGY_ARG="$2"; shift 2 ;;
        --run-seconds)    RUN_SECONDS_ARG="$2"; shift 2 ;;
        --stop-on-leader) STOP_ON_LEADER_ARG="$2"; shift 2 ;;
        --verbose)        VERBOSE="--verbose"; shift ;;
        --legacy-switch)  LEGACY_SWITCH=1; shift ;;
        --help|-h)        sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ ! -f "$CONFIG" ]]; then
    echo "[launcher] config not found: $CONFIG" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG"

TOPOLOGY="${TOPOLOGY_ARG:-${TOPOLOGY:-$PROJECT_ROOT/topology.json}}"
NS3_BIN="${NS3_BIN:-$PROJECT_ROOT/ns3/haven_csim}"
ZMQ_ENDPOINT="${ZMQ_ENDPOINT:-ipc:///tmp/haven_zmq.sock}"
RUN_SECONDS="${RUN_SECONDS_ARG:-${RUN_SECONDS:-90}}"
STOP_ON_LEADER="${STOP_ON_LEADER_ARG:-${STOP_ON_LEADER:-3}}"

# If topology file does not exist, generate default ring topology from config
if [[ ! -f "$TOPOLOGY" ]]; then
    echo "[launcher] topology file not found; generating default ring: $TOPOLOGY"
    python3 "$PROJECT_ROOT/sim/gen_topology.py" \
        --nodes "${NUM_NODES:-3}" \
        --type ring \
        --loss-pct 0 \
        --delay-ms "${HOP_DELAY_MS:-20}" \
        --out "$TOPOLOGY"
fi

# Extract topology parameters using Python
NODE_IDS_STR=$(python3 -c "import json; t=json.load(open('$TOPOLOGY')); print(' '.join(str(n['id']) for n in t['nodes']))")
read -r -a NODE_IDS <<< "$NODE_IDS_STR"
NUM_NODES=${#NODE_IDS[@]}
MAX_ADJ_NODES=$(python3 -c "import json; t=json.load(open('$TOPOLOGY')); print(t.get('meta', {}).get('max_adj_nodes', 2))")
ECHO_THRESHOLD=$(python3 -c "import json; t=json.load(open('$TOPOLOGY')); print(t.get('meta', {}).get('echo_threshold', 2))")

RENODE_PIDS=()
BRIDGE_PID=""
NS3_PID=""

cleanup() {
    echo
    echo "[launcher] shutting down HAVEN co-simulation..."

    if [[ -n "$BRIDGE_PID" ]]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
    fi
    if [[ -n "$NS3_PID" ]]; then
        kill "$NS3_PID" 2>/dev/null || true
    fi

    # Kill Renode instances (dotnet child processes included)
    for pid in "${RENODE_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        pkill -TERM -P "$pid" 2>/dev/null || true
        kill "$pid" 2>/dev/null || true
    done
    sleep 0.5
    for pid in "${RENODE_PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill -KILL "$pid" 2>/dev/null || true
    done

    # Clean PTY symlinks and ZMQ socket
    for node_id in "${NODE_IDS[@]}"; do
        rm -f "/tmp/haven_uart_$node_id" 2>/dev/null || true
    done
    rm -f /tmp/haven_zmq.sock 2>/dev/null || true

    echo "[launcher] stopped."
}
trap cleanup INT TERM EXIT

echo "======================================"
echo "    HAVEN Co-Simulation Environment   "
echo "======================================"
echo
echo "[launcher] config          $(basename "$CONFIG")"
echo "[launcher] topology        $TOPOLOGY"
echo "[launcher] nodes           $NUM_NODES (${NODE_IDS[*]})"
echo "[launcher] max degree      $MAX_ADJ_NODES"
echo "[launcher] echo threshold  $ECHO_THRESHOLD"
echo "[launcher] network backend $(if [[ $LEGACY_SWITCH -eq 1 ]]; then echo 'legacy ring_switch.py'; else echo 'ns-3 (haven_csim) + ZMQ'; fi)"
echo

# ---------------------------------------------------------------- validation
if [[ $LEGACY_SWITCH -eq 1 ]]; then
    if ! python3 "$PROJECT_ROOT/bridge/ring_switch.py" --config "$CONFIG" --check; then
        echo "[launcher] ring topology invalid; aborting." >&2
        exit 1
    fi
fi

# -------------------------------------------------------------------- build
echo "[launcher] building $NUM_NODES firmware images..."
BUILD_FAILED=0
ELFS=()
for node_id in "${NODE_IDS[@]}"; do
    build_dir="$PROJECT_ROOT/firmware/build_node_$node_id"
    if ! (cd "$PROJECT_ROOT/firmware" && cmake -B "$build_dir" \
        -DNODE_ID="$node_id" \
        -DHAVEN_MAX_ADJ_NODES="$MAX_ADJ_NODES" \
        -DHAVEN_ECHO_THRESHOLD="$ECHO_THRESHOLD") >"$build_dir.cmake.log" 2>&1; then
        echo "[launcher]   node $node_id: cmake configure FAILED" >&2
        BUILD_FAILED=1
        continue
    fi
    if ! cmake --build "$build_dir" >"$build_dir/build.log" 2>&1; then
        echo "[launcher]   node $node_id: build FAILED (see $build_dir/build.log)" >&2
        BUILD_FAILED=1
        continue
    fi
    rm -f "$build_dir.cmake.log"
    ELFS+=("$build_dir/haven.elf")
    printf "[launcher]   node %-3s ok\n" "$node_id"
done

if [[ $BUILD_FAILED -ne 0 ]]; then
    echo "[launcher] build failed; aborting." >&2
    exit 1
fi
echo

# ------------------------------------------------------------------- renode
if ! command -v "$RENODE_BIN" >/dev/null 2>&1; then
    if [[ -x /opt/renode/bin/renode ]]; then
        RENODE_BIN=/opt/renode/bin/renode
    else
        echo "[launcher] renode not found (set RENODE_BIN in $CONFIG)" >&2
        exit 1
    fi
fi

mkdir -p "$LOG_DIR"
rm -f /tmp/haven_uart_* 2>/dev/null || true
rm -f /tmp/haven_zmq.sock 2>/dev/null || true

# ------------------------------------------------------- start network backend
if [[ $LEGACY_SWITCH -eq 1 ]]; then
    echo "[launcher] starting legacy ring switch..."
    python3 "$PROJECT_ROOT/bridge/ring_switch.py" --config "$CONFIG" $VERBOSE &
    BRIDGE_PID=$!
else
    if [[ ! -x "$NS3_BIN" ]]; then
        echo "[launcher] ns-3 binary not found at $NS3_BIN" >&2
        exit 1
    fi
    echo "[launcher] starting ns-3 simulation..."
    "$NS3_BIN" --topology="$TOPOLOGY" --zmq="$ZMQ_ENDPOINT" --duration="$RUN_SECONDS" &
    NS3_PID=$!
    echo "[launcher] ns-3 pid $NS3_PID"
    sleep 0.5

    echo "[launcher] starting UART <-> ZMQ bridge..."
    python3 "$PROJECT_ROOT/bridge/uart_bridge.py" \
        --topology="$TOPOLOGY" \
        --zmq-endpoint="$ZMQ_ENDPOINT" \
        --run-seconds="$RUN_SECONDS" \
        --stop-on-leader="$STOP_ON_LEADER" \
        $VERBOSE &
    BRIDGE_PID=$!
    echo "[launcher] bridge pid $BRIDGE_PID"
fi
echo

# ----------------------------------------------------------- start renode nodes
RESC_DIR=$(mktemp -d /tmp/haven_resc.XXXXXX)
echo "[launcher] starting $NUM_NODES Renode instances..."

idx=0
for node_id in "${NODE_IDS[@]}"; do
    elf="${ELFS[$idx]}"
    idx=$((idx + 1))
    pty="/tmp/haven_uart_$node_id"
    resc="$RESC_DIR/node_$node_id.resc"
    log="$LOG_DIR/node_$node_id.log"

    cat > "$resc" <<EOF
mach create "haven$node_id"
machine LoadPlatformDescription @$PROJECT_ROOT/renode/haven.repl
sysbus LoadELF @$elf
emulation CreateUartPtyTerminal "uart" "$pty" true
uart AttachTo sysbus.uart
start
EOF

    rm -f "$pty"
    # Assign distinct monitor port per instance so Renode never collides on 1234
    node_flags="$RENODE_FLAGS"
    node_port=$((1234 + node_id))
    if [[ "$node_flags" == *"--port=-1"* ]]; then
        node_flags="${node_flags//--port=-1/--port=$node_port}"
    elif [[ "$node_flags" == *"--port -1"* ]]; then
        node_flags="${node_flags//--port -1/--port=$node_port}"
    elif [[ "$node_flags" != *"--port"* ]]; then
        node_flags="$node_flags --port=$node_port"
    fi

    $RENODE_BIN $node_flags "$resc" >"$log" 2>&1 &
    RENODE_PIDS+=("$!")
    printf "[launcher]   node %-3s pid %-7s pty %s (port %s)\n" "$node_id" "$!" "$pty" "$node_port"
done
echo

# ------------------------------------------------------------------ monitor
echo "[launcher] logs:       $LOG_DIR/node_<id>.log"
echo "[launcher] running for ${RUN_SECONDS}s"
echo "[launcher] press Ctrl-C to stop."
echo

while kill -0 "$BRIDGE_PID" 2>/dev/null; do
    sleep 0.5
done
wait "$BRIDGE_PID"
BRIDGE_STATUS=$?
BRIDGE_PID=""

if [[ $BRIDGE_STATUS -ne 0 ]]; then
    echo
    echo "[launcher] bridge exited $BRIDGE_STATUS (no leader elected?)"
    exit "$BRIDGE_STATUS"
fi

echo "[launcher] done."