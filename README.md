# HAVEN

**H**ardened **A**uthenticated **V**oter **E**lection **N**etwork

An authenticated distributed max-consensus protocol for sparse adversarial wireless sensor networks. Uses symmetric cryptography only — no PKI, no public-key operations — designed for ARM Cortex-M class hardware.

> This is a research-grade implementation project under [DevLUp Labs](https://github.com/devlup-labs). Read the full protocol design in `docs/` before touching any code.

---

## What This Project Builds

- **TurboBlom** key pre-distribution (GF(2) variant of Blom's scheme) for pairwise authentication
- **3-way HELLO** exchange for mutual node authentication
- **Authenticated max-consensus election** with priority-pruned flooding
- Firmware targeting ARM Cortex-M3, emulated on QEMU
- Network simulation in Python (NetworkX) and ns-3

---

## Repo Structure

```
HAVEN/
├── firmware/          # Bare-metal C for ARM Cortex-M (QEMU target: lm3s6965evb)
│   ├── src/           # C source files
│   ├── include/       # Header files
│   ├── build/         # CMake build output (gitignored)
│   └── CMakeLists.txt
├── sim/               # Python simulation
│   ├── turboblom.py   # TurboBlom reference implementation
│   ├── network_sim.py # NetworkX topology simulation
│   ├── tests/         # Test vectors and pytest suites
│   └── .venv/         # Python virtual environment (gitignored)
├── docs/              # Protocol design documents
└── README.md
```

---

## Environment Setup

Tested on **Ubuntu 22.04 / 24.04**. Run these once.

### Clone and Submodule Initialization

* **For a fresh clone**:
  ```bash
  git clone https://github.com/devlup-labs/HAVEN
  cd HAVEN
  git submodule update --init --recursive
  ```

* **For an existing clone** (if you have already cloned the repository):
  ```bash
  git pull origin main
  git submodule update --init --recursive
  ```

### System Dependencies

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y \
  gcc-arm-none-eabi \
  binutils-arm-none-eabi \
  gdb-multiarch \
  qemu-system-arm \
  cmake \
  make \
  python3 \
  python3-pip \
  python3-venv \
  git
```

### Verify Installation

```bash
arm-none-eabi-gcc --version   # should print ARM GCC version
qemu-system-arm --version     # should print QEMU version
cmake --version
python3 --version
```

### Python Environment

```bash
cd sim/
python3 -m venv .venv
source .venv/bin/activate
pip install networkx pytest
```

Activate the venv every time you work on simulation code:
```bash
source sim/.venv/bin/activate
```

### Verify ARM Cross-Compilation Works

```bash
echo 'int main(){while(1);}' > /tmp/test.c
arm-none-eabi-gcc -mcpu=cortex-m3 -mthumb -nostdlib -o /tmp/test.elf /tmp/test.c
file /tmp/test.elf
# Expected output: ELF 32-bit LSB executable, ARM
rm /tmp/test.c /tmp/test.elf
```

### Verify QEMU ARM Works

```bash
qemu-system-arm -M lm3s6965evb -nographic -kernel /dev/null 2>&1 | head -5
# Should print QEMU output, not "command not found"
```

> **QEMU machine target**: Always use `-M lm3s6965evb` (Cortex-M3, LM3S6965 microcontroller). Do not use STM32 machine targets — QEMU's STM32 peripheral emulation is incomplete.

---

## Building the Firmware

```bash
cd firmware/
cmake -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
```

Running on QEMU:
```bash
qemu-system-arm \
  -M lm3s6965evb \
  -kernel build/haven.elf \
  -nographic \
  -semihosting
```

To exit QEMU: `Ctrl+A` then `X`.

---

## Running the Simulation

```bash
source sim/.venv/bin/activate
python3 sim/turboblom.py        # TurboBlom reference + self-test
python3 sim/network_sim.py      # NetworkX topology simulation
pytest sim/tests/               # Full test suite
```

## Protocol Overview

HAVEN is structured in four layers:

```
Layer 3 — Authenticated Max-Consensus Election
Layer 2 — Node Authentication (3-way HELLO)
Layer 1 — Key Derivation (TurboBlom + per-node election keys)
Layer 0 — Deployment Provisioning (trusted environment, done once)
```

Each layer only receives input from the layer below it. The election protocol has no knowledge of cryptographic details — it trusts that anything reaching it is from a legitimate, authenticated node.

Full protocol specification: see `docs/DESIGN.md` (to be added).

---

## Key Parameters

| Parameter | Value | Justification |
|-----------|-------|---------------|
| TurboBlom total spaces (m) | 50 | Zhao 2019 connectivity/resilience trade-off |
| Spaces per node (k) | 5 | ~56% pairwise connectivity probability |
| Polynomial threshold (λ) | 3 | <1% link compromise at 10% node capture |
| MAC primitive | HMAC-SHA256 | 1–5 µs on Cortex-M4; ASCON-MAC for tighter targets |
| MAC output | 16 bytes | Sufficient security margin, fits 802.15.4 frame |
| Max message size | 46 bytes (CLAIM) | Single 802.15.4 frame (127-byte max payload) |

---

## Threat Model (Short Version)

The adversary can: eavesdrop, inject, replay, drop messages, MITM wireless links, introduce fake nodes.

Nodes are crash-fault only — they stop, they do not act maliciously. Cryptography does not fail.

The core architectural insight: authenticate at the perimeter (Layer 2), so the election layer (Layer 3) only ever sees messages from legitimate nodes. Inside the perimeter, the problem reduces to crash-fault-tolerant max-consensus — much simpler than Byzantine.

---

## Known Limitations

- **Selective dropping**: An adversary dropping CLAIM messages from the highest-priority candidate can force a suboptimal outcome. Retransmit-with-jitter mitigates but does not eliminate this. Full mitigation requires Byzantine fault tolerance at the network layer — out of scope.
- **K_master physical compromise**: Advanced side-channel extraction of K_master breaks priority forgery resistance. RDP Level 2 makes this infeasible under standard threat models. Threshold sharing of K_master is documented as future work.
- **No formal security proof**: Security arguments are informal reductions to known secure primitives. UC or game-based formal proof does not exist for this specific combination.

---

## References

- Karlof & Wagner — Secure Routing in Wireless Sensor Networks (2003)
- Perrig et al. — SPINS: Security Protocols for Sensor Networks (2002)
- Zhao, Yağan, Gligor — Connectivity in Random Key Graphs With Unreliable Links (2019)
- Blin & Tixeuil — Compact Self-Stabilizing Leader Election for Arbitrary Graphs (2020)
- NIST SP 800-108 — Key Derivation Using Pseudorandom Functions
- mbedTLS Documentation — https://mbed-tls.readthedocs.io

---

## Contributing

Each contributor works in a branch named `mvp/<task>` (e.g. `mvp/turboblom-python`, `mvp/qemu-bringup`). Open a PR when your deliverable is complete. Do not merge without a review.

Do not commit: build artifacts, `.elf` files, `.venv/`, or any key material (even test keys).
