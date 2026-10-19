# HAVEN: Comprehensive Runbook & Command Reference

This runbook provides complete, tested command-line procedures for running all simulation tiers, compiling firmware, executing automated test suites, and debugging individual hardware-in-the-loop components.

---

## 1. Quickstart: Interactive Web GUI Visualizer Studio

The Web Visualizer Studio provides an interactive control center with real-time network graphs, flying packet animations, node inspection, and dynamic fault injection.

### Launch the Web GUI Server
From the repository root (`HAVEN/`):

```bash
# Launch on default port 8080
./scripts/start_gui.sh

# Or launch on a custom port
./scripts/start_gui.sh --port 3000
```

Once running, navigate to **http://localhost:8080** in any modern web browser.

### Visualizer Features & Controls
- **Dual Simulation Engines**:
  - **Fast Protocol Engine (DES)**: Pure Python discrete-event protocol simulator supporting instant step-by-step frame inspection, adjustable clock speeds, and deterministic execution.
  - **Hardware Co-Simulation Platform**: Live telemetry stream connected to actual multi-instance Renode Cortex-M3 emulators and the ns-3 RF network simulator.
- **Interactive Network Canvas**: Live Vis.js graph showing node states (`DISCOVERY`, `ELECTION`, `PASSTHROUGH`, `CLAIMING`, `LEADER`), authenticated links, and animated packet flights colored by frame type.
- **Real-Time Fault Injection**:
  - Dynamically sever or restore physical links between any pair of nodes.
  - Crash or reboot specific nodes.
  - Adjust battery reserves in real time to observe dynamic leader re-convergence.
- **Node Inspector**: Click any node to inspect its assigned TurboBlom key spaces, internal fitness score, authenticated neighbor table, and pairwise symmetric keys ($K_{AB}$).
- **Packet Chronicle & Serial Console**: Live scrolling log of wire frames, MAC verification tags, and system events.

---

## 2. Full Hardware Co-Simulation (Renode + ns-3 + ZMQ)

The hardware co-simulation pipeline cross-compiles individual bare-metal C binaries for each node, spawns $N$ headless Renode Cortex-M3 emulators, and bridges their USART peripherals across an ns-3 discrete-event RF propagation network.

### First-Time Permission Setup
Ensure the master launcher script has execution permissions:
```bash
chmod +x scripts/start_haven.sh scripts/start_gui.sh
```

### Running the Co-Simulation
```bash
# Run with default configuration (configs/default_ring.conf and configs/topology_10node_ring.json)
./scripts/start_haven.sh

# Run with custom configuration and topology
./scripts/start_haven.sh --config configs/default_ring.conf --topology configs/topology_20node_ring.json

# Run for a specific duration (in seconds)
./scripts/start_haven.sh --run-seconds 60

# Enable verbose frame logging on the bridge
./scripts/start_haven.sh --verbose

# Run using the lightweight fallback Python ring switch (no ns-3 dependency)
./scripts/start_haven.sh --legacy-switch
```

### Clean Shutdown
Press `Ctrl+C` in the terminal. The launcher's trap handler will automatically terminate all Renode instances, stop the Python bridge, shutdown ns-3, and remove temporary Unix PTY symlinks and IPC sockets in `/tmp/`.

---

## 3. Embedded Firmware Compilation (ARM Cortex-M3)

The firmware targets an ARM Cortex-M3 microcontroller using the `arm-none-eabi` toolchain.

### Prerequisites (Ubuntu/Debian)
```bash
sudo apt update && sudo apt install -y \
  gcc-arm-none-eabi \
  binutils-arm-none-eabi \
  cmake \
  make
```

### Using the Firmware Build Helper Script
Navigate to `firmware/`:
```bash
cd firmware/

# Standard build (compiles build/haven.elf for default Node 1)
./build.sh

# Clean build from scratch
./build.sh -c

# Build and immediately run on QEMU (single-node smoke test)
./build.sh -r
```

### Manual Multi-Node Compilation via CMake
To build an ELF binary provisioned for a specific Node ID with custom topology constraints:
```bash
cd firmware/

# Configure for Node ID 2 with maximum degree 4
cmake -B build_node_2 \
  -DNODE_ID=2 \
  -DHAVEN_MAX_ADJ_NODES=4 \
  -DHAVEN_ECHO_THRESHOLD=2

# Compile the ELF binary
cmake --build build_node_2
```

---

## 4. Python Test Suites & Algorithmic Tools

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Test Suite (pytest)
```bash
# Run all tests with PYTHONPATH pointing to repository root
PYTHONPATH=. pytest test_simulation/tests/ -v

# Run specific test modules:
PYTHONPATH=. pytest test_simulation/tests/test_turboblom.py -v
PYTHONPATH=. pytest test_simulation/tests/test_provision.py -v
PYTHONPATH=. pytest test_simulation/tests/test_ring_election.py -v
PYTHONPATH=. pytest test_simulation/tests/test_network_split_join.py -v
```

### Running Algorithmic Reference Tools
```bash
# Execute TurboBlom key derivation reference and self-test
PYTHONPATH=. python3 test_simulation/turboblom.py

# Generate a new random connected topology (Erdos-Renyi, Ring, Line, or Star)
PYTHONPATH=. python3 test_simulation/gen_topology.py \
  --nodes 10 \
  --type ring \
  --loss-pct 0 \
  --delay-ms 20 \
  --out topology.json

# Compute valid Hamilton cycles ensuring adjacent nodes share key spaces
PYTHONPATH=. python3 test_simulation/compute_ring_order.py \
  --nodes 10 \
  --m 12 \
  --k 5
```

---

## 5. Step-by-Step Manual Component Bring-Up & Debugging

When diagnosing communication faults or bringing up individual pieces of the co-simulation stack manually:

### 1. Launch a Standalone Renode Instance
```bash
renode renode/haven.resc
```

### 2. Inspect Active PTY Serial Endpoints
Renode creates a symlink pointing to the emulated USART's pseudo-terminal:
```bash
ls -l /tmp/haven_uart*
# Example output: /tmp/haven_uart -> /dev/pts/3
```

### 3. Read Raw Serial Output from Firmware
```bash
# Open raw serial feed from the emulated terminal
cat /tmp/haven_uart
```

### 4. Run the UART <-> ZeroMQ Co-Simulation Bridge
In a separate terminal:
```bash
PYTHONPATH=. python3 bridge/uart_bridge.py \
  --topology topology.json \
  --zmq-endpoint ipc:///tmp/haven_zmq.sock \
  --verbose
```

### 5. Monitor ZeroMQ Network Traffic
You can inspect active frames passing over the ZeroMQ socket using Python or `socat`:
```bash
# Verify socket exists
ls -l /tmp/haven_zmq.sock
```

---

## 6. Troubleshooting & Common Pitfalls

| Symptom | Cause | Solution |
|:---|:---|:---|
| `renode: command not found` | Renode is not installed or not on `$PATH`. | Install Renode via package manager or specify path in `configs/default_ring.conf` (`RENODE_BIN=/opt/renode/bin/renode`). |
| `Address already in use` during Renode startup | Multiple Renode instances attempting to bind monitor port 1234. | Verify `scripts/start_haven.sh` passes `--port -1` to disable the telnet monitor for worker instances. |
| `ImportError: No module named ...` | Python path does not include the project root. | Always run Python commands with `PYTHONPATH=.` or activate the local virtual environment. |
| `Link establishment failed (K_AB is None)` | Adjacent nodes in topology do not share any TurboBlom key spaces. | Run `test_simulation/compute_ring_order.py` to ensure valid space distribution or increase $k$ in `configs/topology_10node_ring.json`. |
| PTY devices or sockets lingering after crash | Previous run was forcefully killed without triggering cleanup traps. | Run: `rm -f /tmp/haven_uart* /tmp/haven_zmq.sock /tmp/haven_events.jsonl` |