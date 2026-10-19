# HAVEN: Hardened Authenticated Voter Election Network

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Cortex-M3](https://img.shields.io/badge/Target-ARM%20Cortex--M3-brightgreen.svg)]()
[![Emulator](https://img.shields.io/badge/Emulator-Renode%20%7C%20QEMU-orange.svg)]()
[![Tests](https://img.shields.io/badge/Tests-180%20passed-success.svg)]()
[![DevLUp Labs](https://img.shields.io/badge/Research-DevLUp%20Labs-blueviolet.svg)](https://github.com/devlup-labs)

**HAVEN** (**H**ardened **A**uthenticated **V**oter **E**lection **N**etwork) is an authenticated distributed max-consensus leader election protocol engineered for sparse, adversarial wireless sensor networks (WSNs). 

Designed specifically for resource-constrained embedded targets (such as ARM Cortex-M microcontrollers), HAVEN operates strictly using **symmetric cryptography only** — eliminating the computational overhead, flash consumption, and vulnerability to side-channel timing attacks associated with Public Key Infrastructure (PKI) and asymmetric signatures.

> 📖 **Deep Dive Documentation**: For mathematical proofs, formal state machines, wire formats, and extended architectural analysis, refer to the comprehensive manuals in the [`docs/`](docs/) directory:
> - [`docs/architecture.md`](docs/architecture.md) — Multi-tier co-simulation pipeline & hardware emulation architecture
> - [`docs/run_commands.md`](docs/run_commands.md) — Comprehensive runbook, CLI reference, and troubleshooting guide
> - [`docs/PSEUDOCODE.md`](docs/PSEUDOCODE.md) — Complete 13-phase protocol pseudocode, invariants, and algorithms
> - [`docs/progress_report.md`](docs/progress_report.md) — Implementation verification benchmarks and footprint measurements

---

## Table of Contents

1. [Key Protocol Innovations](#key-protocol-innovations)
2. [Protocol Architecture](#protocol-architecture)
3. [System Requirements & Prerequisites](#system-requirements--prerequisites)
4. [Environment Setup & Installation](#environment-setup--installation)
5. [Repository Structure](#repository-structure)
6. [Building the Embedded Firmware](#building-the-embedded-firmware)
7. [Running HAVEN (All Execution Tiers)](#running-haven-all-execution-tiers)
   - [Tier 1: Interactive Web GUI Visualizer Studio](#tier-1-interactive-web-gui-visualizer-studio)
   - [Tier 2: Full Hardware Co-Simulation (Renode Multi-Node Ring)](#tier-2-full-hardware-co-simulation-renode-multi-node-ring)
   - [Tier 3: Algorithmic Reference & Topology Tools](#tier-3-algorithmic-reference--topology-tools)
   - [Tier 4: Automated Test Suite (pytest)](#tier-4-automated-test-suite-pytest)
8. [Documentation Guide (`docs/`)](#documentation-guide-docs)
9. [Key Protocol Parameters & Threat Model](#key-protocol-parameters--threat-model)
10. [Troubleshooting & Common Pitfalls](#troubleshooting--common-pitfalls)
11. [Contributing & Research Credits](#contributing--research-credits)

---

## Key Protocol Innovations

- **TurboBlom Key Pre-Distribution**: An efficient $\text{GF}(2)$ row-XOR symmetric key pre-distribution scheme (rooted in Blom's polynomials) that allows any two sensor nodes sharing at least one key space to derive an authenticated 16-byte symmetric pairwise key ($K_{AB}$) in under $10\,\mu\text{s}$ on Cortex-M hardware.
- **Perimeter Authentication (Layer 2)**: All physical links are mutually authenticated via a 3-way challenge-response handshake with HMAC-SHA256 authentication tags before any routing occurs, preventing Sybil nodes and wire injection from touching the election core.
- **Priority-Pruned Consensus (Layer 3)**: Nodes evaluate candidate fitness based on residual battery reserves and topological degree. Higher-priority candidates suppress lower-priority claims across the graph, guaranteeing fast convergence with minimal wireless airtime.
- **Resonance Echo Counting**: Candidates require echo confirmation from multiple independent directions before declaring leadership, preventing unauthenticated edge-claim partitions.
- **Dynamic Partition Split & Join (Phases 12–13)**: Autonomous network partition detection, independent cluster leader emergence during graph severing, and clean global re-election upon physical link restoration.
- **Zero Dynamic Allocation ($O(1)$ RAM)**: The entire firmware runs without `malloc()` or dynamic heaps, with a BSS footprint under 400 bytes, making it immune to heap fragmentation and memory leaks.

---

## Protocol Architecture

HAVEN is structured as four strictly isolated layers:

```
┌────────────────────────────────────────────────────────┐
│ Layer 3: Authenticated Max-Consensus Election          │
│          Priority pruning, echo counting, claim timers │
├────────────────────────────────────────────────────────┤
│ Layer 2: Node Authentication & Link Framing            │
│          Streaming parser (0xA5 SOF), 16-byte HMAC tag │
├────────────────────────────────────────────────────────┤
│ Layer 1: TurboBlom Key Pre-Distribution                │
│          HMAC row generation, XOR key-space derivation │
├────────────────────────────────────────────────────────┤
│ Layer 0: Secure Deployment Provisioning                │
│          K_master derivation, deterministic space sets │
└────────────────────────────────────────────────────────┘
```

1. **Layer 0 (Provisioning)**: In a trusted provisioning environment, each node $i$ is assigned $k$ key spaces out of $m$ total spaces deterministically using $K_{\text{master}}$.
2. **Layer 1 (Key Derivation)**: During neighbour discovery, nodes exchange assigned space indices. If $\text{spaces}(A) \cap \text{spaces}(B) \ne \emptyset$, both nodes compute identical pairwise symmetric keys $K_{AB}$.
3. **Layer 2 (Authentication)**: Nodes authenticate pairwise links using 3-way challenge-response exchanges. Every link frame carries an HMAC-SHA256 tag computed with $K_{AB}$.
4. **Layer 3 (Consensus)**: Inside the authenticated perimeter, nodes run max-consensus. Candidates flood claims with resonance verification. The node with the highest composite fitness score becomes the network leader and emits periodic signed heartbeats.

---

## System Requirements & Prerequisites

The HAVEN framework has been tested on **Ubuntu 20.04 / 22.04 / 24.04 LTS**, **Debian 12**, and **WSL2 (Ubuntu on Windows)**.

### Toolchain & System Packages
To compile bare-metal firmware and run multi-node co-simulations, install the required system packages:

```bash
sudo apt update && sudo apt install -y \
    gcc-arm-none-eabi \
    binutils-arm-none-eabi \
    cmake \
    make \
    git \
    python3 \
    python3-pip \
    python3-venv \
    qemu-system-arm
```

### Hardware Emulators

1. **Renode (Cortex-M Multi-Instance Co-Simulation)**:
   - **Required** for multi-node hardware-in-the-loop co-simulation (`scripts/start_haven.sh`).
   - Download the official `.deb` package (version $\ge 1.16.1$) from the [Renode Releases](https://github.com/renode/renode/releases):
     ```bash
     wget https://github.com/renode/renode/releases/download/v1.16.1/renode_1.16.1_amd64.deb
     sudo apt install -y ./renode_1.16.1_amd64.deb
     ```
   - Verify: `renode --version`

2. **QEMU ARM (Single-Node Smoke Testing)**:
   - Installed via `qemu-system-arm`.
   - Used by `firmware/build.sh -r` for rapid single-binary testing (`-M lm3s6965evb`).

3. **ns-3 Network Simulator (Optional - Discrete-Event RF)**:
   - Models physical 802.15.4 radio propagation, stochastic packet drops, and path delays via `ns3/haven_csim.cc` linking with ZeroMQ (`libzmq3-dev`).
   - If ns-3 is not installed, HAVEN includes a lightweight pure-Python virtual switch fallback (`--legacy-switch`) that models identical frame timing without external C++ dependencies.

---

## Environment Setup & Installation

### Step 1: Clone the Repository with Submodules
HAVEN embeds **mbedTLS** as a submodule for hardware-optimized cryptographic primitives (HMAC, SHA-256).

```bash
# Clone repository
git clone https://github.com/devlup-labs/HAVEN.git
cd HAVEN

# Initialize and pull cryptographic submodules
git submodule update --init --recursive
```

### Step 2: Configure Python Virtual Environment
Install all core, visualizer, and simulation dependencies into an isolated virtual environment:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python packages according to official specifications
pip install -r requirements.txt
```

Verify Python packages:
```bash
python3 -c "import aiohttp, zmq, pytest, networkx, numpy; print('Environment OK!')"
```

---

## Repository Structure

```
HAVEN/
├── firmware/                  # Bare-metal C implementation for ARM Cortex-M3
│   ├── src/                   # C source files (haven.c, turboblom.c, haven_link.c, etc.)
│   ├── include/               # Public headers (haven.h, turboblom.h, haven_config.h)
│   ├── mbedtls/               # Git submodule: mbedTLS cryptographic primitives
│   ├── build.sh               # Convenience compilation and QEMU test script
│   ├── CMakeLists.txt         # CMake build definition for arm-none-eabi
│   └── linker.ld              # Cortex-M3 memory layout and linker script
│
├── renode/                    # Renode hardware simulation models
│   ├── haven.repl             # Cortex-M3 machine platform description (CPU, RAM, Flash, USART)
│   ├── haven.resc             # Renode script template for PTY serial endpoint attachment
│   └── test_semihosting.repl  # Platform description for semihosted testing
│
├── bridge/                    # Virtual network switches & serial bridge
│   ├── ring_switch.py         # Pure-Python virtual radio ring switch (zero external C++ deps)
│   ├── uart_bridge.py         # Multi-threaded PTY <-> ZeroMQ bridge for ns-3 co-simulation
│   ├── uart_tcp_bridge.py     # TCP socket bridge for remote emulator endpoints
│   └── tcp_test_server.py     # Diagnostic socket harness
│
├── configs/                   # Single-source-of-truth network configurations
│   ├── default_ring.conf      # Default ring parameters (node count, timeouts, hop delays)
│   ├── topology_10node_ring.json # Primary 10-node network definition (coordinates, spaces, links)
│   └── topology_20node_ring.json # 20-node pre-configured topology for large-scale simulations
│
├── scripts/                   # Master orchestrators and startup scripts
│   ├── start_haven.sh         # Master launcher: compiles node ELFs, starts switch & Renode nodes
│   └── start_gui.sh           # Web Visualizer Studio launcher (runs gui/server.py on port 8080)
│
├── gui/                       # Interactive Web Visualizer Studio & simulation engine
│   ├── index.html             # Single-page control cockpit and network canvas
│   ├── server.py              # Async web server (aiohttp) and WebSocket telemetry streamer
│   ├── haven_sim_engine.py    # Deterministic discrete-event simulation engine with chaos controls
│   ├── js/                    # Client UI logic (app.js, network_graph.js via Vis.js)
│   └── css/                   # Visualizer styling & dark-theme telemetry dashboard
│
├── test_simulation/           # Python algorithmic reference models & pytest suites
│   ├── turboblom.py           # TurboBlom reference implementation and KDF validation
│   ├── gen_topology.py        # Graph generator (Erdos-Renyi, Ring, Line, Star)
│   ├── compute_ring_order.py  # Hamiltonian cycle finder ensuring adjacent nodes share key spaces
│   ├── network_sim.py         # NetworkX resilience simulation & node-capture analysis
│   └── tests/                 # Comprehensive test suite (180 automated unit & integration tests)
│
├── ns3/                       # ns-3 discrete-event RF propagation simulator
│   ├── haven_csim.cc          # C++ co-simulation engine bridging ns-3 and ZeroMQ
│   └── CMakeLists.txt         # Build definitions for ns-3 co-simulation
│
├── docs/                      # Formal protocol specifications & technical reference manuals
│   ├── architecture.md        # Detailed hardware & co-simulation pipeline design
│   ├── run_commands.md        # Comprehensive runbook with all CLI commands and options
│   ├── PSEUDOCODE.md          # 13-phase formal pseudocode, invariants, and algorithms
│   └── progress_report.md     # Benchmarks, memory footprint audits, and sprint reports
│
├── pytest.ini                 # Pytest discovery configuration
├── requirements.txt           # Standard Python package manifest
└── README.md                  # This file
```

---

## Building the Embedded Firmware

The embedded firmware is written in clean, MISRA-conscious bare-metal C for ARM Cortex-M3.

### Using the Convenience Build Helper
Navigate to `firmware/` and use `build.sh`:

```bash
cd firmware/

# 1. Standard build (compiles build/haven.elf for default Node ID 1)
./build.sh

# 2. Clean build from scratch
./build.sh -c

# 3. Build and execute immediate single-node smoke test on QEMU
./build.sh -r
```

### Manual Cross-Compilation via CMake
To compile a specific ELF binary provisioned for Node ID $2$ with custom adjacency limits:

```bash
cd firmware/
cmake -B build_node_2 \
    -DNODE_ID=2 \
    -DHAVEN_MAX_ADJ_NODES=4 \
    -DHAVEN_ECHO_THRESHOLD=2

cmake --build build_node_2
```

### Firmware Memory Footprint (Measured)
```
   text    data     bss     dec     hex filename
  21348    2120     364   23832    5d18 build/haven.elf
```
- **Flash (text + data)**: $\approx 23.4\,\text{KB}$ (well within 64 KB microcontrollers)
- **RAM (bss)**: $364\,\text{bytes}$ (leaving $>99\%$ of Cortex-M3 RAM available)

---

## Running HAVEN (All Execution Tiers)

HAVEN supports four execution tiers, ranging from an interactive visual browser studio to automated unit testing.

### Tier 1: Interactive Web GUI Visualizer Studio

The Visualizer Studio is an interactive control center featuring live network graphs, real-time flying packet animations, interactive node inspectors, and dynamic fault injection.

```bash
# Launch on default port 8080
./scripts/start_gui.sh

# Or specify a custom port
./scripts/start_gui.sh --port 3000
```
Open **`http://localhost:8080`** in any web browser.

#### Studio Capabilities:
- **Dual Execution Engines**: Seamlessly switch between the **Fast DES Protocol Engine** (instant stepping, live chaos, millisecond clock controls) and the **Full Hardware Co-Simulation** (live telemetry stream connected to actual multi-instance Renode Cortex-M3 emulators).
- **Interactive Network Graph**: Live Vis.js canvas displaying node operational modes (`DISCOVERY`, `ELECTION`, `PASSTHROUGH`, `CLAIMING`, `LEADER`), authenticated links, and animated packet flights colored by frame type.
- **Real-Time Fault Injection**:
  - Dynamically sever or reconnect physical links.
  - Crash or revive individual nodes.
  - Dynamically adjust battery reserves to observe real-time leader re-convergence.
- **Node Inspector**: Click any node to inspect its assigned TurboBlom key spaces, internal fitness score, authenticated neighbor table, and derived symmetric keys ($K_{AB}$).
- **Packet Chronicle & Serial Console**: Live scrolling log of wire frames, MAC verification tags, and system events.

---

### Tier 2: Full Hardware Co-Simulation (Renode Multi-Node Ring)

The co-simulation pipeline cross-compiles individual bare-metal C binaries for each node, spawns $N$ headless Renode Cortex-M3 emulators, and bridges their USART peripherals across a virtual radio switch.

```bash
# 1. Run with default ring configuration (configs/default_ring.conf) using lightweight Python switch
./scripts/start_haven.sh --legacy-switch

# 2. Run with custom topology and verbose serial frame logging
./scripts/start_haven.sh --legacy-switch --topology configs/topology_10node_ring.json --verbose

# 3. Run for a specific duration (in seconds)
./scripts/start_haven.sh --legacy-switch --run-seconds 60

# 4. Run using the ns-3 discrete-event RF propagation simulator (if ns-3 binary is built)
./scripts/start_haven.sh --topology configs/topology_10node_ring.json
```

**Clean Shutdown**: Press `Ctrl+C`. The launcher trap handler terminates all Renode instances and child processes, cleans up temporary PTY symlinks (`/tmp/haven_uart_*`), and removes temporary IPC sockets.

---

### Tier 3: Algorithmic Reference & Topology Tools

HAVEN provides standalone algorithmic reference scripts in `test_simulation/`:

```bash
# 1. Execute TurboBlom key derivation reference and self-test
python3 test_simulation/turboblom.py

# 2. Generate a deterministic connected topology (Erdos-Renyi, Ring, Line, or Star)
python3 test_simulation/gen_topology.py \
    --nodes 10 \
    --type ring \
    --loss-pct 0 \
    --delay-ms 20 \
    --out my_topology.json

# 3. Compute valid Hamiltonian cycles ensuring adjacent nodes share key spaces
python3 test_simulation/compute_ring_order.py \
    --nodes 10 \
    --m 12 \
    --k 5

# 4. Run NetworkX topology resilience analysis and node-capture security evaluation
python3 test_simulation/network_sim.py
```

---

### Tier 4: Automated Test Suite (pytest)

The test suite contains 180 unit, integration, and topology tests validating all protocol layers, mathematical invariants, framing edge cases, and REST endpoints:

```bash
# Run all tests from the repository root
pytest

# Run tests with verbose output
pytest -v

# Run a specific test module
pytest test_simulation/tests/test_turboblom.py -v
pytest test_simulation/tests/test_ring_switch.py -v
pytest test_simulation/tests/test_network_split_join.py -v
```

---

## Documentation Guide (`docs/`)

For in-depth research, formal proofs, and technical specifications, please consult the documents in the [`docs/`](docs/) directory:

| Document | Purpose & Key Topics Covered |
|:---|:---|
| [`docs/architecture.md`](docs/architecture.md) | **System Architecture & Co-Simulation Pipeline**: Deep dive into Renode hardware modeling, USART PTY bridging, ns-3 RF propagation co-simulation, zero-copy packet flow, and hardware memory footprints. |
| [`docs/run_commands.md`](docs/run_commands.md) | **Comprehensive Runbook & Command Reference**: Tested command-line recipes for every component, manual step-by-step bringup procedures, and troubleshooting diagnostic matrix. |
| [`docs/PSEUDOCODE.md`](docs/PSEUDOCODE.md) | **Formal Protocol Pseudocode**: Complete algorithmic specifications for all 13 phases, state transitions, resonance echo math, timing invariants, and partition split/join handlers. |
| [`docs/progress_report.md`](docs/progress_report.md) | **Engineering Progress & Benchmarks**: Sprint milestones, memory footprint audits, convergence latency measurements, and future roadmap. |

---

## Key Protocol Parameters & Threat Model

### Default Operational Parameters

| Parameter | Symbol | Shipped Value | Design Justification |
|:---|:---:|:---:|:---|
| Total Key Spaces | $m$ | $12$ | Allows $\approx 99\%$ pairwise key sharing probability with $k=5$ |
| Key Spaces per Node | $k$ | $5$ | Guaranteed Hamilton cycle feasibility across ring topologies |
| Polynomial Threshold | $\lambda$ | $3$ | Resistance to collusion attacks up to $\lambda$ compromised nodes |
| Symmetric MAC Primitive | — | HMAC-SHA256 | Truncated to 16 bytes; execute in $<5\,\mu\text{s}$ on Cortex-M |
| Start-of-Frame Delimiter | SOF | `0xA5` | High Hamming distance from preamble noise |
| Resonance Echo Threshold | — | $2$ | Prevents single-edge unverified claim storms |
| Discovery Window | $T_{\text{window}}$ | $5000\,\text{ms}$ | Allows sparse radio networks to stabilize before drawing claims |
| Claim Delay | $T_{\text{claim}}$ | $5000\,\text{ms}$ | Ensures resonance echoes traverse full network circumference |

### Threat Model Summary
- **Adversary Capabilities**: The adversary can eavesdrop, intercept, replay, drop messages, and attempt MitM attacks on wireless channels.
- **Physical Node Compromise**: Up to $\lambda$ nodes can be captured without compromising the pairwise security of uncaptured node links.
- **Crash Fault Tolerance**: Nodes can crash, run out of battery, or suffer link cuts. Inside the authenticated perimeter, the network converges to the highest-priority surviving candidate.

---

## Troubleshooting & Common Pitfalls

| Symptom | Probable Cause | Recommended Resolution |
|:---|:---|:---|
| `mbedtls/CMakeLists.txt: No such file or directory` | Submodule uninitialized | Run `git submodule update --init --recursive` from repo root. |
| `renode: command not found` | Renode not installed or not on `$PATH` | Install Renode $\ge 1.16.1$ via `.deb` package or specify path in `configs/default_ring.conf` (`RENODE_BIN=/opt/renode/bin/renode`). |
| `Address already in use (port 1234)` during Renode launch | Renode telnet monitor collision | Verify `scripts/start_haven.sh` assigns individual ports (`--port=1235`, `--port=1236`, etc.) or passes `--port -1`. |
| `ImportError: No module named '...'` | Virtual environment not active | Activate virtual environment (`source .venv/bin/activate`) or verify `requirements.txt` is installed. |
| `Link establishment failed (K_AB is None)` | Adjacent nodes do not share any key spaces | Run `python3 test_simulation/compute_ring_order.py --nodes N --m 12 --k 5` to compute a valid Hamiltonian cycle. |
| Lingering PTYs or sockets after crash | Previous run killed forcefully without cleanup trap | Run: `rm -f /tmp/haven_uart_* /tmp/haven_zmq.sock /tmp/haven_events.jsonl` |

---

## Contributing & Research Credits

HAVEN is an open research project developed under **[DevLUp Labs](https://github.com/devlup-labs)**.

- **Foundational Research**:
  - Karlof & Wagner (2003) — *Secure Routing in Wireless Sensor Networks*
  - Zhao, Yağan, Gligor (2019) — *Connectivity in Random Key Graphs With Unreliable Links*
  - Blin & Tixeuil (2020) — *Compact Self-Stabilizing Leader Election for Arbitrary Graphs*
- **Contributions**: Pull requests are welcome! Please make sure that any functional protocol changes pass the test suite (`pytest`) and adhere to the zero-dynamic-allocation rule for `firmware/`.
- **License**: Released under the MIT License.

## Contributing & Research Credits

HAVEN is an open research project developed under **[DevLUp Labs](https://github.com/devlup-labs)**.

- **Foundational Research**:
  - Karlof & Wagner (2003) — *Secure Routing in Wireless Sensor Networks*
  - Zhao, Yağan, Gligor (2019) — *Connectivity in Random Key Graphs With Unreliable Links*
  - Blin & Tixeuil (2020) — *Compact Self-Stabilizing Leader Election for Arbitrary Graphs*
- **Contributions**: Pull requests are welcome! Please make sure that any functional protocol changes pass the test suite (`pytest`) and adhere to the zero-dynamic-allocation rule for `firmware/`.
- **License**: Released under the MIT License.

