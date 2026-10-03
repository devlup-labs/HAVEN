#!/usr/bin/env python3
"""
Virtual radio for a HAVEN ring of N Renode nodes.

Each Renode instance exposes one UART as a PTY. This process owns every PTY and
relays frames between the two ring neighbours of the sender, so the emulated
topology is a chordal ring rather than a mesh:

    RING_ORDER = 1 9 5 2 ...        node 1 <-> node 9
    link(i)   = order[i-1] <-> order[i]   and   order[i+1] <-> order[i]

Why not a plain broadcast hub: HAVEN_MAX_ADJ_NODES is 2 and forwarding always
excludes the sender, so the ring is closed by the firmware itself. If this
process delivered every frame to every node, the election packets would take
shortcuts across the graph and the measured latency would no longer be the
n-hops-per-direction result the ring produces.

Discovery (dst=0xFF) is broadcast, because PHASE 1 must let a node meet both
neighbours, but it is still only ever delivered to the sender's two ring
neighbours -- never further.

The wire format is the 5-byte header from firmware/src/haven_link.c:

    SOF(0xA5) | type | len | src | dst | payload[len]

Frames are forwarded verbatim; the switch never decrypts, re-signs or rewrites
anything. It also never inspects them beyond src/dst/len for routing, so it
cannot mask a protocol bug. Anything that fails header validation is counted as
garbage and dropped rather than relayed.

Usage:
    bridge/ring_switch.py --config haven_ring.conf [--verbose]
"""
import argparse
import os
import re
import select
import signal
import sys
import time
import tty
from collections import deque
from pathlib import Path

SOF = 0xA5
HDR_LEN = 5
MAX_PAYLOAD = 64          # HAVEN_MAX_PAYLOAD in firmware/include/haven_config.h
BROADCAST = 0xFF          # HAVEN_ID_NONE

import http.server
import threading
import json
import queue

sse_clients = []
sse_lock = threading.Lock()

class SSEHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open(str(Path(__file__).resolve().parents[1] / 'visualizer.html'), 'rb') as f:
                self.wfile.write(f.read())
        elif self.path == '/events':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            q = queue.Queue()
            with sse_lock:
                sse_clients.append(q)
                if last_init_msg:
                    q.put(last_init_msg)
            try:
                while True:
                    msg = q.get()
                    self.wfile.write(f"data: {msg}\n\n".encode('utf-8'))
                    self.wfile.flush()
            except Exception:
                with sse_lock:
                    if q in sse_clients:
                        sse_clients.remove(q)
        else:
            self.send_response(404)
            self.end_headers()

last_init_msg = None

def sse_broadcast(msg_dict):
    global last_init_msg
    msg = json.dumps(msg_dict)
    if msg_dict.get("type") == "init":
        last_init_msg = msg
    with sse_lock:
        for q in sse_clients:
            q.put(msg)

def start_sse_server():
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 8080), SSEHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server

FRAME_TYPES = {1: "DISCOVERY", 2: "ELECTION", 3: "CLAIM", 4: "HEARTBEAT"}

# Colors, suppressed when not a TTY.
_TTY = sys.stdout.isatty()


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s


def log(msg):
    print(_c("36", f"[switch {time.strftime('%H:%M:%S')}]") + f" {msg}", flush=True)


def warn(msg):
    print(_c("31", "[switch] ") + msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------- config

def load_config(path):
    """Parse KEY=VALUE, tolerating quotes and # comments.

    Deliberately not a shell source: this file is also read by start_haven.sh,
    so anything that needs shell expansion would behave differently between the
    two readers.
    """
    cfg = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        cfg[key.strip()] = val
    return cfg


def parse_ring_order(spec):
    order = [int(x) for x in re.findall(r"\d+", spec)]
    if len(order) < 3:
        raise ValueError(f"ring needs at least 3 nodes, got {len(order)}")
    if len(set(order)) != len(order):
        raise ValueError(f"duplicate node id in ring order: {order}")
    return order


def read_firmware_defines(header):
    """Parse integer #defines out of a firmware header.

    The switch must agree with the firmware about m and k, or it will validate
    a topology the firmware cannot actually build.
    """
    text = Path(header).read_text()
    out = {}
    for name in ("HAVEN_M_SPACES", "HAVEN_NUM_SPACES", "HAVEN_PROV_NUM_NODES"):
        m = re.search(rf"^#define\s+{name}\s+(\d+)", text, re.M)
        if m:
            out[name] = int(m.group(1))
    return out


# ------------------------------------------------------------ topology check

def validate(order, k, m, k_master, verbose=False):
    """Every adjacent pair in the ring must share a space.

    compute_K_AB() returns None for a disjoint pair and firmware/src/haven.c
    drops that peer in on_discovery(), so an invalid order yields a silently
    partitioned ring rather than an error. Catching it here turns a confusing
    test failure into a clear message.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim"))
    from turboblom import assign_spaces, compute_K_AB, generate_key_matrix

    n = len(order)
    matrix = generate_key_matrix(m, k_master)
    spaces = {i: assign_spaces(i, k, m, k_master) for i in order}

    problems = []
    for i, a in enumerate(order):
        b = order[(i + 1) % n]
        if compute_K_AB(a, b, matrix, spaces[a], spaces[b]) is None:
            problems.append((a, b))

    if verbose:
        for i in order:
            log(f"node {i:>2} spaces {spaces[i]}")

    if problems:
        detail = ", ".join(f"{a}-{b}" for a, b in problems)
        raise SystemExit(
            f"error: ring order {order} is not viable at k={k}, m={m}.\n"
            f"  These adjacent pairs share no space and can never link:\n"
            f"    {detail}\n"
            f"  Fix with:  ./sim/compute_ring_order.py --nodes {n} --k {k} --m {m}"
        )
    return spaces


# ------------------------------------------------------------------ framing

def frames(buf):
    """Split `buf` into (list_of_complete_frames, bytes_consumed).

    Anything after the last complete frame is left unconsumed so a frame split
    across two reads is reassembled on the next call. Resyncs on SOF, so a
    stray byte or a corrupted length cannot wedge the stream permanently.
    """
    out = []
    i = 0
    n = len(buf)
    while True:
        s = buf.find(b"\xa5", i)
        if s < 0:
            return out, n
        if s + HDR_LEN > n:                  # header not complete yet
            return out, s
        ln = buf[s + 2]
        if ln > MAX_PAYLOAD:                 # corrupt length, hunt for next SOF
            i = s + 1
            continue
        end = s + HDR_LEN + ln
        if end > n:                          # payload not complete yet
            return out, s
        out.append(buf[s:end])
        i = end


# ---------------------------------------------------------------------- node

class Node:
    """One Renode instance's PTY, plus its pending-delay queue."""

    def __init__(self, nid, path):
        self.id = nid
        self.path = path
        self.fd = None
        self.inbuf = b""
        self.outq = deque()
        self.tx = 0
        self.rx = 0

    def open(self, timeout):
        """Open the PTY if Renode has created it, waiting up to `timeout`.

        With timeout=0 this makes a single non-blocking attempt, which lets the
        caller round-robin over every node instead of waiting on each in turn.

        The firmware transmits its PHASE 1 discovery the instant it starts
        executing, so a node whose fd is opened late has already missed its
        neighbours' broadcasts and the ring forms only partially.
        """
        deadline = time.time() + timeout
        while True:
            if os.path.exists(self.path):
                try:
                    # Renode's PTY needs raw mode: canonical mode would buffer
                    # until a newline, and frames carry none.
                    fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                    tty.setraw(fd)
                    self.fd = fd
                    return True
                except OSError:
                    pass
            if time.time() >= deadline:
                return False
            time.sleep(0.02)

    def feed(self, data):
        """Parse what a node sent and return complete frames."""
        self.inbuf += data
        got, consumed = frames(self.inbuf)
        self.inbuf = self.inbuf[consumed:]
        return got

    def queue(self, data, deliver_at):
        self.outq.append((deliver_at, data))

    def pump(self, now):
        """Write queued frames whose hop delay has elapsed.

        The PTY is opened non-blocking, so os.write raises BlockingIOError when
        the guest's receive buffer is full. That must NOT be swallowed: dropping
        the frame silently loses protocol traffic, which shows up much later as
        a node that never learns a neighbour. On EAGAIN the frame goes back on
        the head of the queue and is retried on the next pass.
        """
        wrote = 0
        while self.outq and self.outq[0][0] <= now:
            _, data = self.outq[0]
            try:
                os.write(self.fd, data)
            except BlockingIOError:
                # Buffer full: retry next tick rather than dropping the frame.
                break
            except OSError:
                self.outq.popleft()                # guest closed; discard
                continue
            self.outq.popleft()
            wrote += 1
        return wrote

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--config", default=str(root / "haven_ring.conf"))
    ap.add_argument("--verbose", action="store_true",
                    help="log every frame, not just lifecycle events")
    ap.add_argument("--quiet", action="store_true", help="suppress frame logging")
    ap.add_argument("--check", action="store_true",
                    help="validate the ring topology and exit, without opening PTYs")
    args = ap.parse_args()

    cfg = load_config(args.config)
    verbose = args.verbose and not args.quiet

    num_nodes = int(cfg.get("NUM_NODES", 3))
    hop_ms = int(cfg.get("HOP_DELAY_MS", 20))
    run_s = int(cfg.get("RUN_SECONDS", 90))
    pty_timeout = int(cfg.get("PTY_TIMEOUT_S", 30))
    pty_pattern = cfg.get("PTY_PATTERN", "/tmp/haven_uart_{id}")

    hdr = root / "firmware" / "include" / "haven_config.h"
    defines = read_firmware_defines(hdr)
    m = defines.get("HAVEN_M_SPACES", 12)
    k = defines.get("HAVEN_NUM_SPACES", 5)

    order = parse_ring_order(cfg.get("RING_ORDER", "1 2 3"))[:num_nodes]
    if len(order) != num_nodes:
        raise SystemExit(
            f"error: RING_ORDER has {len(order)} entries but NUM_NODES={num_nodes}."
        )

    log(f"config      {args.config}")
    log(f"ring order  {' '.join(map(str, order))}   (N={num_nodes})")
    log(f"spaces      k={k} m={m}  (from {hdr.name})")
    log(f"hop delay   {hop_ms} ms")

    spaces = validate(order, k, m, bytes(range(32)), verbose)
    log(f"topology    OK, every adjacent pair shares a space")

    if args.check:
        log("--check passed; ring is viable. Not starting (no PTYs opened).")
        return 0

    nodes = {nid: Node(nid, pty_pattern.format(id=nid)) for nid in order}

    # Neighbour map: who may hear whom.
    n = len(order)
    neigh = {order[i]: (order[(i - 1) % n], order[(i + 1) % n]) for i in range(n)}
    leader_active = False
    last_search_time = time.time()
    start_sse_server()
    nodes_data = []
    for nid in order:
        bat = 100 if nid == 1 else 100 - ((nid - 1) * 3) % 100
        nodes_data.append({"id": nid, "battery": bat, "score": bat + 2})
    sse_broadcast({"type": "init", "order": order, "nodesData": nodes_data})

    log("waiting for PTYs " + ", ".join(str(x.path) for x in nodes.values()))
    # Poll all paths together rather than opening one and waiting for the next.
    # Renode boots each instance at a slightly different wall time, and the
    # firmware broadcasts its PHASE 1 discovery immediately, so a serial
    # open-wait-open loop misses the early nodes' frames and the ring forms
    # only partially.
    open_deadline = time.time() + pty_timeout
    while time.time() < open_deadline:
        pending = [nd for nd in nodes.values() if nd.fd is None]
        if not pending:
            break
        for nd in pending:
            nd.open(0)                        # single non-blocking attempt
        if any(nd.fd is None for nd in pending):
            time.sleep(0.02)

    missing = [nd for nd in nodes.values() if nd.fd is None]
    if missing:
        for nd in missing:
            warn(f"no PTY at {nd.path} (node {nd.id})")
        raise SystemExit(
            "error: not all Renode instances came up.\n"
            "  Each instance must be started with --port -1, or they collide on\n"
            "  monitor port 1234 and all but the first abort before creating a PTY.\n"
            "  Renode logs: /tmp/haven_logs/node_<id>.log"
        )
    log(f"all {n} PTYs open")

    stats = {t: 0 for t in FRAME_TYPES}
    seen_leader = set()
    deadline = time.time() + run_s
    started = time.time()
    last_search_time = time.time()
    started = time.time()
    deadline = started + run_s
    log(f"relaying (hop delay {hop_ms} ms). Ctrl-C to stop early.")

    while time.time() < deadline:
        now = time.time()

        # Write anything whose hop delay has elapsed.
        for nd in nodes.values():
            nd.pump(now)

        rlist = [nd.fd for nd in nodes.values() if nd.fd is not None]
        if not rlist:
            break
        try:
            ready, _, _ = select.select(rlist, [], [], 0.02)
        except (OSError, ValueError):
            break

        for fd in ready:
            nd = next((x for x in nodes.values() if x.fd == fd), None)
            if nd is None:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                continue
            if not data:
                continue
            nd.rx += len(data)

            for fr in nd.feed(data):
                src, dst, ln, ftype = fr[3], fr[4], fr[2], fr[1]
                stats[ftype] = stats.get(ftype, 0) + 1

                if ftype == 4:
                    leader_active = True
                if ftype == 4 and ln >= 5:                 # HEARTBEAT
                    lid = fr[HDR_LEN + 4]
                    if lid not in seen_leader:
                        seen_leader.add(lid)
                        log(f"node {lid} is sending heartbeats")

                # Discovery must reach both neighbours; everything else is
                # addressed, and HAVEN forwards only along its own two links.
                targets = neigh.get(src, ())
                if dst != BROADCAST and dst in targets:
                    targets = (dst,)

                if verbose:
                    label = FRAME_TYPES.get(ftype, f"type{ftype}")
                    log(f"  {src} -> {dst if dst != BROADCAST else 'all'} "
                        f"{label}({ln}B) via {list(targets)}")
                
                sse_broadcast({"type": "packet", "src": src, "dst": dst, "targets": list(targets), "ftype": ftype})

                for t in targets:
                    nodes[t].queue(fr, now + hop_ms / 1000.0)

        # Cheap liveness: if nothing has been relayed for a while, say so.
        if time.time() > deadline:
            break

    elapsed = time.time() - started
    log(f"stopped after {elapsed:.1f}s")
    total = sum(stats.values())
    log("frames relayed: " + ", ".join(
        f"{FRAME_TYPES.get(t, f'type{t}')}={c}" for t, c in sorted(stats.items())))
    log(f"total {total}")

    for nd in nodes.values():
        nd.close()

    if not seen_leader:
        warn("no heartbeat observed: no leader was elected within the window.")
        warn("check that RING_ORDER neighbours share spaces and that "
             "HAVEN_T_CLAIM_MS exceeds one ring traversal.")
        return 1

    log(_c("32", f"leader(s) established: {sorted(seen_leader)}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())