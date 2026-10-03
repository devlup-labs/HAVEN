#!/usr/bin/env python3
"""
HAVEN UART <-> ZMQ Co-Simulation Bridge.

Connects Renode node PTY character devices (/tmp/haven_uart_<id>) to an ns-3
discrete-event simulation process via ZeroMQ (DEALER <-> ROUTER).

Wire format on ZMQ:
    [u32 src_id][u32 dst_id][u16 len][raw_frame]
    (big-endian 10-byte header followed by raw HAVEN frame)
    dst_id = 0xFF (255) represents broadcast.
"""

import argparse
import json
import os
import re
import select
import signal
import struct
import sys
import time
import tty
from collections import deque
from pathlib import Path

try:
    import zmq
except ImportError:
    sys.exit("error: pyzmq is required for uart_bridge.py (pip install pyzmq)")

SOF = 0xA5
HDR_LEN = 5
MAX_PAYLOAD = 64          # HAVEN_MAX_PAYLOAD
BROADCAST = 0xFF          # HAVEN_ID_NONE
ZMQ_IDENTITY = b"haven_bridge"

FRAME_TYPES = {1: "DISCOVERY", 2: "ELECTION", 3: "CLAIM", 4: "HEARTBEAT"}
_TTY = sys.stdout.isatty()


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s


def log(msg):
    print(_c("36", f"[bridge {time.strftime('%H:%M:%S')}]") + f" {msg}", flush=True)


def warn(msg):
    print(_c("31", "[bridge] ") + msg, file=sys.stderr, flush=True)


def emit_event(ev_file, ev):
    if not ev_file:
        return
    try:
        with open(ev_file, "a") as f:
            f.write(json.dumps(ev) + "\n")
    except Exception:
        pass


# ------------------------------------------------------------------ framing

def frames(buf):
    """Split `buf` into (list_of_complete_frames, bytes_consumed).

    Anything after the last complete frame is left unconsumed so a frame split
    across two reads is reassembled on the next call. Resyncs on SOF.
    """
    out = []
    i = 0
    n = len(buf)
    while True:
        s = buf.find(b"\xa5", i)
        if s < 0:
            return out, n
        if s + HDR_LEN > n:
            return out, s
        ln = buf[s + 2]
        if ln > MAX_PAYLOAD:
            i = s + 1
            continue
        end = s + HDR_LEN + ln
        if end > n:
            return out, s
        out.append(buf[s:end])
        i = end


def pack_envelope(src, dst, raw_frame):
    """Pack frame into a 10-byte big-endian header + payload for ZMQ."""
    return struct.pack(">IIH", src, dst, len(raw_frame)) + raw_frame


def unpack_envelope(data):
    """Unpack 10-byte header from ZMQ message."""
    if len(data) < 10:
        return None, None, None
    src, dst, ln = struct.unpack(">IIH", data[:10])
    raw_frame = data[10:10 + ln]
    return src, dst, raw_frame


# ---------------------------------------------------------------------- node

class Node:
    """One Renode instance's PTY interface with pacing."""

    def __init__(self, nid, path):
        self.id = nid
        self.path = path
        self.fd = None
        self.inbuf = b""
        self.outq = deque()
        self.tx_frames = 0
        self.rx_frames = 0
        self.tx_bytes = 0
        self.rx_bytes = 0
        self.next_tx_time = 0.0

    def open(self, timeout=0):
        """Open PTY in raw non-blocking mode."""
        deadline = time.time() + timeout
        while True:
            if os.path.exists(self.path):
                try:
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
        """Consume data from PTY and return complete frames."""
        self.inbuf += data
        got, consumed = frames(self.inbuf)
        self.inbuf = self.inbuf[consumed:]
        return got

    def queue(self, data, now=None):
        if now is None:
            now = time.time()
        # Enforce minimum inter-frame spacing (25ms) to model UART wire time
        # and prevent RX FIFO overrun in Renode STM32F7 USART emulation.
        deliver_at = max(now, self.next_tx_time)
        self.outq.append((deliver_at, data))
        self.next_tx_time = deliver_at + 0.025

    def pump(self, now=None):
        """Write queued frames to PTY whose delivery time has arrived."""
        if now is None:
            now = time.time()
        wrote = 0
        while self.outq and self.outq[0][0] <= now:
            _, data = self.outq[0]
            try:
                os.write(self.fd, data)
            except BlockingIOError:
                # Buffer full: retry next tick
                break
            except OSError:
                self.outq.popleft()
                continue
            self.outq.popleft()
            self.tx_frames += 1
            self.tx_bytes += len(data)
            wrote += 1
        return wrote

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


# ---------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology", default="topology.json", help="path to topology.json")
    parser.add_argument("--zmq-endpoint", default="ipc:///tmp/haven_zmq.sock", help="ZMQ socket endpoint")
    parser.add_argument("--pty-pattern", default="/tmp/haven_uart_{id}", help="PTY path pattern")
    parser.add_argument("--pty-timeout", type=int, default=30, help="seconds to wait for PTYs")
    parser.add_argument("--run-seconds", type=int, default=90, help="duration to run")
    parser.add_argument("--stop-on-leader", type=int, default=0,
                        help="stop after N leader heartbeats are observed (0 to disable)")
    parser.add_argument("--event-file", default=os.environ.get("HAVEN_EVENT_FILE", ""),
                        help="path to append JSONL events for GUI visualizer")
    parser.add_argument("--verbose", action="store_true", help="verbose frame logging")
    parser.add_argument("--direct-relay", action="store_true",
                        help="direct ring/mesh relay without ns-3 (standalone mode)")
    args = parser.parse_args()

    topo_path = Path(args.topology)
    if not topo_path.is_file():
        sys.exit(f"error: topology file not found: {topo_path}")

    topo = json.loads(topo_path.read_text())
    node_ids = [n["id"] for n in topo["nodes"]]
    num_nodes = len(node_ids)

    log(f"loaded topology: {topo_path} ({num_nodes} nodes)")

    # Build adjacency list if direct relay is used
    adj = {i: set() for i in node_ids}
    for lk in topo.get("links", []):
        adj[lk["a"]].add(lk["b"])
        adj[lk["b"]].add(lk["a"])

    # Initialize ZMQ DEALER socket
    ctx = zmq.Context()
    z_sock = None
    if not args.direct_relay:
        z_sock = ctx.socket(zmq.DEALER)
        z_sock.setsockopt(zmq.IDENTITY, ZMQ_IDENTITY)
        z_sock.setsockopt(zmq.SNDHWM, 10000)
        z_sock.setsockopt(zmq.RCVHWM, 10000)
        z_sock.connect(args.zmq_endpoint)
        log(f"connected ZMQ DEALER to {args.zmq_endpoint}")
    else:
        log("running in direct relay mode (ns-3 bypassed)")

    # Open PTYs concurrently
    nodes = {nid: Node(nid, args.pty_pattern.format(id=nid)) for nid in node_ids}
    log("waiting for PTYs " + ", ".join(str(nd.path) for nd in nodes.values()))

    deadline = time.time() + args.pty_timeout
    while time.time() < deadline:
        pending = [nd for nd in nodes.values() if nd.fd is None]
        if not pending:
            break
        for nd in pending:
            nd.open(0)
        if any(nd.fd is None for nd in pending):
            time.sleep(0.02)

    missing = [nd for nd in nodes.values() if nd.fd is None]
    if missing:
        for nd in missing:
            warn(f"no PTY at {nd.path} (node {nd.id})")
        sys.exit("error: not all Renode PTYs appeared within timeout.")

    log(f"all {num_nodes} PTYs open")

    stats = {t: 0 for t in FRAME_TYPES}
    seen_leader = set()
    stop = False

    def on_signal(sig, _frm):
        nonlocal stop
        stop = True
        log(f"signal {sig}, shutting down bridge")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    poller = zmq.Poller()
    if z_sock is not None:
        poller.register(z_sock, zmq.POLLIN)

    for nd in nodes.values():
        poller.register(nd.fd, zmq.POLLIN)

    started = time.time()
    run_deadline = started + args.run_seconds
    log(f"bridge active for {args.run_seconds}s. Press Ctrl-C to stop.")

    while not stop and time.time() < run_deadline:
        now = time.time()

        # Pump any pending outbound frames
        for nd in nodes.values():
            nd.pump(now)

        try:
            events = dict(poller.poll(10))   # 10ms timeout for responsive pacing
        except (KeyboardInterrupt, SystemExit, OSError):
            break

        now = time.time()
        for nd in nodes.values():
            nd.pump(now)

        if not events:
            continue

        # Check ZMQ inbound from ns-3 (drain all pending messages)
        if z_sock is not None and z_sock in events:
            while True:
                try:
                    msg = z_sock.recv(flags=zmq.NOBLOCK)
                except zmq.ZMQError:
                    break
                src, dst, raw_fr = unpack_envelope(msg)
                if dst is not None and dst in nodes and raw_fr:
                    nodes[dst].queue(raw_fr, now)
                    nodes[dst].pump(now)
                    if args.event_file and len(raw_fr) >= HDR_LEN:
                        r_ftype = raw_fr[1]
                        emit_event(args.event_file, {
                            "event": "rx",
                            "time": now,
                            "src": src,
                            "dst": dst,
                            "type": FRAME_TYPES.get(r_ftype, f"type{r_ftype}"),
                            "type_id": r_ftype,
                            "len": len(raw_fr) - HDR_LEN
                        })
                    if args.verbose:
                        log(f"  [ZMQ -> PTY] delivering to node {dst} ({len(raw_fr)}B)")

        # Check PTY inbound from Renode
        for nd in nodes.values():
            if nd.fd is not None and nd.fd in events:
                try:
                    data = os.read(nd.fd, 65536)
                except OSError:
                    continue
                if not data:
                    continue
                nd.rx_bytes += len(data)

                for fr in nd.feed(data):
                    nd.rx_frames += 1
                    ftype, ln, src, dst = fr[1], fr[2], fr[3], fr[4]
                    stats[ftype] = stats.get(ftype, 0) + 1

                    if args.event_file:
                        ev = {
                            "event": "tx",
                            "time": now,
                            "src": src,
                            "dst": dst,
                            "type": FRAME_TYPES.get(ftype, f"type{ftype}"),
                            "type_id": ftype,
                            "len": ln,
                            "hex": fr.hex()
                        }
                        if ftype == 2 and ln >= 2:
                            ev["score"] = fr[HDR_LEN]
                            ev["origin"] = fr[HDR_LEN + 1]
                        elif ftype == 3 and ln >= 2:
                            ev["origin"] = fr[HDR_LEN]
                            ev["score"] = fr[HDR_LEN + 1]
                        elif ftype == 4 and ln >= 5:
                            ev["leader_id"] = fr[HDR_LEN + 4]
                        emit_event(args.event_file, ev)

                    if ftype == 4 and ln >= 5:  # HEARTBEAT
                        lid = fr[HDR_LEN + 4]
                        if lid not in seen_leader:
                            seen_leader.add(lid)
                            log(f"node {lid} is sending heartbeats")
                            if args.event_file:
                                emit_event(args.event_file, {
                                    "event": "leader",
                                    "time": now,
                                    "leader_id": lid
                                })
                        if args.stop_on_leader and stats[4] >= args.stop_on_leader:
                            log(f"observed {stats[4]} heartbeats from leader {lid}; stopping early")
                            stop = True

                    if args.verbose:
                        label = FRAME_TYPES.get(ftype, f"type{ftype}")
                        log(f"  [PTY -> {'ZMQ' if z_sock else 'Relay'}] {src} -> "
                            f"{dst if dst != BROADCAST else 'all'} {label}({ln}B)")

                    if z_sock is not None:
                        # Forward to ns-3
                        env = pack_envelope(src, dst, fr)
                        try:
                            z_sock.send(env, flags=zmq.NOBLOCK)
                        except zmq.ZMQError:
                            warn("ZMQ send failed (buffer full)")
                    else:
                        # Direct relay mode
                        targets = adj.get(src, ())
                        if dst != BROADCAST and dst in targets:
                            targets = (dst,)
                        for t in targets:
                            nodes[t].queue(fr, now)
                            nodes[t].pump(now)

    elapsed = time.time() - started
    log(f"stopped after {elapsed:.1f}s")
    total = sum(stats.values())
    log("frames captured: " + ", ".join(
        f"{FRAME_TYPES.get(t, f'type{t}')}={c}" for t, c in sorted(stats.items())))
    log(f"total {total} frames")

    if args.event_file:
        emit_event(args.event_file, {
            "event": "finished",
            "time": time.time(),
            "elapsed": elapsed,
            "stats": {FRAME_TYPES.get(t, f"type{t}"): c for t, c in stats.items()},
            "leaders": sorted(seen_leader)
        })

    for nd in nodes.values():
        nd.close()

    if z_sock is not None:
        z_sock.close()
    ctx.term()

    if not seen_leader:
        warn("no heartbeat observed: no leader was elected within the window.")
        return 1

    log(_c("32", f"leader(s) established: {sorted(seen_leader)}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
