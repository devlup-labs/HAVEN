# HAVEN: Complete Master Technical Reference Manual
**Hardened Authenticated Voter Election Network (Hostile-Aware Verifiable Election Network)**

---

## Table of Contents

1. [Executive Summary & Core Mission](#1-executive-summary--core-mission)
2. [Threat Model & System Assumptions](#2-threat-model--system-assumptions)
3. [The Four-Layer Architectural Model](#3-the-four-layer-architectural-model)
4. [Cryptographic Architecture (TurboBlom & Dual-Key Model)](#4-cryptographic-architecture-turboblom--dual-key-model)
5. [The HAVEN Consensus Protocol (Phases 1 to 14)](#5-the-haven-consensus-protocol-phases-1-to-14)
6. [Packet Wire Formats & Data Layouts](#6-packet-wire-formats--data-layouts)
7. [Embedded Firmware Architecture (Bare-Metal ARM Cortex-M)](#7-embedded-firmware-architecture-bare-metal-arm-cortex-m)
8. [Simulation, Emulation & GUI Architecture](#8-simulation-emulation--gui-architecture)
9. [Repository & Codebase Map](#9-repository--codebase-map)
10. [Comprehensive Runbook & Command Reference](#10-comprehensive-runbook--command-reference)
11. [Empirical Insights, Tuning & Documented Deviations](#11-empirical-insights-tuning--documented-deviations)
12. [Known Limitations, Security Gaps & Future Roadmap](#12-known-limitations-security-gaps--future-roadmap)

---

## 1. Executive Summary & Core Mission

### 1.1 What is HAVEN?
**HAVEN** is a research-grade, authenticated distributed **max-consensus leader election protocol** designed specifically for sparse, decentralized, and adversarial **Wireless Sensor Networks (WSNs)** operating in hostile environments (e.g., tactical battlefield zones, disaster response scenarios, unattended industrial monitoring).

### 1.2 The Core Problem
In decentralized embedded networks with no base station, satellite link, or trusted central coordinator:
1. **Public-Key Cryptography is Infeasible**: Traditional key exchange (Diffie-Hellman, RSA, ECC) and digital signature schemes (ECDSA, Ed25519) require excessive CPU cycles, large RAM allocations, and several seconds to minutes of computation on low-power microcontrollers (e.g., ARM Cortex-M0/M3/M4). This opens massive Denial-of-Service (DoS) and battery-drain vectors.
2. **Standard Consensus Protocols Fail**:
   - **Paxos / Raft**: Require high network density, heavy state maintenance, and a pre-known static cluster configuration.
   - **Bully Algorithm**: Induces transmission storms ($O(N^2)$ message complexity) and requires dense point-to-point links.
   - **Classic Ring Elections**: Highly brittle; a single severed link halts the entire token/election flow.
   - **Pre-Shared Pairwise Keys**: Storing $N(N-1)/2$ keys exhausts embedded Flash/SRAM on scaling networks.

### 1.3 The HAVEN Solution
HAVEN achieves authenticated, tamper-resistant leader election using **symmetric cryptography exclusively** (HMAC-SHA256 and combinatorial key pre-distribution) with minimal Flash/RAM footprint.

### 1.4 The Core Architectural Axiom: "Authenticate at the Perimeter"
By enforcing cryptographic verification on every incoming physical link at the network perimeter, any message reaching the election state machine is guaranteed to originate from a legitimate, provisioned node over an authenticated link. As a result:
- The consensus problem simplifies from **Byzantine Fault Tolerance (BFT)** down to **Crash-Fault-Tolerant (CFT) Max-Consensus**.
- Nodes can crash or drop out, but malicious packet injection, score forgery, and identity spoofing are discarded at the link layer before influencing election state.

---

## 2. Threat Model & System Assumptions

### 2.1 Adversarial Capabilities (Active Threat Model)
The adversary has complete control over the wireless RF medium and can:
- **Eavesdrop** on all transmissions across all RF channels.
- **Inject** arbitrary raw frames with fabricated headers, scores, or keys.
- **Replay** previously recorded valid frames at arbitrary future times.
- **Drop / Jam** packets selectively or indiscriminately.
- **Man-in-the-Middle (MITM)** wireless links between adjacent nodes.
- **Insert Fake Nodes** that attempt to participate in the election.
- **Physically Capture Nodes** and extract all key material stored in non-secure memory.

### 2.2 System & Node Assumptions
- **Crash-Fault Only (Non-Byzantine)**: Provisioned nodes that have not been physically compromised execute the firmware faithfully. They may crash, exhaust their battery, reboot, or lose connectivity, but they do not intentionally fabricate false sensor readings or lie about their scores.
- **Trusted Offline Deployment**: Initial provisioning (node IDs, master secret, and initial cryptographic domain assignments) occurs in a secure environment prior to field distribution.
- **Hardware Limitations**: Target nodes are typical 32-bit microcontrollers (e.g., ARM Cortex-M3 @ 16 MHz, 64 KB SRAM, 256 KB Flash).

---

## 3. The Four-Layer Architectural Model

HAVEN is structured as a strict 4-layer stack. Each layer only accepts input from the layer beneath it, completely decoupling cryptographic verification from election state logic.

```
┌────────────────────────────────────────────────────────┐
│  Layer 3: Authenticated Max-Consensus Election        │
│  - Candidate draw, Priority pruning, Echo counting     │
│  - Claim window, Objection handling, Heartbeats        │
├────────────────────────────────────────────────────────┤
│  Layer 2: Node Authentication & Link Framing          │
│  - 3-way HELLO handshake, Session TTL, Neighbor Table  │
│  - Frame codec (SOF 0xA5, 5-byte header, CRC/HMAC)     │
├────────────────────────────────────────────────────────┤
│  Layer 1: Key Derivation (TurboBlom KDF)              │
│  - Pairwise key K_AB computation via shared spaces     │
│  - HMAC-SHA256 primitives, Master integrity tags       │
├────────────────────────────────────────────────────────┤
│  Layer 0: Deployment Provisioning (Offline Trusted)    │
│  - Node ID, Master Key (K_master), Space subsets, Batt │
└────────────────────────────────────────────────────────┘
```

1. **Layer 0 (Provisioning)**: Establishes base identity and cryptographic seeds before deployment.
2. **Layer 1 (Key Derivation)**: Generates symmetric keys on demand via TurboBlom without exchanging secret keys over the air.
3. **Layer 2 (Authentication & Framing)**: Converts physical UART/RF byte streams into authenticated datagrams and manages neighbor connection states.
4. **Layer 3 (Consensus Election)**: Solves leader convergence using authenticated scores without needing to know any cryptographic primitives.

---

## 4. Cryptographic Architecture (TurboBlom & Dual-Key Model)

### 4.1 Evolution of TurboBlom in HAVEN
1. **Classic Blom (1984)**: Uses finite-field algebra ($A = (D \cdot G)^T$). Guarantees 100% connectivity and optimal $\lambda$-resilience against node capture. **Drawback**: Requires heavy finite-field polynomial multiplications, which are sluggish on Cortex-M0/M3 microcontrollers.
2. **Academic TurboBlom (Khabbazian et al., 2024)**: Replaces general field multiplication with additions/shifts by restricting the generator matrix $G$ to binary $\{0, 1\}$ or powers of 2.
3. **HAVEN TurboBlom Implementation**: A compute-bound, combinatorial Key Derivation Function (KDF) using HMAC-SHA256 and bitwise XOR accumulation. It reduces matrix storage requirements in RAM/Flash to zero.

### 4.2 Mathematical Key Derivation Mechanics
Every node is provisioned with:
- **$K_{master}$**: Global 32-byte deployment secret.
- **Space Subset $S_i$**: A set of $k$ unique integers drawn from a total pool of $m$ cryptographic domains ("spaces"): $S_i \subset \{0, 1, \dots, m-1\}, |S_i| = k$.

#### Step-by-Step Pairwise Key Derivation ($K_{AB}$)
When Node $A$ and Node $B$ meet:
1. **Space Intersection**: Nodes exchange their public space lists and determine overlapping indices:
   $$S_{shared} = S_A \cap S_B$$
   If $S_{shared} = \emptyset$, the two nodes share no common cryptographic subspace and **cannot establish a direct secure link**.
2. **Row Generation**: For each shared index $s \in S_{shared}$, a 32-byte pseudo-random row is computed deterministically:
   $$\text{msg} = \text{"row"} \parallel \text{uint16\_be}(s)$$
   $$\text{row}_s = \text{HMAC-SHA256}(K_{master}, \text{msg})$$
3. **XOR Accumulation**: An accumulator buffer of 32 zero-bytes is updated across all shared spaces:
   $$\text{XOR\_sum} = \bigoplus_{s \in S_{shared}} \text{row}_s$$
4. **Symmetric ID Mixing**: To ensure both nodes arrive at the exact same key without coordination, node IDs are sorted:
   $$id_{low} = \min(A, B), \quad id_{high} = \max(A, B)$$
   $$\text{preimage} = \text{XOR\_sum} \parallel \text{uint32\_be}(id_{low}) \parallel \text{uint32\_be}(id_{high})$$
5. **Final Key Extraction**:
   $$K_{AB} = \text{SHA256}(\text{preimage})[0..15]$$
   The first 16 bytes of the digest form the bidirectional pairwise link key $K_{AB} = K_{BA}$.

### 4.3 The Dual-Key Security Tier
To isolate payload integrity from network packet routing, HAVEN frames use two distinct keys simultaneously:

| Key | Scope | Size | Authentication Target |
|:---|:---|:---|:---|
| **$K_{master}$** | Global Network Secret | 32 Bytes | **Content Integrity**: Protects candidate scores, candidate origins, claim announcements, and leader heartbeat counters. An intermediate forwarding node cannot alter a score or forge a claim without knowing $K_{master}$. |
| **$K_{AB}$** | Pairwise Link Secret | 16 Bytes | **Link Attribution & Hop Freshness**: Authenticates the physical transmitter (`replayer_id`) and hop timestamp. Defends against replay, wormhole, and packet injection attacks on a specific link. |

### 4.4 Parameter Tuning: Space Pool ($m$) vs Subsets ($k$)
The probability that two random nodes share at least one space is:
$$P(\text{link}) = 1 - \frac{\binom{m-k}{k}}{\binom{m}{k}}$$

- **Initial Specification ($m=50, k=5$)**:  
  $P(\text{disjoint}) = \frac{\binom{45}{5}}{\binom{50}{5}} \approx 0.577 \implies P(\text{link}) \approx 42.3\%$.  
  *Fatal Result*: More than half of adjacent node pairs cannot link. Forming an ordered ring or reliable mesh is mathematically impossible without high node density.
- **HAVEN Production Parameter ($m=12, k=5$)**:  
  $P(\text{disjoint}) = \frac{\binom{7}{5}}{\binom{12}{5}} = \frac{21}{792} \approx 0.0265 \implies P(\text{link}) \approx 97.35\%$.  
  In the provisioned 20-node deployment, 100% of adjacent ring pairs successfully link.

---

## 5. The HAVEN Consensus Protocol (Phases 1 to 14)

The election lifecycle is modeled as a deterministic state machine:

```
[BOOT] ──► M_DISCOVERY ──► M_PASSTHROUGH ──► (Yield / Relay / Lock Vote)
                 │
                 └──► M_ELECTION ──► M_CLAIMING ──► M_LEADER
```

### Detailed Phase Mechanics

#### Phase 1: Neighbor Discovery & Key Derivation
1. At boot, node $A$ broadcasts a `T_DISCOVERY` frame:
   $$\{ \text{node\_id}: A, \; \text{spaces}: S_A, \; \text{time}: now(), \; \text{hash}: \text{HMAC}(K_{master}, A \parallel S_A \parallel time)[0..7] \}$$
2. The node listens for a randomized duration $t_{disc} \in [5.0, 6.0]$ seconds to prevent synchronized RF collision storms.
3. For each received packet:
   - Check freshness: $|time - now()| \le \text{REPLAY\_WINDOW\_S}$ (10s).
   - Verify discovery hash with $K_{master}$.
   - Intersect spaces: $S_{shared} = S_A \cap S_B$. If non-empty, compute $K_{AB}$ via TurboBlom.
   - Insert neighbor into `neighbour_table` with `auth_status = AUTHENTICATED`, `countdown_timer = SESSION_TTL`.

#### Phase 2: Fitness Score Computation & Mode Decision
1. Compute internal score (integer arithmetic for frame packing):
   $$\text{internal\_score} = \text{battery\_pct} + |\text{neighbour\_table}|$$
2. Compute candidacy odds:
   $$\text{odds} = \max\left(1, \frac{L \cdot \frac{\text{battery\_pct}}{100} + M \cdot \frac{|\text{neighbour\_table}|}{\text{MAX\_ADJ}}}{2}\right)$$
   *(where $L=1, M=1$ are system weights).*
3. Sample pseudo-random probability from Linear Congruential Generator (LCG):
   $$\text{PRNG}_{next} = (A \cdot \text{seed} + B) \pmod M$$
   $$\text{prob} = \frac{\text{PRNG}_{next}}{M}$$
4. **Decision**:
   - If $\text{odds} > \text{prob}$: Node transitions to `M_ELECTION` (active candidate).
   - Otherwise: Node transitions to `M_PASSTHROUGH` (relay/voter).

#### Phase 3: Candidacy Flood Announcement
If in `M_ELECTION`:
1. Generate master score tag: $\text{score\_tag} = \text{HMAC}(K_{master}, \text{score} \parallel \text{origin\_id})[0..15]$.
2. Initialize: $\text{best\_score} = \text{internal\_score}$, $\text{best\_origin} = self.id$, $\text{echo\_count} = 0$.
3. Broadcast `T_ELECTION` frame to all authenticated neighbors. Each outbound transmission is tagged with the link-specific replay HMAC:
   $$\text{hmac\_replay} = \text{HMAC}(K_{AB}, \text{score} \parallel \text{origin\_id} \parallel self.id \parallel now())[0..15]$$

#### Phase 4: Election Packet Reception & Propagation
Upon receiving a `T_ELECTION` packet:
1. Verify timestamp freshness ($\le 10$s) and verify `hmac_replay` using neighbor's $K_{AB}$.
2. Verify `score_tag` using $K_{master}$.
3. **If `origin_id == self.id` (Candidate Echo)**:
   - Own candidate packet has traversed the network/ring and returned.
   - Increment `echo_count++`.
   - If `echo_count >= HAVEN_ECHO_THRESHOLD` (typically 2) and `T_claim` not yet running:
     - Start $T_{claim}$ timer (5000 ms).
   - Drop packet (terminate loop circulation).
4. **If strictly better candidate**:
   $$(\text{score} > \text{best\_score}) \lor (\text{score} == \text{best\_score} \land \text{origin\_id} > \text{best\_origin})$$
   - Adopt new leader candidate: $\text{best\_score} = \text{score}$, $\text{best\_origin} = \text{origin\_id}$.
   - Reset echo tracker: $\text{echo\_count} = 0$, cancel $T_{claim}$.
   - Transition `M_ELECTION -> M_PASSTHROUGH` (yield to stronger node).
5. **Cycle Forwarding Protection (`fwd_mask`)**:
   - Forwarding check: lookup `fwd_mask[neighbour_slot][origin_id]`. If already forwarded from this incoming neighbor direction, drop packet. Otherwise, mark bit and retransmit to all neighbors except sender.

#### Phase 5: Claim Safety Timeout
- When $T_{claim}$ expires:
  - If $\text{best\_origin} \neq self.id$: Node yielded to a higher score; revert to `M_PASSTHROUGH`.
  - If $\text{best\_origin} == self.id$: Node proved global dominance; initiate Phase 6.

#### Phase 6: Claimant Broadcast
1. Candidate creates a `T_CLAIM` frame:
   $$\{ \text{origin}: self.id, \; \text{score}: \text{internal\_score}, \; \text{score\_tag}, \; time, \; \text{claim\_tag}: \text{HMAC}(K_{master}, self.id \parallel time)[0..15] \}$$
2. Broadcast to all neighbors.
3. Start objection window timer: $T_{window} = 5000\text{ ms}$.
4. Transition state to `M_CLAIMING`.

#### Phase 7: Claim Reception, Vote Locking & Objections
When any node receives a `T_CLAIM` frame:
1. Verify freshness and cryptographic tags ($K_{master}$).
2. **Objection Trigger**: If the local node holds a higher score than the claimant ($\text{internal\_score} > \text{claim.score}$ or $\text{best\_score} > \text{claim.score}$ with a different origin):
   - Transmit `T_OBJECTION` frame backward toward claimant containing the superior score.
3. **Vote Locking**: If claimant is legitimate and unchallenged:
   - Lock local vote: set `vote_origin = claim.origin`, start local vote deadline timer ($T_{window}$).
   - Forward `T_CLAIM` onward to all other neighbors.

#### Phase 8: Consensus Finalization
At the claimant node:
- If an authentic `T_OBJECTION` with a higher score arrives during $T_{window}$:
  - Cancel $T_{window}$.
  - Adopt higher candidate, yield state to `M_PASSTHROUGH`.
- When $T_{window}$ expires with **zero valid objections**:
  - Node officially transitions to `M_LEADER`.
  - Reset `epoch_counter = 0`.
  - Begin periodic Leader Heartbeat loop (Phase 9).

#### Phase 9: Active Leader Heartbeats & Epoch Advancements
1. Leader emits `T_HEARTBEAT` every `HAVEN_EPOCH_MS` (1000 ms):
   $$\{ \text{counter}: \text{epoch\_counter}++, \; \text{leader\_id}: self.id, \; \text{tag}_{counter}, \; \text{tag}_{leader} \}$$
2. **Follower Nodes on Heartbeat**:
   - Verify $K_{master}$ tags and assert $\text{counter} > \text{last\_seen\_counter}$ (strict monotonic advance prevents replay).
   - Set `leader_id = packet.leader_id`, set `mode = M_PASSTHROUGH`.
   - Reset session TTL for the leader.
   - **Crucial Rule**: Unconditionally clear local promotion timers (`claim_on = 0, window_on = 0, vote_on = 0`) to prevent race-condition split-brain leadership.

#### Phase 10: Passthrough Fast-Path
Nodes in `M_PASSTHROUGH` with an active, fresh leader suppress new election storms and answer requests using cached leader information.

#### Phase 11: Dynamic Session Expiry & Re-Authentication
- Background tick decrements neighbor countdown timers.
- When `countdown_timer == 0`: Trigger a 3-way HELLO handshake. If verification fails, purge the neighbor profile and cached $K_{AB}$ from memory.

#### Phase 12: Link Failure & Network Partition Handling
1. If an established link to neighbor $N$ drops:
   - Emit `FIND_LEADER` packet in both directions.
2. If the request circles back from both directions: Loop is closed, topology is intact.
3. If an ACK arrives on one side while the other side times out:
   - **Partition Confirmed**: Clear `leader_id = NULL`.
   - Trigger local re-election within the isolated segment (Phases 2-8).

#### Phase 13: Network Merging & Leader Resignation
When previously partitioned segments reconnect:
1. Border nodes forward `JOIN_REQUEST` frames to the active leader.
2. If `join_request_count > RESIGNATION_THRESHOLD`:
   - Leader issues a signed `T_RESIGNATION` broadcast.
   - All nodes reset state and trigger a global re-election across the newly unified topology.

#### Phase 14: Dynamic Connection Tracking (Ambient Beacons)
- Nodes periodically emit unaddressed, low-overhead `PRESENCE_HEARTBEAT` frames carrying `{node_id, current_leader_id, nonce, HMAC(K_node)}`.
- Receivers verify identity using on-the-fly key derivation: $K_{node} = \text{HMAC}(K_{master}, node\_id)$.
- Nodes advertising the same leader can be dynamically admitted into spare neighbor slots without restarting an election.

---

## 6. Packet Wire Formats & Data Layouts

HAVEN frames utilize a compact binary framing structure optimized for resource-constrained 802.15.4 / UART radios. Maximum payload length is strictly capped at 64 bytes.

### 6.1 Link-Layer Wire Framing (`haven_link.h`)
Every packet on the wire begins with a 5-byte header:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   SOF (0xA5)  |   Frame Type  |  Payload Len  |   Source ID   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| Destination ID|             Payload Data (0..64 Bytes) ...    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```
- **SOF (`0xA5`)**: 1 Byte Start-of-Frame delimiter for stream synchronization.
- **Type**: 1 Byte message identifier (`0x01` DISC, `0x02` ELEC, `0x03` CLAIM, `0x04` HB).
- **Len**: 1 Byte payload length in bytes.
- **Src / Dst**: 1 Byte node IDs (`0xFF` = `HAVEN_ID_NONE` / Broadcast).

---

### 6.2 Detailed Frame Payload Specifications

#### Frame 1: `T_DISCOVERY` (Payload: 18 Bytes)
Used during Phase 1 for neighbor advertisement and TurboBlom space sharing.

| Field Offset | Field Name | Size | Type | Description |
|:---|:---|:---|:---|:---|
| `+0` | `node_id` | 1 Byte | `uint8_t` | Sender node ID |
| `+1` | `spaces` | 5 Bytes | `uint8_t[5]` | List of $k=5$ TurboBlom space indices |
| `+6` | `timestamp` | 4 Bytes | `uint32_t_be`| Unix seconds timestamp |
| `+10` | `discovery_hash` | 8 Bytes | `uint8_t[8]` | $\text{HMAC}(K_{master}, node\_id \parallel spaces \parallel timestamp)[0..7]$ |

---

#### Frame 2: `T_ELECTION` (Payload: 40 Bytes)
Flooded across the network during Phase 3 & 4 to propagate candidate priority.

| Field Offset | Field Name | Size | Type | Description |
|:---|:---|:---|:---|:---|
| `+0` | `score` | 2 Bytes | `uint16_be` | Candidate composite score |
| `+2` | `origin_id` | 1 Byte | `uint8_t` | ID of candidate node who owns this score |
| `+3` | `score_tag` | 16 Bytes| `uint8_t[16]`| Content integrity: $\text{HMAC}(K_{master}, score \parallel origin\_id)$ |
| `+19` | `replayer_id` | 1 Byte | `uint8_t` | Immediate forwarding node ID |
| `+20` | `timestamp` | 4 Bytes | `uint32_t_be`| Time packet was retransmitted |
| `+24` | `hmac_replay`| 16 Bytes| `uint8_t[16]`| Link attribution: $\text{HMAC}(K_{AB}, score \parallel origin \parallel replayer \parallel time)$ |

---

#### Frame 3: `T_CLAIM` (Payload: 39 Bytes)
Broadcast by the winning candidate to begin the objection window.

| Field Offset | Field Name | Size | Type | Description |
|:---|:---|:---|:---|:---|
| `+0` | `origin_id` | 1 Byte | `uint8_t` | Claimant ID |
| `+1` | `score` | 2 Bytes | `uint16_be` | Claimed score |
| `+3` | `score_tag` | 16 Bytes| `uint8_t[16]`| Master tag verifying score ownership |
| `+19` | `claim_time` | 4 Bytes | `uint32_t_be`| Timestamp claim was emitted |
| `+23` | `claim_tag` | 16 Bytes| `uint8_t[16]`| Freshness: $\text{HMAC}(K_{master}, origin\_id \parallel claim\_time)$ |

---

#### Frame 4: `T_HEARTBEAT` (Payload: 37 Bytes)
Broadcast periodically by the established leader to enforce term freshness.

| Field Offset | Field Name | Size | Type | Description |
|:---|:---|:---|:---|:---|
| `+0` | `epoch_counter`| 4 Bytes | `uint32_t_be`| Monotonically increasing epoch sequence |
| `+4` | `leader_id` | 1 Byte | `uint8_t` | Elected leader ID |
| `+5` | `counter_tag` | 16 Bytes| `uint8_t[16]`| $\text{HMAC}(K_{master}, \text{uint32\_be}(epoch\_counter))$ |
| `+21` | `leader_tag` | 16 Bytes| `uint8_t[16]`| $\text{HMAC}(K_{master}, leader\_id)$ |

---

## 7. Embedded Firmware Architecture (Bare-Metal ARM Cortex-M)

### 7.1 Target Hardware & Memory Layout
- **Microcontroller**: ARM Cortex-M3 (emulated via Renode/QEMU).
- **Core Frequency**: 16 MHz SysTick.
- **Peripherals**: STM32F7 USART peripheral mapped at MMIO address `0x40004400`.
- **Memory Map** (`linker.ld`):
  - **FLASH (256 KB)**: `0x00000000` to `0x00040000` (`.isr_vector`, `.text`, `.rodata`).
  - **SRAM (64 KB)**: `0x20000000` to `0x20010000` (`.data`, `.bss`, Stack top at `0x20010000`).

### 7.2 Boot Sequence & CRT0 (`startup.c`)
Because firmware compiles with `-nostartfiles --specs=nosys.specs`, startup is handled manually:
1. **Vector Table**: Minimal 2-entry table in `.isr_vector` containing initial stack pointer (`_estack`) and `Reset_Handler`.
2. **`Reset_Handler` Execution**:
   - Copies `.data` initializers from Flash (`_sidata`) into SRAM (`_sdata` to `_edata`).
   - Zeroes out the `.bss` section (`_sbss` to `_ebss`).
   - Transfers control to `main()`.

### 7.3 USART as the Wireless Transport Medium
- `uart.c` operates the STM32F7 USART using raw MMIO status registers (`ISR`, `TDR`, `RDR`).
- Non-blocking character polling (`uart_try_getchar`) drives `haven_link.c`.
- **Broadcast Emulation**: When `link_send` transmits a frame with destination `HAVEN_ID_NONE (0xFF)`, the bridge/simulator distributes the bytes to all connected RF neighbors.

### 7.4 Minimal Cryptographic Footprint (mbedTLS)
- Firmware vendors `mbedtls` (v2.28.8) configured via `mbedtls_config.h`.
- Only `MBEDTLS_MD_C` and `MBEDTLS_SHA256_C` are compiled.
- Strips all platform entropy, filesystem calls, and networking stacks.
- Total binary size: **~23 KB Flash**, leaving >230 KB Flash available.

---

## 8. Simulation, Emulation & GUI Architecture

HAVEN integrates a three-tier execution hierarchy:

```
[Web GUI Studio (Port 8080)]  <── WebSocket ──>  [gui/server.py (aiohttp)]
                                                         │
                           ┌─────────────────────────────┴─────────────────────────────┐
                           ▼                                                           ▼
             [Interactive DES Engine]                                  [Hardware Co-Simulation Platform]
             - In-memory Python simulation                             - N Renode Cortex-M3 Node Emulators
             - Instant step / play / chaos                             - ns-3 Physical Wireless Network
             - Live packet flight animations                           - bridge/uart_bridge.py (ZMQ <-> PTY)
```

### 8.1 Dual Simulation Engines
1. **Interactive Discrete-Event Simulator (DES)**:
   - Python-based protocol simulation running inside `gui/server.py`.
   - Allows instant topology rewiring, step-by-step frame execution, and dynamic node crashing/battery drain via web UI.
2. **Full Hardware Co-Simulation (Renode + ns-3)**:
   - **Nodes**: N independent instances of Renode running compiled bare-metal `haven.elf` binaries.
   - **Interconnect**: Each Renode node exposes a character device PTY (`/tmp/haven_uart_<id>`).
   - **Bridge**: `bridge/uart_bridge.py` reads PTY frames and serializes them into ZeroMQ (`ipc:///tmp/haven_zmq.sock`).
   - **Network**: `ns-3` receives frames, models wireless RF propagation delay, 802.15.4 contention, and packet drop rates, and re-delivers frames to target node PTYs.

### 8.2 Topology Management (`topology.json`)
The single source of truth for node positions, battery levels, TurboBlom space allocations, and link graphs. Both Python simulators, Renode scripts, and ns-3 read this file directly.

---

## 9. Repository & Codebase Map

| Path | Primary Language | Description |
|:---|:---|:---|
| `firmware/src/haven.c` | C (Bare-metal) | Core protocol state machine (Phases 1-9), timer loops, dual-tag verifications |
| `firmware/src/turboblom.c` | C (Bare-metal) | TurboBlom key derivation ($K_{AB}$), HMAC-XOR row computation |
| `firmware/src/haven_link.c` | C (Bare-metal) | Frame encoder/decoder, non-blocking SOF `0xA5` packet parser |
| `firmware/src/haven_time.c` | C (Bare-metal) | SysTick polled timer providing `time_ms()` and freshness validation |
| `firmware/src/provision.c` | C (Bare-metal) | Per-node provisioning table (spaces, battery, keys) |
| `firmware/src/uart.c` | C (Bare-metal) | Raw MMIO STM32F7 USART driver |
| `firmware/src/crypto.c` | C (Bare-metal) | Wrapper around mbedTLS HMAC-SHA256 |
| `firmware/include/haven_config.h` | C Header | Global macro tunables ($m=12, k=5, T_{claim}=5000\text{ms}$, etc.) |
| `gui/server.py` | Python (AsyncIO) | Web server, WebSocket telemetry hub, discrete-event protocol engine |
| `gui/public/` | HTML/JS/CSS | Frontend visualizer, Vis.js network graph, real-time node inspector |
| `sim/turboblom.py` | Python 3 | Reference TurboBlom KDF and key symmetry tests |
| `sim/gen_topology.py` | Python 3 | Random graph generator generating valid `topology.json` configurations |
| `bridge/uart_bridge.py` | Python 3 | Bidirectional PTY $\leftrightarrow$ ZeroMQ bridge for ns-3 co-simulation |
| `bridge/ring_switch.py` | Python 3 | Legacy frame-forwarding software switch for ring topologies |
| `renode/haven.repl` | Renode DSL | Hardware platform description (Cortex-M3 + USART + Memory) |
| `renode/haven.resc` | Renode Script | Renode initialization script creating PTY terminals |
| `start_gui.sh` | Bash | Launches Web GUI Visualizer Studio on port 8080/6969 |
| `start_haven.sh` | Bash | Master CLI orchestrator launching Renode, ns-3, and bridge |
| `haven_ring.conf` | Bash Shell Config | Simulation parameter definitions and Renode JVM flags |

---

## 10. Comprehensive Runbook & Command Reference

### 10.1 Interactive Web GUI Studio (Recommended)
```bash
# Start on default port 8080
./start_gui.sh

# Or run on a custom port
./start_gui.sh --port 6969
```
*Open `http://localhost:8080` in any web browser.*

### 10.2 Full System CLI Co-Simulation
```bash
# Ensure execution permissions
chmod +x start_haven.sh

# Run full co-simulation with default configuration
./start_haven.sh

# Useful CLI flags:
./start_haven.sh --verbose                 # Detailed packet logs
./start_haven.sh --topology my_topo.json   # Run with custom topology
./start_haven.sh --run-seconds 60          # Automatically terminate after 60s
./start_haven.sh --stop-on-leader 3        # Terminate when leader emits 3 heartbeats
./start_haven.sh --legacy-switch           # Use Python ring switch instead of ns-3
```

### 10.3 Automated Test Suites
```bash
# Activate Python virtual environment
source .venv/bin/activate

# Execute all unit tests (127+ passing tests)
python3 -m pytest sim/tests/ -q -p no:cacheprovider

# Run TurboBlom cryptographic self-test
python3 sim/turboblom.py
```

### 10.4 Topology Generation & Pre-Flight Checks
```bash
# Generate a new connected 10-node topology
python3 sim/gen_topology.py --nodes 10 --avg-degree 4.5 --out topology.json

# Check space intersection and link feasibility without launching Renode
python3 bridge/ring_switch.py --config haven_ring.conf --check

# Compute valid Hamiltonian cycle ring order for (m, k)
python3 sim/compute_ring_order.py --nodes 10 --m 12 --k 5
```

### 10.5 Bare-Metal Firmware Compilation & Direct Debugging
```bash
# Standard firmware compilation
cd firmware && ./build.sh
cd ..

# Clean rebuild
cd firmware && ./build.sh -c
cd ..

# Inspect active Renode PTY endpoints
ls -l /tmp/haven_uart*

# Direct serial monitor on a specific node (e.g., pts/2)
cat /dev/pts/2
```

---

## 11. Empirical Insights, Tuning & Documented Deviations

### 11.1 The Ring Forwarding Deadlock & `fwd_mask` Solution
- **The Issue**: In a cycle or ring, a candidate packet leaves in both directions (clockwise and counter-clockwise). The two copies meet head-on at the antipodal node. The literal pseudocode rule *"forward only if strictly better"* dropped the second copy as a non-improving duplicate. Consequently, **both directional copies died mid-network**, 0 echoes returned to the origin, $T_{claim}$ never triggered, and no leader could ever be elected.
- **The Solution**: Implementation of `fwd_mask[MAX_ADJ][32]` in `haven.c`. Forwarding memory is keyed on the pair:
  $$(\text{incoming\_neighbour}, \; \text{origin\_id})$$
  This allows both directional traversals to pass each other and complete the full circuit, reliably delivering exactly 2 echoes to the origin.

### 11.2 Mathematical Election Latency Formula
Empirical validation across ring sizes $N \in [3, 50]$ established the exact hop latency:
$$\text{Latency} = N + T_{claim} + T_{window} - 1 \quad (\text{in firmware milliseconds})$$
This proves linear $O(N)$ scalability on rings.

### 11.3 Candidacy Odds Clamp Fix
In `haven.c`, the pseudocode statement `odds = max(1, ...)` was initially coded with `< 1000u`, forcing `odds` to 1000 permille (100%) and making every node unconditionally contend for leadership. Corrected to `odds = (odds < 1u) ? 1u : odds`, restoring proper probabilistic contention based on battery level and connectivity.

### 11.4 Immediate Promotion Cancellation on Heartbeat
Under the basic pseudocode, follower nodes receiving a `T_HEARTBEAT` switched their mode to `M_PASSTHROUGH` but forgot to cancel their local $T_{window}$ timers. When $T_{window}$ expired, followers promoted themselves to `M_LEADER`, creating a split-brain condition with multiple leaders. `haven.c` explicitly resolves this by clearing all promotion timers on heartbeat receipt:
```c
claim_on = 0; window_on = 0; vote_on = 0;
```

### 11.5 SysTick Clock Scaling Factor (~0.56x)
`haven_time.c` reads SysTick `COUNTFLAG` via polling rather than interrupt vectors. High polling loop latency misses roughly every other tick. In Renode simulation:
- Firmware clock runs at **~0.56x real-time**.
- A nominal 5-second $T_{claim}$ translates to **~9 seconds** of real wall-clock time. All ns-3 simulation timeouts are scaled accordingly.

---

## 12. Known Limitations, Security Gaps & Future Roadmap

1. **Global $K_{master}$ Capture Vulnerability**:
   - Because all nodes share the same $K_{master}$ for content integrity, physically extracting Flash from one captured node allows an attacker to forge score tags and claim tags.
   - *Mitigation*: Store $K_{master}$ inside a hardware Secure Enclave or CryptoCell HSM with tamper-zeroization.
2. **One-Shot Discovery Window**:
   - In the current basic implementation, discovery runs once at boot (5-6s). Nodes powering on after this window remain isolated.
   - *Mitigation*: Implement periodic background discovery beacons (Phase 14).
3. **No Byzantine Tolerance**:
   - If an authenticated node is compromised and instructed to transmit arbitrary maximum scores (`0xFFFF`), the network will elect it. HAVEN assumes non-Byzantine crash faults only.
4. **Majority Vote Tallying**:
   - The reference Python simulation (`sim/leaderElections.py`) tallies votes before final confirmation. The bare-metal C implementation currently relies solely on uncontested claim window expiration.
5. **8-Bit Node Addressing Limit**:
   - Frame headers use 1-byte node IDs, capping deployment sizes at 254 active nodes (`0xFF` reserved for broadcast). Expanding to 16-bit IDs will allow scaling to tens of thousands of sensor nodes.
