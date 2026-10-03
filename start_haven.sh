#!/bin/bash
#
# HAVEN multi-node Renode launcher.
#
# Builds one ELF per node, starts one headless Renode instance per node (each
# with its own PTY), and runs a switch that relays frames between the two ring
# neighbours of each sender so the emulated topology is a chordal ring.
#
#   ./start_haven.sh                      # run with haven_ring.conf
#   ./start_haven.sh --config my.conf     # alternate config
#   ./start_haven.sh --verbose            # log every relayed frame
#
# Type 'quit haven' at the prompt, or Ctrl-C, to shut everything down.

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

CONFIG="$PROJECT_ROOT/haven_ring.conf"
VERBOSE=""
LOG_DIR="/tmp/haven_logs"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)  CONFIG="$2"; shift 2 ;;
        --verbose) VERBOSE=""; shift ;;
        --help|-h) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [[ ! -f "$CONFIG" ]]; then
    echo "[launcher] config not found: $CONFIG" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG"

# RING_ORDER is stored as one quoted string ("1 9 5 ...") so that both bash and
# bridge/ring_switch.py can read this file without shell expansion. Split it
# into an array here; the quotes mean "${RING_ORDER[@]}" would otherwise yield a
# single 10-element string.
read -r -a RING_ORDER <<< "$RING_ORDER"

# The config stores a full 10-node cycle and NUM_NODES selects how much of it to
# deploy. Truncate to NUM_NODES so only that many instances are built and run.
if (( ${#RING_ORDER[@]} < NUM_NODES )); then
    echo "[launcher] RING_ORDER has ${#RING_ORDER[@]} entries but NUM_NODES=$NUM_NODES" >&2
    exit 1
fi
RING_ORDER=("${RING_ORDER[@]:0:NUM_NODES}")

RENODE_PIDS=()
SWITCH_PID=""

cleanup() {
    echo
    echo "[launcher] shutting down HAVEN..."

    if [[ -n "$SWITCH_PID" ]]; then
        kill "$SWITCH_PID" 2>/dev/null || true
    fi

    # Each Renode instance is a wrapper that execs dotnet, so kill the whole
    # process group to be sure no orphaned instance survives.
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

    # PTY symlinks are recreated by Renode each run; clear stale ones so the
    # next launch cannot open a dead node by mistake.
    for node_id in "${RING_ORDER[@]}"; do
        rm -f "/tmp/haven_uart_$node_id" 2>/dev/null || true
    done

    echo "[launcher] stopped."
}
trap cleanup INT TERM EXIT

echo "======================================"
echo "        HAVEN Ring Test Environment"
echo "======================================"
echo
echo "[launcher] config      $(basename "$CONFIG")"
echo "[launcher] NUM_NODES   $NUM_NODES"
echo "[launcher] RING_ORDER  ${RING_ORDER[*]}"
echo

# ---------------------------------------------------------------- validation
# Fail before building anything if the requested ring cannot physically form.
# An unlinkable neighbour pair is silent at runtime (firmware drops the peer in
# on_discovery), so this check is what turns a silent hang into a clear error.
if ! python3 "$PROJECT_ROOT/bridge/ring_switch.py" --config "$CONFIG" --check; then
    echo "[launcher] ring topology invalid; aborting." >&2
    exit 1
fi
echo

# -------------------------------------------------------------------- build
# cmake -B only sets the binary dir; the source dir stays the cwd, so run it
# from firmware/ where CMakeLists.txt lives.
echo "[launcher] building $NUM_NODES firmware images..."
BUILD_FAILED=0
ELFS=()
for node_id in "${RING_ORDER[@]}"; do
    build_dir="$PROJECT_ROOT/firmware/build_node_$node_id"
    if ! (cd "$PROJECT_ROOT/firmware" && cmake -B "$build_dir" -DNODE_ID="$node_id") >"$build_dir.cmake.log" 2>&1; then
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

# Generate one script per instance so each gets a distinct PTY path and ELF.
RESC_DIR=$(mktemp -d /tmp/haven_resc.XXXXXX)
echo "[launcher] starting $NUM_NODES Renode instances..."

idx=0
for node_id in "${RING_ORDER[@]}"; do
    elf="${ELFS[$idx]}"
    idx=$((idx + 1))
    pty="/tmp/haven_uart_$node_id"
    resc="$RESC_DIR/node_$node_id.resc"
    log="$LOG_DIR/node_$node_id.log"

    # The leading @ is required by Renode's tokenizer for absolute paths; a
    # bare path fails with "Could not tokenize here" and no PTY is ever made.
    cat > "$resc" <<EOF
mach create "haven$node_id"
machine LoadPlatformDescription @$PROJECT_ROOT/renode/haven.repl
sysbus LoadELF @$elf
emulation CreateUartPtyTerminal "uart" "$pty" true
uart AttachTo sysbus.uart
start
EOF

    rm -f "$pty"
    # --disable-xwt is required: N GUI windows would each need their own
    # display, and the PTY is the only data path the ring needs.
    $RENODE_BIN $RENODE_FLAGS "$resc" >"$log" 2>&1 &
    RENODE_PIDS+=("$!")
    printf "[launcher]   node %-3s pid %-7s pty %s\n" "$node_id" "$!" "$pty"
done
echo

# ------------------------------------------------------------------- switch
echo "[launcher] starting ring switch..."
python3 "$PROJECT_ROOT/bridge/ring_switch.py" --config "$CONFIG" $VERBOSE &
SWITCH_PID=$!
echo "[launcher] switch pid $SWITCH_PID"
echo

# ------------------------------------------------------------------ monitor
echo "[launcher] logs:       $LOG_DIR/node_<id>.log"
echo "[launcher] running for ${RUN_SECONDS}s"
echo "[launcher] type 'quit haven' or Ctrl-C to stop."
echo

# Exit as soon as the switch does, so a failed topology is reported promptly.
while kill -0 "$SWITCH_PID" 2>/dev/null; do
    sleep 0.5
done
wait "$SWITCH_PID"
SWITCH_STATUS=$?
SWITCH_PID=""

if [[ $SWITCH_STATUS -ne 0 ]]; then
    echo
    echo "[launcher] ring switch exited $SWITCH_STATUS (no leader elected?)"
    exit "$SWITCH_STATUS"
fi

echo "[launcher] done."