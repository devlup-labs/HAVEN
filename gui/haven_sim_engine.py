#!/usr/bin/env python3
"""
HAVEN High-Fidelity Discrete-Event Protocol Simulation Engine.

Faithfully implements the HAVEN protocol state machine as specified in:
- PSEUDOCODE.md
- firmware/src/haven.c
- sim/turboblom.py
- sim/tests/test_ring_election.py

Features:
- TurboBlom pairwise key pre-distribution & authentication
- Multi-phase election: Discovery -> Mode Decision -> Election Flooding -> Claiming -> Leader Heartbeats
- Asynchronous stepped or continuous real-time execution with adjustable speed
- Per-link delay and loss modeling
- Runtime fault injection: link drop, node kill/revive, battery alteration
- Event emission for real-time visualization over WebSockets
"""

import asyncio
import copy
import hashlib
import hmac
import json
import math
import random
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Callable, Any

# Ensure access to sim modules
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "sim") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "sim"))

try:
    from sim.turboblom import assign_spaces, compute_K_AB, generate_key_matrix
except ImportError:
    try:
        from turboblom import assign_spaces, compute_K_AB, generate_key_matrix
    except ImportError:
        def generate_key_matrix(m, seed):
            return [hmac.new(seed, b'row' + i.to_bytes(2, 'big'), hashlib.sha256).digest() for i in range(m)]

        def assign_spaces(node_id, k, m, k_master):
            spaces = []
            seen = set()
            counter = 0
            while len(spaces) < k:
                msg = b'spaces' + node_id.to_bytes(4, 'big') + counter.to_bytes(4, 'big')
                h = hmac.new(k_master, msg, hashlib.sha256).digest()
                for byte in h:
                    idx = byte % m
                    if idx not in seen:
                        seen.add(idx)
                        spaces.append(idx)
                        if len(spaces) == k:
                            break
                counter += 1
            return sorted(spaces)

        def compute_K_AB(node_a, node_b, matrix, spaces_a, spaces_b):
            shared = set(spaces_a) & set(spaces_b)
            if not shared:
                return None
            xor_sum = bytearray(32)
            for idx in sorted(shared):
                row = matrix[idx]
                for i in range(32):
                    xor_sum[i] ^= row[i]
            msg = xor_sum + min(node_a, node_b).to_bytes(4, 'big') + max(node_a, node_b).to_bytes(4, 'big')
            return hashlib.sha256(msg).digest()[:16]

K_MASTER = bytes(range(32))
PRNG_A, PRNG_B, PRNG_M = 1664525, 1013904223, 4294967296
DEFAULT_BATTERIES = [100, 80, 60, 40, 20, 90, 70, 50, 30, 10,
                     95, 75, 55, 35, 15, 85, 65, 45, 25, 5]


class LCG:
    """Exact mirror of prng_next() in haven.c."""
    def __init__(self, seed: int):
        self.s = seed % PRNG_M

    def next(self) -> int:
        self.s = (PRNG_A * self.s + PRNG_B) % PRNG_M
        return self.s


def odds_permille(battery_pct: int, nb_n: int, max_adj: int, l: int = 1, m: int = 1) -> int:
    """Mirror of haven.c PHASE 2, fixed-point permille."""
    if max_adj <= 0:
        max_adj = 1
    o = ((l * battery_pct * 1000) // 100 + (m * nb_n * 1000) // max_adj) // 2
    return max(1, o)


class ProtocolNode:
    def __init__(self, node_id: int, battery: int, spaces: List[int], x: float, y: float):
        self.id = node_id
        self.battery = battery
        self.spaces = list(spaces)
        self.x = x
        self.y = y
        self.alive = True

        # Protocol state
        self.mode = "DISCOVERY"  # DISCOVERY -> ELECTION | PASSTHROUGH -> CLAIMING -> LEADER
        self.internal_score = 0
        self.neighbour_list: List[int] = []
        self.neighbour_keys: Dict[int, str] = {}  # peer_id -> hex key
        self.best_known_score = 0
        self.best_known_origin = 0
        self.echo_count = 0
        self.timeout_started = False
        self.claim_timer: Optional[int] = None
        self.window_timer: Optional[int] = None
        self.leader_id: Optional[int] = None
        self.fwd_mask: Set[Tuple[int, int]] = set()  # (origin, replayer)
        self.heartbeat_counter = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "battery": self.battery,
            "spaces": self.spaces,
            "x": self.x,
            "y": self.y,
            "alive": self.alive,
            "mode": self.mode,
            "score": self.internal_score,
            "best_score": self.best_known_score,
            "best_origin": self.best_known_origin,
            "echo_count": self.echo_count,
            "leader_id": self.leader_id,
            "neighbours": self.neighbour_list,
            "heartbeat_count": self.heartbeat_counter
        }


class HavenSimEngine:
    """Discrete-Event Protocol Simulator with continuous playback and step controls."""

    def __init__(self, topology: Dict[str, Any], event_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.raw_topology = copy.deepcopy(topology)
        self.event_callback = event_callback

        self.meta = self.raw_topology.get("meta", {})
        self.echo_threshold = self.meta.get("echo_threshold", 2)
        self.max_adj_nodes = self.meta.get("max_adj_nodes", 8)
        self.m_spaces = self.meta.get("m_spaces", 12)
        self.k_spaces = self.meta.get("k_spaces", 5)
        self.matrix = generate_key_matrix(self.m_spaces, K_MASTER)

        # Simulation controls
        self.status = "IDLE"  # IDLE, RUNNING, PAUSED, CONVERGED, STOPPED
        self.hop = 0
        self.sim_time_ms = 0.0
        self.speed = 1.0  # multiplier: 1.0 = normal, 2.0 = fast, 0.5 = slow
        self.step_delay = 0.4  # base seconds per hop

        # Protocol timings (in hops)
        self.t_claim_hops = 2
        self.t_window_hops = 2
        self.heartbeat_interval_hops = 3

        # Physical links
        self.links: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.adj_physical: Dict[int, Set[int]] = {}
        self.disabled_links: Set[Tuple[int, int]] = set()

        # In-flight packets: list of {src, dst, type, payload, remaining_hops, id}
        self.in_flight: List[Dict[str, Any]] = []
        self.packet_seq = 0

        # Stats
        self.stats = {
            "DISCOVERY": 0,
            "ELECTION": 0,
            "CLAIM": 0,
            "HEARTBEAT": 0,
            "DROPPED": 0,
            "TOTAL": 0
        }
        self.leader: Optional[int] = None
        self.convergence_hop: Optional[int] = None
        self.convergence_time_ms: Optional[float] = None

        # Nodes
        self.nodes: Dict[int, ProtocolNode] = {}
        self.rng: Dict[int, LCG] = {}

        self._async_task: Optional[asyncio.Task] = None
        self._init_from_topology()

    def _init_from_topology(self):
        nodes_data = self.raw_topology.get("nodes", [])
        num_nodes = len(nodes_data)

        # Default circle layout if coordinates are missing
        for idx, nd in enumerate(nodes_data):
            nid = nd["id"]
            battery = nd.get("battery", DEFAULT_BATTERIES[(nid - 1) % len(DEFAULT_BATTERIES)])
            spaces = nd.get("spaces")
            if not spaces:
                spaces = assign_spaces(nid, self.k_spaces, self.m_spaces, K_MASTER)
            x = nd.get("x")
            y = nd.get("y")
            if x is None or y is None:
                angle = 2.0 * math.pi * idx / max(1, num_nodes)
                x = 500.0 + 320.0 * math.cos(angle)
                y = 500.0 + 320.0 * math.sin(angle)

            pnode = ProtocolNode(nid, battery, spaces, x, y)
            self.nodes[nid] = pnode
            self.rng[nid] = LCG(nid)
            self.adj_physical[nid] = set()

        # Parse links
        links_data = self.raw_topology.get("links", [])
        for lk in links_data:
            a, b = lk["a"], lk["b"]
            if a in self.nodes and b in self.nodes:
                self.adj_physical[a].add(b)
                self.adj_physical[b].add(a)
                pair = (min(a, b), max(a, b))
                self.links[pair] = {
                    "a": a,
                    "b": b,
                    "loss_pct": float(lk.get("loss_pct", 0.0)),
                    "delay_ms": int(lk.get("delay_ms", 20)),
                    "bw_bps": int(lk.get("bw_bps", 9600))
                }

    def emit(self, event_type: str, data: Dict[str, Any]):
        if self.event_callback:
            try:
                self.event_callback({
                    "event": event_type,
                    "time_ms": self.sim_time_ms,
                    "hop": self.hop,
                    **data
                })
            except Exception:
                pass

    def get_topology_dict(self) -> Dict[str, Any]:
        """Return serialized topology state including runtime node states."""
        return {
            "meta": {
                **self.meta,
                "echo_threshold": self.echo_threshold,
                "max_adj_nodes": self.max_adj_nodes,
                "m_spaces": self.m_spaces,
                "k_spaces": self.k_spaces,
                "status": self.status,
                "leader": self.leader,
                "hop": self.hop,
                "sim_time_ms": self.sim_time_ms,
                "convergence_hop": self.convergence_hop,
                "convergence_time_ms": self.convergence_time_ms,
                "stats": self.stats
            },
            "nodes": [nd.to_dict() for nd in self.nodes.values()],
            "links": [
                {
                    "a": lk["a"],
                    "b": lk["b"],
                    "loss_pct": lk["loss_pct"],
                    "delay_ms": lk["delay_ms"],
                    "bw_bps": lk["bw_bps"],
                    "disabled": (min(lk["a"], lk["b"]), max(lk["a"], lk["b"])) in self.disabled_links
                }
                for lk in self.links.values()
            ]
        }

    # ------------------------------------------------------------- Fault injection
    def toggle_link(self, u: int, v: int, disable: Optional[bool] = None) -> bool:
        pair = (min(u, v), max(u, v))
        if pair not in self.links:
            return False
        if disable is None:
            if pair in self.disabled_links:
                self.disabled_links.remove(pair)
                state = False
            else:
                self.disabled_links.add(pair)
                state = True
        elif disable:
            self.disabled_links.add(pair)
            state = True
        else:
            self.disabled_links.discard(pair)
            state = False

        self.emit("link_state", {"u": u, "v": v, "disabled": state})
        return state

    def toggle_node(self, node_id: int, alive: Optional[bool] = None) -> bool:
        if node_id not in self.nodes:
            return False
        nd = self.nodes[node_id]
        if alive is None:
            nd.alive = not nd.alive
        else:
            nd.alive = alive

        self.emit("node_alive", {"node_id": node_id, "alive": nd.alive})
        return nd.alive

    def set_node_battery(self, node_id: int, battery: int):
        if node_id not in self.nodes:
            return
        nd = self.nodes[node_id]
        nd.battery = max(0, min(100, battery))
        self.emit("node_battery", {"node_id": node_id, "battery": nd.battery})

    # ------------------------------------------------------------- Simulation cycle
    def start_sim(self):
        """Begin simulation from Phase 1: Discovery & Key Derivation."""
        self.status = "RUNNING"
        self.hop = 0
        self.sim_time_ms = 0.0
        self.in_flight.clear()
        self.leader = None
        self.convergence_hop = None
        self.convergence_time_ms = None
        self.stats = {k: 0 for k in self.stats}

        for nid, nd in self.nodes.items():
            nd.mode = "DISCOVERY"
            nd.neighbour_list.clear()
            nd.neighbour_keys.clear()
            nd.fwd_mask.clear()
            nd.echo_count = 0
            nd.timeout_started = False
            nd.claim_timer = None
            nd.window_timer = None
            nd.leader_id = None
            nd.best_known_score = 0
            nd.best_known_origin = 0

        self.emit("sim_start", {"status": "RUNNING"})

        # Launch Discovery broadcasts from all alive nodes
        for nid, nd in self.nodes.items():
            if not nd.alive:
                continue
            for peer in self.adj_physical[nid]:
                self._send_frame(
                    src=nid,
                    dst=peer,
                    frame_type="DISCOVERY",
                    payload={"spaces": nd.spaces}
                )

    def _send_frame(self, src: int, dst: int, frame_type: str, payload: Dict[str, Any]):
        pair = (min(src, dst), max(src, dst))
        if pair in self.disabled_links:
            self.stats["DROPPED"] += 1
            self.emit("frame_drop", {
                "src": src,
                "dst": dst,
                "type": frame_type,
                "reason": "link_disabled"
            })
            return

        # Check loss model
        link_info = self.links.get(pair, {"loss_pct": 0, "delay_ms": 20})
        if link_info.get("loss_pct", 0) > 0:
            if random.uniform(0, 100) < link_info["loss_pct"]:
                self.stats["DROPPED"] += 1
                self.emit("frame_drop", {
                    "src": src,
                    "dst": dst,
                    "type": frame_type,
                    "reason": "loss_model"
                })
                return

        self.packet_seq += 1
        pkt = {
            "id": self.packet_seq,
            "src": src,
            "dst": dst,
            "type": frame_type,
            "payload": payload,
            "remaining_hops": 1,
            "delay_ms": link_info.get("delay_ms", 20)
        }
        self.in_flight.append(pkt)
        self.stats[frame_type] = self.stats.get(frame_type, 0) + 1
        self.stats["TOTAL"] += 1

        self.emit("frame_tx", {
            "pkt_id": pkt["id"],
            "src": src,
            "dst": dst,
            "type": frame_type,
            "payload": payload,
            "delay_ms": pkt["delay_ms"]
        })

    def step(self):
        """Advance discrete simulation by 1 hop/tick."""
        if self.status not in ("RUNNING", "CONVERGED"):
            return

        self.hop += 1
        self.sim_time_ms += 20.0  # canonical 20ms per hop

        # 1. Deliver in-flight packets
        current_batch = list(self.in_flight)
        self.in_flight.clear()

        delivered_election_frames: List[Dict[str, Any]] = []

        for pkt in current_batch:
            src = pkt["src"]
            dst = pkt["dst"]
            ftype = pkt["type"]
            payload = pkt["payload"]

            if dst not in self.nodes or not self.nodes[dst].alive:
                continue

            dest_node = self.nodes[dst]

            self.emit("frame_rx", {
                "pkt_id": pkt["id"],
                "src": src,
                "dst": dst,
                "type": ftype,
                "payload": payload
            })

            # Process by frame type
            if ftype == "DISCOVERY":
                self._handle_discovery(dest_node, src, payload)
            elif ftype == "ELECTION":
                delivered_election_frames.append((dest_node, src, payload))
            elif ftype == "CLAIM":
                self._handle_claim(dest_node, src, payload)
            elif ftype == "HEARTBEAT":
                self._handle_heartbeat(dest_node, src, payload)

        # Handle Election frames after discovery phase
        for dest_node, src, payload in delivered_election_frames:
            self._handle_election(dest_node, src, payload)

        # 2. Check Discovery completion -> transition to Phase 2 Mode Decision
        if self.hop == 2:
            self._evaluate_mode_decisions()

        # 3. Check Timers (T_claim expiry -> CLAIM; T_window expiry -> LEADER)
        self._check_node_timers()

        # 4. Periodic Heartbeats if Leader established
        if self.leader is not None and self.hop % self.heartbeat_interval_hops == 0:
            ldr = self.nodes.get(self.leader)
            if ldr and ldr.alive:
                ldr.heartbeat_counter += 1
                for peer in ldr.neighbour_list:
                    self._send_frame(
                        src=ldr.id,
                        dst=peer,
                        frame_type="HEARTBEAT",
                        payload={"leader_id": ldr.id, "epoch": 1, "count": ldr.heartbeat_counter}
                    )

        self.emit("step_complete", {
            "hop": self.hop,
            "sim_time_ms": self.sim_time_ms,
            "in_flight": len(self.in_flight),
            "leader": self.leader,
            "stats": self.stats
        })

    def _handle_discovery(self, node: ProtocolNode, peer_id: int, payload: Dict[str, Any]):
        peer_spaces = payload.get("spaces", [])
        shared = set(node.spaces) & set(peer_spaces)
        if shared:
            if peer_id not in node.neighbour_list:
                node.neighbour_list.append(peer_id)
                k_ab = compute_K_AB(node.id, peer_id, self.matrix, node.spaces, peer_spaces)
                node.neighbour_keys[peer_id] = k_ab.hex() if k_ab else "shared_space"

                self.emit("node_auth", {
                    "node_id": node.id,
                    "peer_id": peer_id,
                    "shared_spaces": sorted(list(shared)),
                    "total_neighbours": len(node.neighbour_list)
                })

    def _evaluate_mode_decisions(self):
        """PHASE 2: Score computation and candidacy coin flip."""
        for nid, nd in self.nodes.items():
            if not nd.alive:
                continue
            nb_n = len(nd.neighbour_list)
            nd.internal_score = nd.battery + nb_n
            nd.best_known_score = nd.internal_score
            nd.best_known_origin = nd.id

            odds = odds_permille(nd.battery, nb_n, self.max_adj_nodes)
            prob = (self.rng[nid].next() * 1000) // PRNG_M

            if odds > prob:
                nd.mode = "ELECTION"
                self.emit("mode_change", {"node_id": nid, "mode": "ELECTION", "score": nd.internal_score})
                # Broadcast election packet to all authenticated neighbours
                for peer in nd.neighbour_list:
                    self._send_frame(
                        src=nid,
                        dst=peer,
                        frame_type="ELECTION",
                        payload={
                            "score": nd.internal_score,
                            "origin": nid,
                            "replayer": nid,
                            "age": 0
                        }
                    )
            else:
                nd.mode = "PASSTHROUGH"
                self.emit("mode_change", {"node_id": nid, "mode": "PASSTHROUGH", "score": nd.internal_score})

    def _handle_election(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        score = payload["score"]
        origin = payload["origin"]
        replayer = payload["replayer"]
        age = payload.get("age", 0)

        # 1. Own packet returned home -> Echo!
        if origin == node.id:
            node.echo_count += 1
            self.emit("echo_received", {
                "node_id": node.id,
                "echo_count": node.echo_count,
                "threshold": self.echo_threshold
            })
            if node.echo_count >= self.echo_threshold and not node.timeout_started:
                node.timeout_started = True
                node.claim_timer = self.hop + self.t_claim_hops
                self.emit("claim_timer_armed", {
                    "node_id": node.id,
                    "fires_at_hop": node.claim_timer
                })
            return

        # 2. Check if received score beats best known score
        cur_score, cur_origin = node.best_known_score, node.best_known_origin
        better = (score > cur_score) or (score == cur_score and origin > cur_origin)

        if better:
            node.best_known_score = score
            node.best_known_origin = origin
            node.echo_count = 0
            node.timeout_started = False
            node.claim_timer = None
            if node.mode == "ELECTION":
                node.mode = "PASSTHROUGH"
                self.emit("mode_change", {"node_id": node.id, "mode": "PASSTHROUGH", "demoted_by": origin})

        # 3. Forward directional copy (excluding sender, at most once per (origin, replayer))
        pair = (origin, replayer)
        if pair in node.fwd_mask:
            return
        node.fwd_mask.add(pair)

        for peer in node.neighbour_list:
            if peer != replayer and peer != sender_id:
                self._send_frame(
                    src=node.id,
                    dst=peer,
                    frame_type="ELECTION",
                    payload={
                        "score": score,
                        "origin": origin,
                        "replayer": node.id,
                        "age": age + 1
                    }
                )

    def _check_node_timers(self):
        for nid, nd in self.nodes.items():
            if not nd.alive:
                continue

            # Check Claim Timer
            if nd.claim_timer is not None and self.hop >= nd.claim_timer:
                nd.claim_timer = None
                if nd.best_known_origin == nd.id:
                    nd.mode = "CLAIMING"
                    nd.window_timer = self.hop + self.t_window_hops
                    self.emit("mode_change", {"node_id": nid, "mode": "CLAIMING"})
                    self.emit("claim_broadcast", {"node_id": nid, "window_hops": self.t_window_hops})

                    # Broadcast CLAIM frame
                    for peer in nd.neighbour_list:
                        self._send_frame(
                            src=nid,
                            dst=peer,
                            frame_type="CLAIM",
                            payload={"origin": nid, "score": nd.best_known_score}
                        )
                else:
                    nd.mode = "PASSTHROUGH"

            # Check Window Timer -> Transition to LEADER!
            if nd.window_timer is not None and self.hop >= nd.window_timer:
                nd.window_timer = None
                if nd.best_known_origin == nd.id:
                    nd.mode = "LEADER"
                    nd.leader_id = nd.id
                    self.leader = nd.id
                    self.status = "CONVERGED"
                    self.convergence_hop = self.hop
                    self.convergence_time_ms = self.sim_time_ms

                    self.emit("leader_elected", {
                        "leader_id": nd.id,
                        "battery": nd.battery,
                        "score": nd.best_known_score,
                        "hop": self.hop,
                        "time_ms": self.sim_time_ms
                    })
                    self.emit("mode_change", {"node_id": nid, "mode": "LEADER"})

    def _handle_claim(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        origin = payload["origin"]
        score = payload["score"]

        # If incoming claim has higher score, yield
        if score > node.best_known_score or (score == node.best_known_score and origin > node.best_known_origin):
            node.best_known_score = score
            node.best_known_origin = origin
            node.claim_timer = None
            node.window_timer = None
            if node.mode in ("ELECTION", "CLAIMING"):
                node.mode = "PASSTHROUGH"
                self.emit("mode_change", {"node_id": node.id, "mode": "PASSTHROUGH"})

        # Forward CLAIM along the network
        pair = (origin, sender_id)
        if pair not in node.fwd_mask:
            node.fwd_mask.add(pair)
            for peer in node.neighbour_list:
                if peer != sender_id:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="CLAIM",
                        payload=payload
                    )

    def _handle_heartbeat(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        leader_id = payload["leader_id"]
        node.leader_id = leader_id

        # Forward heartbeat to neighbors
        pair = (leader_id, sender_id)
        if pair not in node.fwd_mask:
            node.fwd_mask.add(pair)
            for peer in node.neighbour_list:
                if peer != sender_id:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="HEARTBEAT",
                        payload=payload
                    )

    # ------------------------------------------------------------- Async runner
    async def run_loop(self):
        try:
            while self.status == "RUNNING":
                self.step()
                delay = max(0.02, self.step_delay / max(0.1, self.speed))
                await asyncio.sleep(delay)
                # Auto-stop if converged and sent multiple heartbeats
                if self.status == "CONVERGED" and self.stats.get("HEARTBEAT", 0) >= 15:
                    break
        except asyncio.CancelledError:
            pass

    def start_async(self):
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
        self.start_sim()
        self._async_task = asyncio.create_task(self.run_loop())

    def pause(self):
        if self.status == "RUNNING":
            self.status = "PAUSED"
            if self._async_task:
                self._async_task.cancel()
            self.emit("sim_pause", {"status": "PAUSED"})

    def resume(self):
        if self.status == "PAUSED":
            self.status = "RUNNING"
            self._async_task = asyncio.create_task(self.run_loop())
            self.emit("sim_resume", {"status": "RUNNING"})

    def stop(self):
        self.status = "STOPPED"
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
        self.emit("sim_stop", {"status": "STOPPED"})
