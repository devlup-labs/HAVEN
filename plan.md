# HAVEN -> ns-3 Co-Simulation: Implementation Plan

**Status:** design agreed, not yet implemented.
**Audience:** the engineer continuing this project.
**Current state:** the N-node ring works entirely in Renode. This plan moves the
*network* into ns-3 so packet loss, delay and bandwidth become modelable, while
Renode keeps simulating the *nodes*.

---

## Table of contents

1. [What works today (do not break this)](#1-what-works-today-do-not-break-this)
2. [The architecture change](#2-the-architecture-change)
3. [Critical correction: ns-3 has no ZMQ module](#3-critical-correction-ns-3-has-no-zmq-module)
4. [Firmware changes required](#4-firmware-changes-required)
5. [Topology file (the single source of truth)](#5-topology-file-the-single-source-of-truth)
6. [The bridge process](#6-the-bridge-process)
7. [ns-3 side: what to build](#7-ns-3-side-what-to-build)
8. [Launcher changes](#8-launcher-changes)
9. [How to run and test](#9-how-to-run-and-test)
10. [Work breakdown with acceptance criteria](#10-work-breakdown-with-acceptance-criteria)
11. [Risks, unknowns and gotchas](#11-risks-unknowns-and-gotchas)
12. [Appendix: protocol mechanics you need to know](#12-appendix-protocol-mechanics-you-need-to-know)

---

## 1. What works today (do not break this)

This is the verified baseline. Everything in this plan is additive; the
existing ring must keep passing these numbers.

### Currently working

| Thing | Where | Verified result |
|---|---|---|
| Firmware build | `firmware/build.sh` | 0 warnings; `text=21348 data=2120 bss=364` |
| Unit tests | `sim/tests/` | **127 passed** |
| N=3 ring in Renode | `./start_haven.sh` | leader = node 1; `DISCOVERY=3 ELECTION=12 CLAIM=8 HEARTBEAT=38` |
| N=5 ring in Renode | `./start_haven.sh` | leader = node 1; `DISCOVERY=5 ELECTION=50 CLAIM=6 HEARTBEAT=22` |

### The current data path

```
Renode node (firmware)
   -> UART
   -> /tmp/haven_uart_<id>          (PTY, a character device, one per node)
   -> bridge/ring_switch.py         (Python: reassembles frames, relays to the
                                     sender's TWO ring neighbours only)
   -> /tmp/haven_uart_<id'>
   -> Renode node
```

`bridge/ring_switch.py` currently does three jobs:
1. **Reassembles** the byte stream into frames (SOF `0xA5`, 5-byte header).
2. **Enforces the ring topology** (relay only to 2 neighbours).
3. **Simulates delay** via `HOP_DELAY_MS` and heartbeat/leader detection.

### Three things to know before you change anything

**(a) These are PTYs, not ports.** `CreateUartPtyTerminal` in Renode creates a
Unix character device (`/dev/pts/N`) exposed as the symlink
`/tmp/haven_uart_<id>`. It is NOT a TCP/UDP socket. There is no `bind()` or
`listen()` anywhere in `ring_switch.py` or `start_haven.sh`. This is why ns-3
cannot simply "connect to" them today, and why the bridge is required.

**(b) `--port -1` is mandatory.** Every Renode instance defaults to telnet
monitor port 1234. Without `--port -1`, all but the first instance die with
"Address already in use" *before creating their PTY*, so the ring forms
partially and silently. This is set in `haven_ring.conf` via `RENODE_FLAGS`.
Do not remove it.

**(c) The firmware clock runs at ~0.56x real time.** `firmware/src/haven_time.c`
polls the SysTick COUNTFLAG flag and misses roughly every other tick. Measured:
`ms=0x2B6` after ~2s wall, `ms=0xB74` after ~6s wall. Consequence: the nominal
5s discovery window really takes ~9s wall, and reaching a leader takes ~27s
wall. **All ns-3 time budgets must be derived from this 0.56x factor**, or your
sim will "time out" when the protocol is actually fine. See
[the formula in section 9](#9-how-to-run-and-test).

---

## 2. The architecture change

### Goal

One **topology file** is the single source of truth. Both ns-3 (which builds the
network) and the Renode side (which builds the nodes) read it. Nothing about the
topology is hardcoded in either simulator. Random topologies are generated from
it.

### Target data path

```
Renode node (firmware)  --unchanged-->
   UART
   -> /tmp/haven_uart_<id>
   -> bridge/uart_bridge.py      (Python: reuse framing from ring_switch.py;
                                  ZMQ <-> PTY, no topology knowledge)
   == ZMQ socket (local, e.g. ipc:///tmp/haven_zmq.sock) ==
   -> ns-3 simulation             (OWNS the network: loss, delay, bandwidth,
                                  decides who hears what)
   == ZMQ ==
   -> bridge/uart_bridge.py
   -> /tmp/haven_uart_<dst>
   -> destination Renode node
```

### Key insight that makes this easier than expected

**The protocol is already flood-based, not ring-circulation-based.** Verified by
reading `firmware/src/haven.c` and by replicating the exact algorithm against
random graphs:

- Every node floods its own election frame to **all** of its neighbours.
- `fwd_mask[HAVEN_MAX_ADJ_NODES][32]` (one 32-byte bitmask per neighbour
  direction) tracks which `(origin, incoming-neighbour)` pairs have already been
  forwarded, which bounds the flood without a spanning tree.
- Therefore a node with degree d needs to store d neighbours, and **no ring
  restructuring is needed for general graphs**.

Consequence: `ring_switch.py`'s "relay to exactly 2 neighbours" logic is
**deleted, not ported**. ns-3 takes over delivery entirely.

### Proposed file layout

```
topology.json                  <- NEW. single source of truth.
sim/
  gen_topology.py              <- NEW. random graph generator -> topology.json
  turbolom.py                  <- EXISTING. authoritative space/key reference
  compute_ring_order.py        <- EXISTING. keep for ring-only experiments
  tests/
    test_provision.py          <- EXISTING. extend for N > 10
    test_topology.py           <- NEW. generator/validator unit tests
    ...                         <- EXISTING 127 tests
bridge/
  uart_bridge.py               <- NEW. ZMQ <-> PTY. (ring_switch.py becomes a
                                  thin compat shim or is deleted)
  ring_switch.py               <- EXISTING. harvest framing, then retire.
ns3/
  CMakeLists.txt               <- NEW
  haven_csim.cc                <- NEW. main ns-3 scenario + ZMQ transport
  build_topology.py            <- NEW. topology.json -> ns-3 objects
firmware/
  include/haven_config.h       <- EDIT. MAX_ADJ_NODES, ECHO_THRESHOLD
  include/provision.h          <- EDIT. NUM_NODES > 10
  src/provision.c              <- EDIT. battery table to 20
  src/haven.c                  <- probably unchanged (flood already general)
renode/
  haven.repl, haven.resc       <- EXISTING, unchanged
start_haven.sh                 <- EDIT. add ns-3 + bridge to launch
haven_ring.conf                <- EDIT. topology path instead of RING_ORDER
```

---

## 3. Critical correction: ns-3 has no ZMQ module

**The earlier discussion assumed ns-3 ships a native ZMQ co-simulation module.
It does not.** Verified directly against the upstream mirror
(`nsnam/ns-3-dev-git`):

- `contrib/` contains only a `.gitignore` — no zmq contrib module.
- `src/` has **no zmq module**. The nearest neighbours are `fd-net-device`,
  `tap-bridge`, and `bridge`.
- `examples/` contains no zmq example.

So ZMQ must be added by you. You have three options:

### Option A: TAP / veth (`src/tap-bridge`) -- BLOCKED for the reference user

ns-3 creates a TAP interface; a bridge shuttles frames between the TAP and each
node's PTY. This is the "official" ns-3 external interface.

**Blocked.** Creating `/dev/net/tun` interfaces requires `CAP_NET_ADMIN`. The
reference environment runs as `uid=1000` with `CapEff=0` (no capabilities).
`/dev/net/tun` exists but `TUNSETIFF` will fail. Would need root or a
capabilities grant. Not recommended unless the environment is changed.

### Option B: Write a thin ns-3 module that links libzmq -- RECOMMENDED

ns-3 is a normal set of C++ libraries; link any C dependency you like.

```bash
sudo apt install libzmq3-dev      # the C/C++ ZMQ library
```

Then write `ns3/haven_csim.cc` that:
- creates N ns-3 nodes,
- attaches a point-to-point channel between them per the topology,
- installs a ZMQ socket per emulated node,
- relays `ns3::Packet` <-> ZMQ message.

The Python bridge already can use ZMQ (`pyzmq 27.1.0` is installed), so **only
the ns-3 side needs the C library.** This path needs no privileges, which makes
it the right choice. Cost: you write the transport yourself (~200-400 lines).

### Option C: NIST ns3-cosim -- wrong tool here

<https://github.com/usnistgov/ns3-cosim>. Uses a **TCP/IP socket gateway, not
ZMQ**, and is pinned to a V2X fork (`ns-3-dev-v2x-v1.1`), not stock ns-3. Heavier
than this project needs. Listed for completeness.

### Recommendation

**Option B.** Preserve ZMQ as the transport (you already chose it, and
`pyzmq` is present on the Python side), but implement the ns-3 half yourself
against `libzmq3-dev`. This is a known-workable amount of work and avoids both
the root requirement of A and the fork dependency of C.

> **Open decision for you:** ns-3's native `tap-bridge` is more "standard" but
> needs privileges. Option B keeps your ZMQ choice and needs none. Confirm with
> the project owner that Option B is acceptable before committing to it.

---

## 4. Firmware changes required

These are the **only mandatory firmware edits**. Everything else in the firmware
should already generalise.

### 4.1 `HAVEN_MAX_ADJ_NODES`: 2 -> N  (MANDATORY)

`firmware/include/haven_config.h:31`:

```c
#define HAVEN_MAX_ADJ_NODES   2      // <-- ring-only. Must become >= max degree.
```

`firmware/src/haven.c:131` in `on_discovery`:

```c
nbr_t *n = nb_find(peer);
if (!n) { if (nb_n >= HAVEN_MAX_ADJ_NODES) return; n = &nb[nb_n++]; ... }
```

On a random graph with average degree 6, a node meets ~6 peers but **only the
first 2 are kept. The rest are silently discarded** -- no error, no log, no
reply. This is the single change that separates "random graphs work" from
"random graphs silently half-broken".

**Set it to the maximum degree allowed by your generator, plus headroom.**
Suggested: drive it from a new CMake option so it is set per-experiment rather
than hand-edited.

Memory check (already verified, this is **not** a capacity problem):

```
nbr_t          = 33 bytes  (uint8 id + key[32])
RAM available  = 65536 bytes   (renode/haven.repl: size 0x00010000)
current bss    = 364 bytes

  N  deg  nb[]   fwd_mask  total
 20    4    132       128    260
 20    8    264       256    520
 20   19    627       608   1235
 50    5    165       160    325
```

Even a fully-connected N=20 costs 1235 bytes. No RAM pressure. `fwd_mask`
auto-sizes from the same macro.

### 4.2 `HAVEN_ECHO_THRESHOLD`: semantics change on general graphs (DECIDE)

`firmware/include/haven_config.h:34`:

```c
#define HAVEN_ECHO_THRESHOLD  2
```

Used in `on_election` (`haven.c:161-165`): a node starts its claim timer once it
has seen `ECHO_THRESHOLD` echoes of its **own** election frame.

- **On a ring:** exactly 2 echoes return, one per direction. `2` is exactly right.
- **On a general graph:** echo count scales with degree. Measured on a random
  N=12 graph, degree ~5: echo counts ranged **2 to 8**.

Measured convergence (simulation of the exact firmware algorithm, 25 trials):

| N | avg deg | all nodes reach 2 echoes |
|---|---|---|
| 10 | 3-8 | 100% |
| 12 | 3 | 96% |
| 12 | 4+ | 100% |
| 20 | 3 | 84% |
| 20 | 4+ | **100%** |

Options:

- **(a) Leave at 2.** Works, zero risk. But on a dense graph the threshold
  becomes near-vacuous -- it no longer proves "my packet traversed the network".
- **(b) Raise it** toward `degree/2`. Preserves meaning; risks a node *never*
  starting its claim timer if the graph is sparse or lossy. Needs per-experiment
  tuning.
- **(c) Make it a build option** like `NODE_ID`. Most flexible. **Recommended.**

**Start with (a)** to get the pipeline working end-to-end, then move to (c).

### 4.3 Battery table: 10 -> 20 nodes  (MANDATORY for N > 10)

`firmware/include/provision.h:12`:

```c
#define HAVEN_PROV_NUM_NODES 10
```

`firmware/src/provision.c:60-70`:

```c
int provision_battery(uint8_t node_id) {
    if (node_id == 0 || node_id > HAVEN_PROV_NUM_NODES) return -1;
    return (int)provision_battery_table()[node_id - 1];
}
const uint8_t *provision_battery_table(void) {
    static const uint8_t table[HAVEN_PROV_NUM_NODES] =
        { 100, 80, 60, 40, 20, 90, 70, 50, 30, 10 };   /* only 10 entries */
    return table;
}
```

Node 11 returns `-1`, so it cannot win. To run N > 10 you must:

1. Bump `HAVEN_PROV_NUM_NODES` to at least your N.
2. Extend the table to match, keeping **node 1 highest** so leader identity
   stays deterministic (tests depend on this).

Suggested continuation mirroring the existing shape -- but **confirm with the
project owner**, do not assume:

```c
{ 100, 80, 60, 40, 20, 90, 70, 50, 30, 10,
   95, 75, 55, 35, 15, 85, 65, 45, 25,  5 };
```

3. Move the table into `topology.json` if you want per-experiment battery.
   Cleaner long term; the firmware can be compiled with `-DHAVEN_BATTERY_TABLE=...`
   generated from JSON by the launcher.

### 4.4 What does NOT need changing

- `haven.c` election/flood logic -- already general (verified above).
- `haven_link.c` frame format -- unchanged.
- `compute_K_AB` / space provisioning -- unchanged; works for any degree.
- The PTY/UART layer -- unchanged.

---

## 5. Topology file (the single source of truth)

### Design

One JSON file, read by the generator, the ns-3 builder, and the launcher.

```json
{
  "version": 1,
  "meta": {
    "num_nodes": 12,
    "seed": 20250103,
    "m_spaces": 12,
    "k_spaces": 5,
    "echo_threshold": 2,
    "max_adj_nodes": 12,
    "generator": "Erdos-Renyi",
    "target_avg_degree": 5
  },
  "nodes": [
    { "id": 1, "battery": 100, "spaces": [0,1,2,3,4], "x": 120.5, "y": 44.1 },
    { "id": 2, "battery":  95, "spaces": [3,4,7,9,11], "x": 310.0, "y": 90.2 }
  ],
  "links": [
    { "a": 1, "b": 2,  "loss_pct": 0.0, "delay_ms": 20,  "bw_bps": 9600 },
    { "a": 1, "b": 8,  "loss_pct": 12.5,"delay_ms": 45,  "bw_bps": 9600 }
  ]
}
```

- `nodes[].spaces` must match `sim/turboblom.py::assign_spaces` exactly -- the
  C and Python implementations already have a passing parity test
  (`test_provision.py`). **Generate via the Python reference, never by hand.**
- `links[]` is the adjacency list; each entry is a **bidirectional** link.
- `nodes[].x/y` are optional, for spatial/proximity topologies and for
  ns-3 mobility if you later want it.
- `meta.seed` makes runs reproducible. Log it with every result.

### Random graph generator: `sim/gen_topology.py`

Requirements:

1. **Filter links by shared space.** Two nodes can only be adjacent if they
   share >= 1 space -- otherwise `compute_K_AB` fails in firmware and the link is
   dead on arrival. At m=12, k=5, N=20: **188/190 pairs (98.9%) are linkable**,
   so this filter discards almost nothing.

   *(Open question for the owner: filter the generator, or allow all links and
   let the protocol reject infeasible ones? Filtering gives cleaner experiments;
   allowing all tests the rejection path. Recommend **filter**.)*

2. **Guarantee connectivity.** One connected component is required for a single
   leader. Measured (Erds-Renyi, 30 trials):

   | N | avg deg 2 | 3 | 4 | 6 | 10 |
   |---|---|---|---|---|---|
   | 10 | 97% | 100% | 100% | 100% | 100% |
   | 20 | 80% | 100% | 100% | 100% | 100% |

   **Enforce avg degree >= 4 and verify connectivity explicitly**, rejecting and
   regenerating if needed. Do not rely on luck.

3. **Respect `max_adj_nodes`.** Reject any graph whose max degree exceeds
   `meta.max_adj_nodes`, so the firmware can hold every neighbour.

4. **Deterministic given `--seed`.**

Suggested CLI:

```bash
python3 sim/gen_topology.py --nodes 12 --m 12 --k 5 --avg-degree 5 \
    --seed 20250103 --loss-pct 0 --delay-ms 20 --out topology.json
```

---

## 6. The bridge process

### Purpose

Translate between **PTY character devices** and **ZMQ sockets**. It must hold no
topology knowledge and no timing logic -- both belong to ns-3 now.

### Reuse from `ring_switch.py`

This is the valuable part. Port these directly (they are hard-won and
regression-tested):

- **PTY open in raw mode**: `os.open(path, O_RDWR | O_NOCTTY | O_NONBLOCK)` then
  `tty.setraw(fd)`. Canonical mode would buffer until a newline, and frames
  contain none.
- **Concurrent PTY discovery**: poll *all* paths in one loop. Do NOT open them
  one at a time. This was a real bug: Renode boots instances staggered, firmware
  broadcasts discovery immediately, and serial open-wait-open dropped early
  nodes' frames. Symptom: N=5 relayed only 2/5 discoveries. Fixed by
  round-robining with `open(0)` per node.
- **Frame reassembly (`feed`)**: SOF `0xA5`, 5-byte header
  (`type, len, src, dst`), then `len` payload bytes. Must tolerate partial
  reads and resynchronise on garbage.
  *Off-by-one bug already fixed and covered by tests: check `s + HDR_LEN > n`
  before reading the length byte, or you get an `IndexError` on the first
  partial read.*
- **EAGAIN handling in `pump()`**: the PTY is non-blocking, so `os.write` raises
  `BlockingIOError` when the guest buffer is full. **This must NOT be swallowed.**
  Returning the frame to the head of the queue and retrying next tick is correct;
  `except OSError: pass` silently drops protocol traffic and presents much later
  as a node that never learns a neighbour.
- **Heartbeat/leader detection**: reuse the logic that prints
  `leader(s) established: [...]` so you can compare ns-3 runs against the Renode
  baseline.

### What to delete

- `RING_ORDER` parsing and `neigh` adjacency construction.
- The "relay to 2 neighbours" target computation.
- `HOP_DELAY_MS` (ns-3 owns delay now).
- The `--check` topology validator (moves to `gen_topology.py` / a ns-3-side
  validator).

### ZMQ socket pattern

Use one socket pair, not N sockets -- simpler and matches ns-3's single-threaded
event loop:

- ns-3 binds a REP or ROUTER socket; the bridge connects a DEALER.
- Frame envelope on the wire: `[u32 src_id][u32 dst_id][u16 len][payload]`.
  `dst_id = 0xFF` for broadcast. This mirrors `haven_link.h`'s `frame_t`.
- **Backpressure**: apply the same non-blocking discipline as `pump()`. ZMQ
  high-water marks will otherwise hide drops. Set `SNDHWM`/`RCVHWM` explicitly.
- **Do not** let the bridge reorder or coalesce frames; ns-3 applies the timing.

---

## 7. ns-3 side: what to build

### Scenario construction

1. Read `topology.json`.
2. Create one `ns3::Node` per entry in `nodes[]`.
3. For each entry in `links[]`, install a **point-to-point channel** between the
   two corresponding nodes with per-link attributes taken from the JSON:
   - `loss_pct` -> `PointToPointNetDevice` + `RateErrorModel`
     (`ns3::UniformRandomVariable` with `SetBound(0,1)`, drop when `< loss`).
   - `delay_ms` -> channel `SetPropagationDelay(MilliSeconds(x))`.
   - `bw_bps` -> channel `SetDataRate(bps)`.
4. Attach an application/socket per node that:
   - **sends** anything the bridge pushes toward the network, addressed to
     `dst_id` (or broadcast);
   - **receives** packets ns-3 delivers and pushes them back to the bridge for
     that node's PTY.
5. Stop at a configurable simulated-time horizon (see section 9 for how to pick
   it).

### ZMQ transport inside ns-3

Link `libzmq` directly. Sketch of the integration point:

```cpp
// ns3/haven_csim.cc
#include <zmq.h>                 // libzmq3-dev
#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/internet-module.h"

// One application per emulated node. On receive-from-ZMQ, wrap into an
// ns3::Packet and Send() it; on ns3 receive, encode and push to ZMQ.
class ZmqNodeApp : public ns3::Application { ... };
```

Key constraints:

- ns-3's event loop is single-threaded and **non-blocking**. Never block in a ZMQ
  call inside a callback. Poll the ZMQ socket from a scheduled event, or use
  ZMQ's edge-triggered integration carefully.
- Respect the **0.56x firmware clock** when converting between ns-3 simulated
  time and the firmware's `time_ms()`. See section 9.
- Decide explicitly whether the ns-3 clock or the firmware's clock is
  authoritative. Recommendation: **ns-3 owns simulated time**; the firmware's
  timers are emulated durations, so ns-3's `delay_ms` values should be the
  *real* intended delays, and you simply need to let the simulation run long
  enough in ns-3 time to cover the firmware's own timer sequence.

### What ns-3 buys you

Once working, per-link `loss_pct` / `delay_ms` / `bw_bps` from `topology.json`
become first-class knobs. That is the entire point of this phase: real-world
channel conditions, per-link, without touching firmware.

---

## 8. Launcher changes

`start_haven.sh` currently: build N ELFs -> generate N `.resc` -> launch N Renode
-> run `ring_switch.py`.

New order:

```
1. read topology.json (replaces RING_ORDER)
2. run gen_topology.py if topology.json is absent (or --regenerate)
3. validate topology: shared-space feasibility + connectivity + max degree
4. build N ELFs, one per node in topology.json  (-DNODE_ID=<id>)
5. export battery/space tables from topology.json if firmware reads them
6. launch ns-3 simulation                 (Option B: no ZMQ port collisions)
7. launch bridge/uart_bridge.py          (waits for ZMQ + all PTYs)
8. launch N headless Renode instances    (--port -1, --disable-xwt, --hide-log)
9. wait; on exit, kill all children and remove /tmp/haven_uart_* and the ipc socket
```

Config changes in `haven_ring.conf`:

- Replace `RING_ORDER="..."` with `TOPOLOGY=topology.json`.
- Keep `NUM_NODES` **derived from** the topology file, not set independently.
  Two sources of truth for N is exactly the bug we are eliminating.
- Keep `RENODE_FLAGS` with `--port -1` (mandatory, see 1b).
- `RUN_SECONDS` needs the 0.56x factor (section 9).

Also: `sim/compute_ring_order.py` still defaults to `--m 50`, which is stale --
the firmware is at `m=12`. Fix its default or make it read
`firmware/include/haven_config.h`.

---

## 9. How to run and test

### A. Today's ring (works now -- run this first as a baseline)

```bash
cd /home/kuppa/HAVEN/HAVEN

# unit tests -> expect 127 passed
python3 -m pytest sim/tests/ -q -p no:cacheprovider

# clean firmware build -> expect 0 warnings, dec 23832
cd firmware && rm -rf build && ./build.sh && cd ..

# N=3 ring (default in haven_ring.conf)
./start_haven.sh

# N=5 ring
sed -i 's/^NUM_NODES=.*/NUM_NODES=5/' haven_ring.conf
./start_haven.sh
```

**Expected:** `leader(s) established: [1]` from node 1, plus a frame tally.
`--verbose` logs every relayed frame.

**Read the failure mode carefully.** If you see
`no heartbeat observed: no leader was elected within the window`, that is
almost always a **timeout, not a protocol fault**. See below.

### The 0.56x clock rule -- do not skip this

Measured on the reference machine:

| elapsed wall time | firmware `ms` register |
|---|---|
| ~2 s | `0x2B6` = 694 |
| ~6 s | `0xB74` = 2932 |

Rate ~= **0.56x**. So:

```
wall_seconds  ~=  (HAVEN_T_CLAIM_MS + 2 * HAVEN_T_WINDOW_MS) / 0.56  +  boot(~10s)
             ~=  (5000 + 2*5000) / 0.56  +  10
             ~=  48 seconds
```

`RUN_SECONDS=90` has margin. Anything under 30 fails. When setting the ns-3
horizon, apply the same factor.

### B. After co-simulation is implemented

```bash
# 1. generate a topology (deterministic given the seed)
python3 sim/gen_topology.py --nodes 12 --m 12 --k 5 --avg-degree 5 \
    --seed 20250103 --out topology.json

# 2. sanity-check it standalone
python3 sim/tests/test_topology.py -q
python3 sim/compute_ring_order.py --nodes 12 --m 12 --k 5   # if you still
                                                          # want a ring view

# 3. build ns-3 (once)
cd ns-3-dev
./ns3 configure --enable-examples --enable-tests
./ns3 build
./ns3 run hello-simulator        # smoke test
cd ..

# 4. run the co-simulation
./start_haven.sh --topology topology.json
```

Add loss to exercise the interesting behaviour:

```bash
python3 sim/gen_topology.py --nodes 12 --avg-degree 5 --loss-pct 15 \
    --delay-ms 40 --seed 7 --out topology-lossy.json
./start_haven.sh --topology topology-lossy.json
```

### Validation order -- do these in sequence

1. **Lossless, no delay, ring topology, N=3.** Must reproduce today's numbers
   (`DISCOVERY=3 ELECTION=12 CLAIM=8 HEARTBEAT=38`). If this differs, your
   bridge or transport is dropping/reordering frames. Fix before proceeding.
2. **Same at N=5** (`DISCOVERY=5 ELECTION=50 CLAIM=6 HEARTBEAT=22`).
3. **Random graph, lossless, N=10, avg-degree 5.** Single leader expected.
4. **Add 10-20% loss.** Expect *slower* convergence, not necessarily failure.
   Record the loss at which election starts failing -- that is a real research
   result.
5. **Sweep N = 5, 10, 15, 20.** Multiple seeds each. Report the failure
   distribution, not a single number.

### Regression guards

- Keep all **127 existing tests** passing. The ring tests still apply to the
  bridge's framing code.
- Add `sim/tests/test_topology.py`: generator produces connected graphs,
  respects `max_adj_nodes`, links only space-sharing pairs, is deterministic
  for a fixed seed.
- Add a byte-exact framing test: a frame out of `uart_bridge` must equal the
  bytes that `ring_switch.py` would have relayed.

---

## 10. Work breakdown with acceptance criteria

Each step is independently verifiable. Do them in order.

| # | Task | Files | Done when |
|---|---|---|---|
| 1 | Fix `compute_ring_order.py` stale `m=50` default | `sim/compute_ring_order.py` | `--help` shows default 12 |
| 2 | Decide `ECHO_THRESHOLD` policy; add as CMake option | `haven_config.h`, `CMakeLists.txt` | `-DHAVEN_ECHO_THRESHOLD=N` works |
| 3 | Battery table 10 -> 20; `HAVEN_PROV_NUM_NODES` | `provision.h`, `provision.c` | `test_provision.py` covers ids 11-20 |
| 4 | `MAX_ADJ_NODES` as CMake option, default >= N | `haven_config.h`, `CMakeLists.txt` | N=20 deg=8 build fits RAM |
| 5 | `gen_topology.py` + `test_topology.py` | `sim/` | connected, space-filtered, deterministic |
| 6 | Extract framing into `bridge/uart_bridge.py`; ZMQ transport | `bridge/` | byte-exact vs `ring_switch.py` |
| 7 | Stand up ns-3 (Option B) + hello-world ZMQ | `ns3/`, `ns3-dev/` | packet crosses ZMQ once |
| 8 | ns-3 scenario from `topology.json` w/ error models | `ns3/haven_csim.cc` | loss/delay visibly applied |
| 9 | Rewire `start_haven.sh` to 3-process launch | `start_haven.sh`, `haven_ring.conf` | N=3 matches baseline numbers |
| 10 | Validation sweep + writeup | new | steps 1-5 in section 9 pass |

---

## 11. Risks, unknowns and gotchas

**Root / capabilities.** uid=1000, `CapEff=0`. No TAP. If anyone proposes
Option A, it needs a privilege change. Also blocks `--enable-python-bindings`? No,
but it does block TAP creation.

**Disk.** `/` is **95% full, ~4.7 GB free**. Building ns-3 typically needs
2-4 GB. Free space first. `df -h /`. Do not delete anything without asking.

**ns-3 has no ZMQ module.** Section 3. Budget for writing the transport.

**ns-3 version.** `apt install ns3` gives **3.35 (2019)** -- no CMake workflow,
no modern contrib, no ZMQ path. Build from `ns-3-dev` instead.

**`pybind11` is not installed.** Only needed for ns-3 Python bindings. If you
write the ns-3 side in C++ (recommended) you do not need it.

**Silent frame loss is the main risk.** Three separate bugs in this project were
all "a frame vanished and nothing said so": the parser `IndexError`, the `EAGAIN`
swallow, and the serial PTY-open race. In the new design you have *two* transports
(PTY and ZMQ) each able to drop silently. **Instrument every stage**: byte
counters in, frames out, per node, printed at shutdown. Compare against the
`ring_switch.py` tally (`DISCOVERY=n ELECTION=n ...`) -- if the numbers do not
match, you dropped something.

**Boot skew.** Renode instances boot ~2.1-2.4 s apart and start transmitting
immediately. At N=20 with sequential builds this could stretch. The concurrent
PTY-open fix in `ring_switch.py` mitigates it; keep it.

**Node IDs are `uint8_t`.** Hard ceiling of 255. Fine to 20, worth stating.

**`fwd_mask` is never reset.** A second election in the same run would be
suppressed. Fine for one-shot experiments; fatal for re-election tests. Document
if you move to repeated elections.

**One-shot discovery.** Late joiners stay isolated forever. Expected; do not
"fix" it silently -- it is out of scope of the basic pseudocode.

**Disconnected components elect one leader each.** The generator must guarantee
connectivity (see section 5).

**`sim/network_sim.py` is legacy and broken.** It uses a Blom lambda+1 = 4 model
predating the current shared-`K_master` protocol; its percentages are invalid.
`networkx` and `numpy` are both missing system-wide. Leave it alone or delete it;
do not treat it as ground truth.

---

## 12. Appendix: protocol mechanics you need to know

Read `firmware/src/haven.c` alongside this. Phase numbers refer to
`Pseudeocode_basic.md`.

### Frame format (`firmware/include/haven_link.h`)

```c
typedef struct {
    uint8_t  type, len, src, dst;
    uint8_t  payload[HAVEN_MAX_PAYLOAD];
} frame_t;                 // 5-byte header + payload
```

Frame types: `T_DISCOVERY=1, T_ELECTION, T_CLAIM, T_HEARTBEAT`.
`dst = HAVEN_ID_NONE (0xFF)` means broadcast.
On the wire, preceded by SOF `0xA5` and reassembled by the bridge.

### Phases (as implemented)

1. **Discovery** (`tx_discovery`) -- broadcast id + spaces + timestamp + HMAC.
   `on_discovery` replies **1-to-1** (never floods) and stores the peer's
   `K_AB` in `nb[]`. This is why the earlier worry about "a node needing to know
   every node" is unfounded: each node only ever stores its direct neighbours.
2. **Election** (`tx_election` / `on_election`) -- flood to all neighbours.
   `fwd_mask[HAVEN_MAX_ADJ_NODES][32]` bounds the flood, keyed on the PAIR
   (neighbour, origin). **This is what makes the protocol graph-native.**
3. **Claim** (`tx_claim` / `on_claim`) -- highest score wins; ties by higher id.
4. **Heartbeat** (`tx_heartbeat` / `on_heartbeat`) -- leader announces each
   `HAVEN_EPOCH_MS`; receivers yield by clearing `claim_on/window_on/vote_on`.

### Election latency, empirically

For a ring of size `n`, the latency formula is:

```
latency  =  n  +  t_claim  +  t_window  -  1      (in firmware-ms)
```

Verified in the Python model for n = 3..50, with exactly two echoes (one per
direction) and a single leader elected.

### Why `fwd_mask` exists (deliberate deviation)

The literal strictly-better forwarding rule in the pseudocode is **wrong on any
cycle**. The two directional copies of an election packet meet head-on at the
antipodal node; the strictly-better test drops the second copy as a duplicate,
so **both copies die mid-network, no echo returns, `ECHO_THRESHOLD` is never
met, and no leader is ever elected.** Keying forwarding memory on
`(origin, incoming neighbour)` lets each copy complete its traversal, giving
exactly one echo per direction.

This is a **documented, intentional deviation** from the pseudocode. It is noted
as such in `progress_report.md` section 9. Get owner sign-off before presenting
results as pseudocode-conformant.

### Key constants (`firmware/include/haven_config.h`)

| Macro | Value | Note |
|---|---|---|
| `HAVEN_NUM_SPACES` (k) | 5 | spaces per node |
| `HAVEN_M_SPACES` (m) | 12 | **changed 50 -> 12**; see below |
| `HAVEN_MAX_ADJ_NODES` | 2 | **must become N for graphs** |
| `HAVEN_ECHO_THRESHOLD` | 2 | meaning changes on graphs |
| `HAVEN_T_CLAIM_MS` | 5000 | |
| `HAVEN_T_WINDOW_MS` | 5000 | |
| `HAVEN_EPOCH_MS` | 1000 | |

### Why m=12 and not 50

At m=50, k=5, **5 of 10 id-adjacent pairs share no space** and can never link,
so an id-ordered ring is impossible. At m=12, k=5, all provisioned pairs link.

Measured probability that all N ring links are valid:

| N | m=12 | m=20 | m=50 |
|---|---|---|---|
| 10 | 0.764 | 0.116 | ~0.000 |
| 20 | **0.584** | 0.013 | ~0.000 |
| 30 | 0.447 | 0.002 | ~0.000 |

Raising `m` makes it *worse*: with k fixed, `P(disjoint) = C(m-k,k)/C(m,k)`
climbs from 0.027 at m=12 to 0.577 at m=50. **Keep m=12.** At m=12, k=5, a full
20-node Hamiltonian cycle exists and is simply `1 -> 2 -> ... -> 20`
(min degree 18, all 20 edges valid, min shared spaces on the cycle = 1).

---

## Quick reference: run commands

```bash
# tests
python3 -m pytest sim/tests/ -q -p no:cacheprovider          # 127 passed

# firmware
cd firmware && rm -rf build && ./build.sh

# single-node QEMU (optional; needs qemu-system-arm)
cd firmware && ./build.sh -r

# current N-node ring
./start_haven.sh
./start_haven.sh --verbose
./start_haven.sh --config my.conf

# topology check only (no Renode launched)
python3 bridge/ring_switch.py --config haven_ring.conf --check

# regenerate a valid ring order for a given m/k
python3 sim/compute_ring_order.py --nodes 12 --m 12 --k 5
```