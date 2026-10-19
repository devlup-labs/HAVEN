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
if str(ROOT_DIR / "test_simulation") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "test_simulation"))
if str(ROOT_DIR / "sim") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "sim"))

try:
    from test_simulation.turboblom import assign_spaces, compute_K_AB, generate_key_matrix
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
    def __init__(self, node_id: int, battery: float, spaces: List[int], x: float, y: float):
        self.id = node_id
        self.battery = float(battery)
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
        self.fwd_mask: Set[Tuple[Any, Any]] = set()  # (origin, replayer)
        self.heartbeat_counter = 0
        self.election_start_hop: int = 0
        self.last_hb_hop: int = 0
        self.partition: str = "A"
        self.join_request_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "battery": int(round(self.battery)),
            "battery_float": round(self.battery, 2),
            "spaces": self.spaces,
            "x": self.x,
            "y": self.y,
            "alive": self.alive,
            "mode": self.mode if self.alive else "OFFLINE",
            "score": self.internal_score,
            "best_score": self.best_known_score,
            "best_origin": self.best_known_origin,
            "echo_count": self.echo_count,
            "leader_id": self.leader_id,
            "partition": getattr(self, "partition", "A"),
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

        # Dynamic Battery & Energy simulation
        self.battery_drain_enabled = True
        self.battery_drain_rate = 1.0  # multiplier: 1.0 = normal, 5.0 = fast, 15.0 = turbo
        self.node_tx_cost = 0.5        # % battery per transmitted frame for general nodes
        self.leader_tx_cost = 1.5      # % battery per transmitted frame for leader nodes
        self.tx_cost = self.node_tx_cost  # alias for backward compatibility
        self.rx_cost = 0.05            # % battery per received frame
        self.idle_cost = 0.01          # % battery per hop baseline
        self.leader_resignation_threshold = 15.0  # % battery where leader yields for handover

        # Physical links
        self.links: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self.adj_physical: Dict[int, Set[int]] = {}
        self.disabled_links: Set[Tuple[int, int]] = set()
        self.partition_cut_links: Set[Tuple[int, int]] = set()
        self.resignation_threshold: int = 1
        self.pending_global_re_election: bool = False
        self.pending_re_election_hop: int = 0

        # In-flight packets: list of {src, dst, type, payload, remaining_hops, id}
        self.in_flight: List[Dict[str, Any]] = []
        self.packet_seq = 0

        # Stats
        self.stats = {
            "DISCOVERY": 0,
            "ELECTION": 0,
            "CLAIM": 0,
            "HEARTBEAT": 0,
            "FIND_LEADER": 0,
            "LEADER_ACK": 0,
            "JOIN_REQUEST": 0,
            "RESIGNATION": 0,
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

    @property
    def leaders(self) -> List[int]:
        """List of all currently elected leader IDs across all active partitions."""
        return sorted([n.id for n in self.nodes.values() if n.alive and n.mode == "LEADER"])

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
                if lk.get("disabled", False):
                    self.disabled_links.add(pair)
                    self.partition_cut_links.add(pair)

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
        """Return serialized topology state including runtime node states and partition info."""
        partitions = self.get_active_partitions()
        is_partitioned = len(partitions) > 1
        active_leaders = [p["leader"] for p in partitions if p["leader"] is not None]
        primary_leader = self.leader if self.leader in active_leaders else (active_leaders[0] if active_leaders else None)

        # Update node partition tags
        for p in partitions:
            for nid in p["nodes"]:
                if nid in self.nodes:
                    self.nodes[nid].partition = p["id"]

        return {
            "meta": {
                **self.meta,
                "echo_threshold": self.echo_threshold,
                "max_adj_nodes": self.max_adj_nodes,
                "m_spaces": self.m_spaces,
                "k_spaces": self.k_spaces,
                "status": self.status,
                "leader": primary_leader,
                "leaders": active_leaders,
                "is_partitioned": is_partitioned,
                "partitions": partitions,
                "severed_bridge_links": [list(x) for x in self.partition_cut_links if x in self.disabled_links],
                "resignation_threshold": getattr(self, "resignation_threshold", 1),
                "hop": self.hop,
                "sim_time_ms": self.sim_time_ms,
                "convergence_hop": self.convergence_hop,
                "convergence_time_ms": self.convergence_time_ms,
                "battery_drain_enabled": self.battery_drain_enabled,
                "battery_drain_rate": self.battery_drain_rate,
                "node_tx_cost": self.node_tx_cost,
                "leader_tx_cost": self.leader_tx_cost,
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

    # ------------------------------------------------------------- Network Splitting & Merging (Phase 12 / 13)
    def get_connected_components(self) -> List[List[int]]:
        """Return connected components of alive nodes over enabled links."""
        alive_ids = {nid for nid, nd in self.nodes.items() if nd.alive}
        adj = {nid: set() for nid in alive_ids}
        for (u, v) in self.links:
            if (min(u, v), max(u, v)) not in self.disabled_links:
                if u in alive_ids and v in alive_ids:
                    adj[u].add(v)
                    adj[v].add(u)

        visited = set()
        components = []
        for nid in sorted(alive_ids):
            if nid not in visited:
                comp = []
                queue = [nid]
                visited.add(nid)
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for nb in adj.get(curr, []):
                        if nb not in visited:
                            visited.add(nb)
                            queue.append(nb)
                components.append(sorted(comp))
        return components

    def get_active_partitions(self) -> List[Dict[str, Any]]:
        """Return metadata for all active connected network partitions/clusters."""
        comps = self.get_connected_components()
        partitions = []
        letters = ["A", "B", "C", "D", "E"]
        for idx, comp in enumerate(comps):
            label = letters[idx] if idx < len(letters) else f"P{idx+1}"
            leader = next((nid for nid in comp if self.nodes[nid].mode == "LEADER"), None)
            partitions.append({
                "id": label,
                "name": f"Network {label}",
                "nodes": comp,
                "leader": leader,
                "node_count": len(comp)
            })
        return partitions

    def find_bipartition(self) -> Tuple[List[int], List[int], List[Tuple[int, int]]]:
        """Find a clean 2-way partition of the active graph and the crossing cut edges."""
        alive_ids = sorted([nid for nid, nd in self.nodes.items() if nd.alive])
        n = len(alive_ids)
        if n < 2:
            return alive_ids, [], []

        # Check if ring
        is_ring = True
        for nid in alive_ids:
            active_nb = [p for p in self.adj_physical.get(nid, []) if p in alive_ids and (min(nid, p), max(nid, p)) not in self.disabled_links]
            if len(active_nb) != 2:
                is_ring = False
                break

        if is_ring:
            half = n // 2
            comp_a = alive_ids[:half]
            comp_b = alive_ids[half:]
            comp_a_set = set(comp_a)
            cut_links = []
            for (u, v) in self.links:
                if (min(u, v), max(u, v)) not in self.disabled_links:
                    if (u in comp_a_set and v not in comp_a_set) or (v in comp_a_set and u not in comp_a_set):
                        cut_links.append((min(u, v), max(u, v)))
            return comp_a, comp_b, cut_links

        target_a = max(1, n // 2)
        adj = {nid: set() for nid in alive_ids}
        for (u, v) in self.links:
            if (min(u, v), max(u, v)) not in self.disabled_links:
                if u in alive_ids and v in alive_ids:
                    adj[u].add(v)
                    adj[v].add(u)

        queue = deque([alive_ids[0]])
        visited = {alive_ids[0]}
        comp_a = []
        while queue and len(comp_a) < target_a:
            curr = queue.popleft()
            comp_a.append(curr)
            for nb in sorted(adj.get(curr, [])):
                if nb not in visited and (len(comp_a) + len(queue)) < target_a:
                    visited.add(nb)
                    queue.append(nb)

        comp_a_set = set(comp_a)
        comp_b = [x for x in alive_ids if x not in comp_a_set]
        cut_links = []
        for (u, v) in self.links:
            if (min(u, v), max(u, v)) not in self.disabled_links:
                if (u in comp_a_set and v not in comp_a_set) or (v in comp_a_set and u not in comp_a_set):
                    cut_links.append((min(u, v), max(u, v)))

        return sorted(comp_a), sorted(comp_b), cut_links

    def split_network(self, cut_links: Optional[List[Tuple[int, int]]] = None) -> Dict[str, Any]:
        """
        Phase 12: Split the network into two disjoint partitions.
        Sever bridge links, detect partition, emit FIND_LEADER packets,
        and trigger local re-election in the segment isolated from the former leader.
        """
        if not cut_links:
            preset_bridges = self.meta.get("default_bridge_links")
            if preset_bridges:
                cut_links = [tuple(sorted((int(x[0]), int(x[1])))) for x in preset_bridges]
            else:
                _, _, cut_links = self.find_bipartition()

        if not cut_links:
            return {"success": False, "reason": "No cut links found to split the network"}

        severed = []
        for (u, v) in cut_links:
            pair = (min(u, v), max(u, v))
            if pair in self.links:
                self.disabled_links.add(pair)
                self.partition_cut_links.add(pair)
                severed.append(pair)
                self.emit("link_state", {"u": pair[0], "v": pair[1], "disabled": True})

        comps = self.get_connected_components()
        if len(comps) < 2:
            return {"success": False, "reason": "Cut did not partition the graph"}

        self.emit("network_split", {
            "hop": self.hop,
            "severed_links": [list(x) for x in severed],
            "partitions": [{"name": f"Network {chr(65+i)}", "nodes": c} for i, c in enumerate(comps)]
        })
        self.emit("sim_log", {
            "message": f"PHASE 12: Network split into {len(comps)} partitions! Severed bridge links: {severed}",
            "level": "warn"
        })

        former_leader = self.leader
        leader_comp_idx = None
        if former_leader is not None:
            for idx, c in enumerate(comps):
                if former_leader in c and self.nodes[former_leader].alive:
                    leader_comp_idx = idx
                    break

        # Border nodes detect severed link and emit FIND_LEADER
        for (u, v) in severed:
            for border_id, lost_nb in [(u, v), (v, u)]:
                if border_id in self.nodes and self.nodes[border_id].alive:
                    self.emit("link_severed_detected", {
                        "node_id": border_id,
                        "lost_neighbour": lost_nb,
                        "hop": self.hop
                    })
                    for peer in self.adj_physical.get(border_id, []):
                        p_pair = (min(border_id, peer), max(border_id, peer))
                        if p_pair not in self.disabled_links and self.nodes.get(peer) and self.nodes[peer].alive:
                            self._send_frame(
                                src=border_id,
                                dst=peer,
                                frame_type="FIND_LEADER",
                                payload={
                                    "requester": border_id,
                                    "lost_neighbour": lost_nb,
                                    "expected_leader": former_leader
                                }
                            )

        # In components cut off from the former leader, confirm partition and trigger local re-election
        for idx, comp in enumerate(comps):
            if idx != leader_comp_idx:
                comp_nodes = [self.nodes[nid] for nid in comp if self.nodes[nid].alive]
                if comp_nodes:
                    self.emit("partition_confirmed", {
                        "component_nodes": comp,
                        "reason": "leader_severed",
                        "hop": self.hop
                    })
                    self.emit("sim_log", {
                        "message": f"Phase 12: Network {chr(65+idx)} [{', '.join(f'#{x}' for x in comp)}] partitioned from Leader #{former_leader}! Triggering local re-election.",
                        "level": "warn"
                    })
                    for nd in comp_nodes:
                        nd.leader_id = None
                    self._trigger_component_election(comp_nodes)

        self.status = "RUNNING"
        self._ensure_loop_running()
        return {
            "success": True,
            "severed_links": [list(x) for x in severed],
            "partitions": comps
        }

    def join_networks(self, bridge_links: Optional[List[Tuple[int, int]]] = None) -> Dict[str, Any]:
        """
        Phase 13: Merge partitioned networks into a single unified network.
        Re-enables bridge links, border nodes discover foreign leaders,
        emit JOIN_REQUEST to active leaders, leaders resign, and GLOBAL_RE_ELECTION is triggered.
        """
        if not bridge_links:
            if self.partition_cut_links:
                bridge_links = list(self.partition_cut_links)
            else:
                comps = self.get_connected_components()
                if len(comps) >= 2:
                    comp_map = {}
                    for idx, c in enumerate(comps):
                        for nid in c:
                            comp_map[nid] = idx
                    crossing = []
                    for (u, v) in self.disabled_links:
                        if u in comp_map and v in comp_map and comp_map[u] != comp_map[v]:
                            crossing.append((u, v))
                    bridge_links = crossing

        if not bridge_links:
            comps = self.get_connected_components()
            if len(comps) <= 1:
                return {"success": False, "reason": "Network is already unified into a single component"}
            return {"success": False, "reason": "No bridge links available to join partitions"}

        reconnected = []
        for (u, v) in bridge_links:
            pair = (min(u, v), max(u, v))
            self.disabled_links.discard(pair)
            self.partition_cut_links.discard(pair)
            reconnected.append(pair)
            self.emit("link_state", {"u": pair[0], "v": pair[1], "disabled": False})

        new_comps = self.get_connected_components()
        self.emit("network_join", {
            "hop": self.hop,
            "reconnected_links": [list(x) for x in reconnected],
            "unified_components": len(new_comps)
        })
        self.emit("sim_log", {
            "message": f"PHASE 13: Bridge links reconnected: {reconnected}! Initiating network merge protocol...",
            "level": "info"
        })

        join_req_sent = False
        active_leaders = [n for n in self.nodes.values() if n.alive and n.mode == "LEADER"]

        for (u, v) in reconnected:
            nd_u = self.nodes.get(u)
            nd_v = self.nodes.get(v)
            if not nd_u or not nd_v or not nd_u.alive or not nd_v.alive:
                continue

            if v not in nd_u.neighbour_list:
                nd_u.neighbour_list.append(v)
            if u not in nd_v.neighbour_list:
                nd_v.neighbour_list.append(u)

            # Exchange DISCOVERY
            self._send_frame(src=u, dst=v, frame_type="DISCOVERY", payload={"spaces": nd_u.spaces})
            self._send_frame(src=v, dst=u, frame_type="DISCOVERY", payload={"spaces": nd_v.spaces})

            l_u = nd_u.leader_id
            l_v = nd_v.leader_id

            if l_u is not None and l_v is not None and l_u != l_v:
                self._handle_foreign_leader_contact(nd_u, v, l_v)
                self._handle_foreign_leader_contact(nd_v, u, l_u)
                join_req_sent = True
            elif active_leaders:
                target = l_u or (active_leaders[0].id if active_leaders else None)
                if target:
                    self._handle_foreign_leader_contact(nd_u, v, l_v or 0)
                    join_req_sent = True

        if not join_req_sent or not active_leaders:
            self.emit("sim_log", {
                "message": "Phase 13: Bridge reconnected. Triggering GLOBAL_RE_ELECTION across unified network.",
                "level": "info"
            })
            self._trigger_re_election()

        self.status = "RUNNING"
        self._ensure_loop_running()
        return {
            "success": True,
            "reconnected_links": [list(x) for x in reconnected],
            "active_components": len(new_comps)
        }

    def _find_next_hop_toward(self, src_id: int, target_id: int) -> Optional[int]:
        """BFS shortest path to find the next hop node toward target_id via enabled links."""
        if src_id == target_id:
            return None
        alive_ids = {nid for nid, nd in self.nodes.items() if nd.alive}
        adj = {nid: [] for nid in alive_ids}
        for (u, v), lk in self.links.items():
            if (min(u, v), max(u, v)) not in self.disabled_links:
                if u in alive_ids and v in alive_ids:
                    adj[u].append(v)
                    adj[v].append(u)

        queue = deque([[src_id]])
        visited = {src_id}
        while queue:
            path = queue.popleft()
            curr = path[-1]
            if curr == target_id:
                return path[1] if len(path) > 1 else None
            for nb in adj.get(curr, []):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(path + [nb])
        return None

    def _handle_foreign_leader_contact(self, node: ProtocolNode, sender_id: int, foreign_leader_id: int):
        """Phase 13: Border node detects foreign network presence and forwards JOIN_REQUEST to its active leader."""
        if getattr(node, "_last_join_req_hop", 0) + 3 > self.hop:
            return
        node._last_join_req_hop = self.hop

        target_leader = node.leader_id
        if target_leader is None or not self.nodes.get(target_leader) or not self.nodes[target_leader].alive:
            return

        self.emit("join_request_initiated", {
            "border_node": node.id,
            "foreign_node": sender_id,
            "foreign_leader": foreign_leader_id,
            "target_leader": target_leader
        })
        self.emit("sim_log", {
            "message": f"MERGE: Border node #{node.id} detected foreign leader #{foreign_leader_id}. Emitting JOIN_REQUEST -> Leader #{target_leader}",
            "level": "info"
        })

        if node.id == target_leader:
            self._on_leader_join_request(node, sender_id, foreign_leader_id)
        else:
            next_hop = self._find_next_hop_toward(node.id, target_leader)
            if next_hop is not None:
                self._send_frame(
                    src=node.id,
                    dst=next_hop,
                    frame_type="JOIN_REQUEST",
                    payload={
                        "border_node": node.id,
                        "foreign_node": sender_id,
                        "foreign_leader": foreign_leader_id,
                        "target_leader": target_leader,
                        "hop_count": 0
                    }
                )

    def _on_leader_join_request(self, leader_node: ProtocolNode, border_node: int, foreign_leader: int):
        """Phase 13: Leader receives JOIN_REQUEST. If count >= threshold, issues RESIGNATION broadcast."""
        leader_node.join_request_count = getattr(leader_node, "join_request_count", 0) + 1
        resignation_threshold = getattr(self, "resignation_threshold", 1)

        self.emit("join_request_received_at_leader", {
            "leader_id": leader_node.id,
            "count": leader_node.join_request_count,
            "threshold": resignation_threshold,
            "border_node": border_node,
            "foreign_leader": foreign_leader
        })

        if leader_node.join_request_count >= resignation_threshold:
            former_leader_id = leader_node.id
            leader_node.mode = "PASSTHROUGH"
            leader_node.leader_id = None
            leader_node.join_request_count = 0

            self.emit("leader_resigned", {
                "former_leader": former_leader_id,
                "reason": "network_merge",
                "foreign_leader": foreign_leader,
                "hop": self.hop
            })
            self.emit("sim_log", {
                "message": f"Phase 13: Leader #{former_leader_id} received JOIN_REQUEST and issued RESIGNATION broadcast to merge with foreign network (Leader #{foreign_leader})!",
                "level": "warn"
            })

            # Broadcast RESIGNATION packet to neighbors
            for peer in leader_node.neighbour_list:
                p_pair = (min(leader_node.id, peer), max(leader_node.id, peer))
                if p_pair not in self.disabled_links and self.nodes.get(peer) and self.nodes[peer].alive:
                    self._send_frame(
                        src=leader_node.id,
                        dst=peer,
                        frame_type="RESIGNATION",
                        payload={"leader_id": former_leader_id, "reason": "network_merge"}
                    )

            surviving_leaders = [n for n in self.nodes.values() if n.alive and n.mode == "LEADER"]
            if not surviving_leaders:
                self._schedule_global_re_election()
            else:
                self.pending_global_re_election = True
                self.pending_re_election_hop = self.hop + 2

    def _schedule_global_re_election(self):
        """Schedule a global re-election across all connected nodes once leaders have yielded."""
        self.emit("sim_log", {
            "message": "Phase 13: Leaders yielded! Triggering GLOBAL_RE_ELECTION across merged network.",
            "level": "success"
        })
        self._trigger_re_election()

    def _trigger_component_election(self, component_nodes: List[ProtocolNode]):
        """Run Phase 2-8 election strictly within a specific connected component of nodes."""
        alive_nodes = [n for n in component_nodes if n.alive]
        if not alive_nodes:
            return

        comp_ids = {n.id for n in alive_nodes}
        self.emit("component_election_started", {
            "hop": self.hop,
            "nodes": sorted(list(comp_ids))
        })

        if len(alive_nodes) == 1:
            only = alive_nodes[0]
            only.mode = "LEADER"
            only.leader_id = only.id
            self.emit("leader_elected", {
                "leader_id": only.id,
                "battery": int(round(only.battery)),
                "score": only.internal_score,
                "hop": self.hop,
                "time_ms": self.sim_time_ms,
                "component": sorted(list(comp_ids))
            })
            self.emit("mode_change", {"node_id": only.id, "mode": "LEADER"})
            return

        for n in alive_nodes:
            valid_nb = []
            for p in self.adj_physical.get(n.id, []):
                pair = (min(n.id, p), max(n.id, p))
                if pair not in self.disabled_links and p in comp_ids and self.nodes[p].alive:
                    valid_nb.append(p)
            n.neighbour_list = valid_nb
            n.mode = "PASSTHROUGH"
            n.leader_id = None
            n.echo_count = 0
            n.timeout_started = False
            n.claim_timer = None
            n.window_timer = None
            n.fwd_mask.clear()
            n.election_start_hop = self.hop
            n.internal_score = int(round(n.battery)) + len(valid_nb)
            n.best_known_score = n.internal_score
            n.best_known_origin = n.id

        contenders = []
        for n in alive_nodes:
            nb_n = len(n.neighbour_list)
            odds = odds_permille(int(round(n.battery)), nb_n, self.max_adj_nodes)
            prob = (self.rng[n.id].next() * 1000) // PRNG_M
            if odds > prob:
                contenders.append(n)

        if not contenders:
            highest_n = max(alive_nodes, key=lambda x: (x.internal_score, x.id))
            contenders.append(highest_n)

        for n in contenders:
            n.mode = "ELECTION"
            n.election_start_hop = self.hop
            self.emit("mode_change", {"node_id": n.id, "mode": "ELECTION", "score": n.internal_score})
            if not n.neighbour_list:
                n.timeout_started = True
                n.claim_timer = self.hop + self.t_claim_hops
            else:
                for peer in n.neighbour_list:
                    if self.nodes[peer].alive:
                        self._send_frame(
                            src=n.id,
                            dst=peer,
                            frame_type="ELECTION",
                            payload={
                                "score": n.internal_score,
                                "origin": n.id,
                                "replayer": n.id,
                                "age": 0
                            }
                        )

    def _is_converged(self) -> bool:
        """Check if all connected components of alive nodes have converged to an elected leader."""
        comps = self.get_connected_components()
        if not comps:
            return False
        for comp in comps:
            leaders_in_comp = [nid for nid in comp if self.nodes[nid].mode == "LEADER"]
            if len(leaders_in_comp) != 1:
                return False
            comp_leader = leaders_in_comp[0]
            for nid in comp:
                if self.nodes[nid].leader_id != comp_leader and self.nodes[nid].mode != "LEADER":
                    return False
        return True

    # ------------------------------------------------------------- Fault injection
    def toggle_link(self, u: int, v: int, disable: Optional[bool] = None) -> bool:
        pair = (min(u, v), max(u, v))
        if pair not in self.links:
            return False
        if disable is None:
            if pair in self.disabled_links:
                self.disabled_links.remove(pair)
                self.partition_cut_links.discard(pair)
                state = False
            else:
                self.disabled_links.add(pair)
                self.partition_cut_links.add(pair)
                state = True
        elif disable:
            self.disabled_links.add(pair)
            self.partition_cut_links.add(pair)
            state = True
        else:
            self.disabled_links.discard(pair)
            self.partition_cut_links.discard(pair)
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

        if not nd.alive:
            self._handle_node_killed(nd)
        else:
            self._handle_node_revived(nd)

        return nd.alive

    def _handle_node_killed(self, nd: ProtocolNode):
        """Handle dynamic failure of a node at runtime (CFT max-consensus failover)."""
        nd.mode = "OFFLINE"
        nd.claim_timer = None
        nd.window_timer = None
        nd.echo_count = 0
        nd.timeout_started = False

        # Drop any pending in-flight packets addressed to or sent from this dead node
        surviving_pkts = []
        for pkt in self.in_flight:
            if pkt["src"] == nd.id or pkt["dst"] == nd.id:
                self.stats["DROPPED"] += 1
                self.stats["TOTAL"] += 1
                self.emit("frame_drop", {
                    "pkt_id": pkt["id"],
                    "src": pkt["src"],
                    "dst": pkt["dst"],
                    "type": pkt["type"],
                    "reason": "node_offline"
                })
            else:
                surviving_pkts.append(pkt)
        self.in_flight = surviving_pkts

        # Case 1: The killed node was the LEADER!
        if self.leader == nd.id:
            former_leader = self.leader
            self.leader = None
            self.status = "RUNNING"
            self.convergence_hop = None
            self.convergence_time_ms = None
            self.emit("leader_lost", {
                "former_leader": former_leader,
                "reason": "leader_killed",
                "hop": self.hop
            })
            self._trigger_re_election()
            self._ensure_loop_running()
        else:
            # Case 2: A non-leader node was killed
            # If an election is running and other nodes were deferring to this dead node,
            # clear the dead origin so surviving nodes don't deadlock!
            affected = False
            for other in self.nodes.values():
                if other.alive and other.best_known_origin == nd.id:
                    other.best_known_origin = other.id
                    other.best_known_score = other.internal_score
                    other.echo_count = 0
                    other.timeout_started = False
                    other.claim_timer = None
                    affected = True

            if affected and self.leader is None:
                self._trigger_re_election()
                self._ensure_loop_running()
            elif self.status in ("RUNNING", "CONVERGED"):
                self._ensure_loop_running()

    def _handle_node_revived(self, nd: ProtocolNode):
        """Handle recovery/reboot of a killed node."""
        nd.alive = True
        nd.fwd_mask.clear()
        nd.echo_count = 0
        nd.timeout_started = False
        nd.claim_timer = None
        nd.window_timer = None

        if self.leader is not None and self.nodes.get(self.leader, None) and self.nodes[self.leader].alive:
            nd.mode = "PASSTHROUGH"
            nd.leader_id = self.leader
            nd.last_hb_hop = self.hop
            self.emit("mode_change", {"node_id": nd.id, "mode": "PASSTHROUGH", "reason": "node_revived"})
        else:
            nd.mode = "DISCOVERY"
            self.emit("mode_change", {"node_id": nd.id, "mode": "DISCOVERY", "reason": "node_revived"})
            self._trigger_re_election()

        self._ensure_loop_running()

    def _trigger_re_election(self):
        """Phase 2-8 Re-election across all connected components of surviving nodes."""
        self.leader = None
        self.status = "RUNNING"
        self.convergence_hop = None
        self.convergence_time_ms = None

        alive_nodes = [n for n in self.nodes.values() if n.alive]
        if not alive_nodes:
            self.emit("sim_log", {"message": "All nodes offline, no leader possible", "level": "warn"})
            return

        comps = self.get_connected_components()
        self.emit("re_election_started", {
            "hop": self.hop,
            "alive_nodes": [n.id for n in alive_nodes],
            "components": len(comps)
        })

        for comp in comps:
            comp_nodes = [self.nodes[nid] for nid in comp if self.nodes[nid].alive]
            self._trigger_component_election(comp_nodes)

    def _ensure_loop_running(self):
        """Ensure the background simulation loop is actively stepping forward."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self.status not in ("PAUSED", "STOPPED"):
            if self._async_task is None or self._async_task.done():
                self._async_task = loop.create_task(self.run_loop())

    def _consume_energy(self, node_id: int, amount: float, reason: str = ""):
        """Deduct energy from node according to dynamic battery model."""
        if not self.battery_drain_enabled or self.battery_drain_rate <= 0:
            return
        nd = self.nodes.get(node_id)
        if not nd or not nd.alive:
            return

        old_int = int(round(nd.battery))
        nd.battery = max(0.0, nd.battery - (amount * self.battery_drain_rate))
        new_int = int(round(nd.battery))
        nb_n = len(nd.neighbour_list)
        nd.internal_score = max(0, new_int + nb_n)

        # Check for battery exhaustion -> Node shuts down!
        if nd.battery <= 0.0:
            nd.battery = 0.0
            nd.alive = False
            nd.mode = "OFFLINE"
            self.emit("node_battery", {
                "node_id": node_id,
                "battery": 0,
                "score": nd.internal_score,
                "alive": False
            })
            self.emit("node_alive", {"node_id": node_id, "alive": False})
            self.emit("node_battery_depleted", {
                "node_id": node_id,
                "hop": self.hop
            })
            self.emit("sim_log", {
                "message": f"CRITICAL: Node #{node_id} battery exhausted (0%)! Powering down.",
                "level": "error"
            })
            self._handle_node_killed(nd)
            return

        # Check for Leader Low-Battery Handover / Resignation
        if nd.id == self.leader and nd.battery <= self.leader_resignation_threshold:
            healthier = [o for o in self.nodes.values() if o.alive and o.id != nd.id and o.battery > (self.leader_resignation_threshold + 5)]
            if healthier:
                former = self.leader
                self.leader = None
                nd.mode = "PASSTHROUGH"
                self.emit("leader_resigned", {
                    "former_leader": former,
                    "battery": new_int,
                    "hop": self.hop,
                    "reason": "low_battery_drain"
                })
                self.emit("sim_log", {
                    "message": f"LEADER HANDOVER: Leader Node #{former} battery low ({new_int}%)! Resigning leadership for consensus re-election.",
                    "level": "warn"
                })
                self._trigger_re_election()

        if new_int != old_int:
            self.emit("node_battery", {
                "node_id": node_id,
                "battery": new_int,
                "score": nd.internal_score,
                "alive": nd.alive
            })

    def set_battery_drain(self, enabled: Optional[bool] = None, rate: Optional[float] = None,
                          node_tx_cost: Optional[float] = None, leader_tx_cost: Optional[float] = None):
        """Configure dynamic battery drain toggle, speed multiplier, and per-packet TX loss rates."""
        if enabled is not None:
            self.battery_drain_enabled = bool(enabled)
        if rate is not None:
            self.battery_drain_rate = max(0.0, float(rate))
        if node_tx_cost is not None:
            self.node_tx_cost = max(0.0, float(node_tx_cost))
            self.tx_cost = self.node_tx_cost
        if leader_tx_cost is not None:
            self.leader_tx_cost = max(0.0, float(leader_tx_cost))
        self.emit("battery_drain_config", {
            "enabled": self.battery_drain_enabled,
            "rate": self.battery_drain_rate,
            "node_tx_cost": self.node_tx_cost,
            "leader_tx_cost": self.leader_tx_cost
        })

    def recharge_all_nodes(self, battery: float = 100.0):
        """Instantly recharge all nodes to full capacity and revive offline nodes."""
        for nid, nd in self.nodes.items():
            nd.battery = float(battery)
            nd.internal_score = max(0, int(round(nd.battery)) + len(nd.neighbour_list))
            was_dead = not nd.alive
            if was_dead and battery > 0:
                nd.alive = True
                self.emit("node_alive", {"node_id": nid, "alive": True})
                self._handle_node_revived(nd)
            self.emit("node_battery", {
                "node_id": nid,
                "battery": int(round(nd.battery)),
                "score": nd.internal_score,
                "alive": nd.alive
            })
        self.emit("sim_log", {
            "message": f"All nodes recharged to {int(battery)}% capacity",
            "level": "success"
        })

    def set_node_battery(self, node_id: int, battery: float):
        """Set specific node's battery percentage directly (with failover/revival handling)."""
        if node_id not in self.nodes:
            return
        nd = self.nodes[node_id]
        nd.battery = max(0.0, min(100.0, float(battery)))
        nb_n = len(nd.neighbour_list)
        nd.internal_score = max(0, int(round(nd.battery)) + nb_n)

        if nd.battery <= 0.0:
            if nd.alive:
                nd.alive = False
                nd.mode = "OFFLINE"
                self.emit("node_battery", {
                    "node_id": node_id,
                    "battery": 0,
                    "score": nd.internal_score,
                    "alive": False
                })
                self.emit("node_alive", {"node_id": node_id, "alive": False})
                self.emit("node_battery_depleted", {
                    "node_id": node_id,
                    "hop": self.hop
                })
                self._handle_node_killed(nd)
                return
        else:
            if not nd.alive:
                nd.alive = True
                self.emit("node_alive", {"node_id": node_id, "alive": True})
                self._handle_node_revived(nd)

        # Check if leader was drained below critical threshold
        if nd.id == self.leader and nd.battery <= self.leader_resignation_threshold:
            healthier = [o for o in self.nodes.values() if o.alive and o.id != nd.id and o.battery > (self.leader_resignation_threshold + 5)]
            if healthier:
                former = self.leader
                self.leader = None
                nd.mode = "PASSTHROUGH"
                self.emit("leader_resigned", {
                    "former_leader": former,
                    "battery": int(round(nd.battery)),
                    "hop": self.hop,
                    "reason": "manual_override_low_battery"
                })
                self._trigger_re_election()

        self.emit("node_battery", {
            "node_id": node_id,
            "battery": int(round(nd.battery)),
            "score": nd.internal_score,
            "alive": nd.alive
        })

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
            orig_node = next((x for x in self.raw_topology.get("nodes", []) if x.get("id") == nid), None)
            if orig_node and "battery" in orig_node:
                nd.battery = float(orig_node["battery"])
            else:
                nd.battery = float(DEFAULT_BATTERIES[(nid - 1) % len(DEFAULT_BATTERIES)])
            nd.alive = True
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
            nd.internal_score = int(round(nd.battery))

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
        if src in self.nodes and not self.nodes[src].alive:
            return

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

        # Consume energy on transmitter: leader nodes vs general nodes
        is_leader = (src == self.leader) or (self.nodes.get(src) is not None and self.nodes[src].mode == "LEADER")
        tx_drain = self.leader_tx_cost if is_leader else self.node_tx_cost
        self._consume_energy(src, tx_drain, f"tx_{frame_type.lower()}")

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
                self.stats["DROPPED"] += 1
                self.stats["TOTAL"] += 1
                self.emit("frame_drop", {
                    "pkt_id": pkt["id"],
                    "src": src,
                    "dst": dst,
                    "type": ftype,
                    "reason": "node_offline"
                })
                continue

            dest_node = self.nodes[dst]

            # Consume energy on receiver
            self._consume_energy(dst, self.rx_cost, f"rx_{ftype.lower()}")

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
            elif ftype == "FIND_LEADER":
                self._handle_find_leader(dest_node, src, payload)
            elif ftype == "LEADER_ACK":
                self._handle_leader_ack(dest_node, src, payload)
            elif ftype == "JOIN_REQUEST":
                self._handle_join_request(dest_node, src, payload)
            elif ftype == "RESIGNATION":
                self._handle_resignation(dest_node, src, payload)

        # Handle Election frames after discovery phase
        for dest_node, src, payload in delivered_election_frames:
            self._handle_election(dest_node, src, payload)

        # 2. Check Discovery completion -> transition to Phase 2 Mode Decision
        if self.hop == 2:
            self._evaluate_mode_decisions()

        # Check pending global re-election after leader resignations
        if getattr(self, "pending_global_re_election", False) and self.hop >= getattr(self, "pending_re_election_hop", 0):
            self.pending_global_re_election = False
            self._schedule_global_re_election()

        # 3. Check Timers (T_claim expiry -> CLAIM; T_window expiry -> LEADER)
        self._check_node_timers()

        # 4. Periodic Heartbeats for all active leaders & leader failure check
        active_leaders = [n for n in self.nodes.values() if n.alive and n.mode == "LEADER"]
        for ldr in active_leaders:
            if not ldr.alive:
                self.emit("leader_lost", {"former_leader": ldr.id, "reason": "leader_offline", "hop": self.hop})
                self._trigger_re_election()
            elif self.hop % self.heartbeat_interval_hops == 0:
                ldr.heartbeat_counter += 1
                for peer in ldr.neighbour_list:
                    pair = (min(ldr.id, peer), max(ldr.id, peer))
                    if pair not in self.disabled_links and self.nodes.get(peer) and self.nodes[peer].alive:
                        self._send_frame(
                            src=ldr.id,
                            dst=peer,
                            frame_type="HEARTBEAT",
                            payload={"leader_id": ldr.id, "epoch": 1, "count": ldr.heartbeat_counter}
                        )

        # 5. Baseline idle drain per hop across all alive nodes
        if self.battery_drain_enabled and self.battery_drain_rate > 0:
            for nid, nd in list(self.nodes.items()):
                if nd.alive:
                    self._consume_energy(nid, self.idle_cost, "idle")

        self.emit("step_complete", {
            "hop": self.hop,
            "sim_time_ms": self.sim_time_ms,
            "in_flight": len(self.in_flight),
            "leader": self.leader,
            "leaders": self.leaders,
            "is_partitioned": len(self.get_active_partitions()) > 1,
            "stats": self.stats,
            "node_batteries": {nid: int(round(nd.battery)) for nid, nd in self.nodes.items()}
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
            nd.election_start_hop = self.hop

            odds = odds_permille(nd.battery, nb_n, self.max_adj_nodes)
            prob = (self.rng[nid].next() * 1000) // PRNG_M

            if odds > prob:
                nd.mode = "ELECTION"
                self.emit("mode_change", {"node_id": nid, "mode": "ELECTION", "score": nd.internal_score})
                # Broadcast election packet to all authenticated neighbours
                for peer in nd.neighbour_list:
                    if self.nodes.get(peer, None) and self.nodes[peer].alive:
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

        # Ignore frames from dead origin
        if origin in self.nodes and not self.nodes[origin].alive:
            return

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
            if peer != replayer and peer != sender_id and self.nodes.get(peer, None) and self.nodes[peer].alive:
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

            # Uncontested candidacy timer (allows non-cyclic networks & partitioned lines to converge)
            if nd.mode == "ELECTION" and nd.best_known_origin == nd.id and not nd.timeout_started:
                if (self.hop - getattr(nd, "election_start_hop", 0)) >= 3:
                    nd.timeout_started = True
                    nd.claim_timer = self.hop + self.t_claim_hops
                    self.emit("claim_timer_armed", {
                        "node_id": nid,
                        "fires_at_hop": nd.claim_timer
                    })

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
                        if self.nodes.get(peer, None) and self.nodes[peer].alive:
                            self._send_frame(
                                src=nid,
                                dst=peer,
                                frame_type="CLAIM",
                                payload={"origin": nid, "score": nd.best_known_score}
                            )
                else:
                    if nd.best_known_origin in self.nodes and not self.nodes[nd.best_known_origin].alive:
                        self._trigger_re_election()
                        return
                    nd.mode = "PASSTHROUGH"

            # Check Window Timer -> Transition to LEADER!
            if nd.window_timer is not None and self.hop >= nd.window_timer:
                nd.window_timer = None
                if nd.best_known_origin == nd.id:
                    nd.mode = "LEADER"
                    nd.leader_id = nd.id

                    # Propagate leader adoption to nodes in this component
                    comps = self.get_connected_components()
                    for c in comps:
                        if nd.id in c:
                            for nid_in_c in c:
                                if self.nodes[nid_in_c].alive and self.nodes[nid_in_c].mode != "LEADER":
                                    self.nodes[nid_in_c].leader_id = nd.id
                            break

                    if self._is_converged():
                        self.status = "CONVERGED"
                        self.convergence_hop = self.hop
                        self.convergence_time_ms = self.sim_time_ms
                    else:
                        self.status = "RUNNING"

                    self.leader = max(self.leaders, key=lambda x: (self.nodes[x].best_known_score, x)) if self.leaders else nd.id

                    self.emit("leader_elected", {
                        "leader_id": nd.id,
                        "battery": int(round(nd.battery)),
                        "score": nd.best_known_score,
                        "hop": self.hop,
                        "time_ms": self.sim_time_ms,
                        "leaders": self.leaders,
                        "is_partitioned": len(self.get_active_partitions()) > 1
                    })
                    self.emit("mode_change", {"node_id": nid, "mode": "LEADER"})

    def _handle_claim(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        origin = payload["origin"]
        score = payload["score"]

        # Reject claim from dead origin
        if origin in self.nodes and not self.nodes[origin].alive:
            return

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
                p_pair = (min(node.id, peer), max(node.id, peer))
                if p_pair not in self.disabled_links and peer != sender_id and self.nodes.get(peer, None) and self.nodes[peer].alive:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="CLAIM",
                        payload=payload
                    )

    def _handle_heartbeat(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        leader_id = payload["leader_id"]
        if leader_id in self.nodes and not self.nodes[leader_id].alive:
            return

        # Phase 14 / Cross-Network Filtering:
        # A node that hears a heartbeat carrying a Leader ID different from its own
        # recognizes the sender as belonging to a foreign network and initiates Phase 13 merge.
        if node.leader_id is not None and node.leader_id != leader_id and node.mode != "DISCOVERY":
            self.emit("foreign_presence_detected", {
                "node_id": node.id,
                "local_leader": node.leader_id,
                "foreign_leader": leader_id,
                "sender_id": sender_id
            })
            self._handle_foreign_leader_contact(node, sender_id, leader_id)
            return

        node.leader_id = leader_id
        node.last_hb_hop = self.hop
        if node.mode != "LEADER":
            node.mode = "PASSTHROUGH"

        # Forward heartbeat to neighbors within the same component
        pair = (leader_id, sender_id)
        if pair not in node.fwd_mask:
            node.fwd_mask.add(pair)
            for peer in node.neighbour_list:
                p_pair = (min(node.id, peer), max(node.id, peer))
                if p_pair not in self.disabled_links and peer != sender_id and self.nodes.get(peer, None) and self.nodes[peer].alive:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="HEARTBEAT",
                        payload=payload
                    )

    # ------------------------------------------------------------- Phase 12 & 13 Frame Handlers
    def _handle_find_leader(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        requester = payload.get("requester")
        expected_leader = payload.get("expected_leader")

        if node.id == expected_leader or (node.leader_id == expected_leader and self.nodes.get(expected_leader) and self.nodes[expected_leader].alive):
            # Leader is alive and reachable in this partition! Send LEADER_ACK back
            next_hop = self._find_next_hop_toward(node.id, requester)
            if next_hop is not None:
                self._send_frame(
                    src=node.id,
                    dst=next_hop,
                    frame_type="LEADER_ACK",
                    payload={"requester": requester, "leader_id": expected_leader, "score": node.best_known_score}
                )
            return

        # Forward FIND_LEADER to other neighbors if not visited
        pair = (f"find_ldr_{requester}", sender_id)
        if pair not in node.fwd_mask:
            node.fwd_mask.add(pair)
            for peer in node.neighbour_list:
                p_pair = (min(node.id, peer), max(node.id, peer))
                if p_pair not in self.disabled_links and peer != sender_id and self.nodes.get(peer) and self.nodes[peer].alive:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="FIND_LEADER",
                        payload=payload
                    )

    def _handle_leader_ack(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        requester = payload.get("requester")
        leader_id = payload.get("leader_id")

        if node.id == requester:
            node.leader_id = leader_id
            self.emit("leader_confirmed", {
                "node_id": node.id,
                "leader_id": leader_id,
                "hop": self.hop
            })
            self.emit("sim_log", {
                "message": f"Phase 12: Node #{node.id} received LEADER_ACK. Leader #{leader_id} confirmed intact.",
                "level": "info"
            })
        else:
            next_hop = self._find_next_hop_toward(node.id, requester)
            if next_hop is not None and next_hop != sender_id:
                self._send_frame(
                    src=node.id,
                    dst=next_hop,
                    frame_type="LEADER_ACK",
                    payload=payload
                )

    def _handle_join_request(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        target_leader = payload.get("target_leader")
        if node.id == target_leader:
            self._on_leader_join_request(node, payload.get("border_node"), payload.get("foreign_leader"))
        else:
            next_hop = self._find_next_hop_toward(node.id, target_leader)
            if next_hop is not None and next_hop != sender_id:
                payload["hop_count"] = payload.get("hop_count", 0) + 1
                self._send_frame(
                    src=node.id,
                    dst=next_hop,
                    frame_type="JOIN_REQUEST",
                    payload=payload
                )

    def _handle_resignation(self, node: ProtocolNode, sender_id: int, payload: Dict[str, Any]):
        former = payload.get("leader_id")
        if node.leader_id == former:
            node.leader_id = None
            if node.mode in ("LEADER", "CLAIMING", "ELECTION"):
                node.mode = "PASSTHROUGH"

        pair = (f"resignation_{former}", sender_id)
        if pair not in node.fwd_mask:
            node.fwd_mask.add(pair)
            for peer in node.neighbour_list:
                p_pair = (min(node.id, peer), max(node.id, peer))
                if p_pair not in self.disabled_links and peer != sender_id and self.nodes.get(peer) and self.nodes[peer].alive:
                    self._send_frame(
                        src=node.id,
                        dst=peer,
                        frame_type="RESIGNATION",
                        payload=payload
                    )

    # ------------------------------------------------------------- Async runner
    async def run_loop(self):
        try:
            while self.status in ("RUNNING", "CONVERGED"):
                self.step()
                delay = max(0.02, self.step_delay / max(0.1, self.speed))
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass

    def start_async(self):
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
        self.start_sim()
        self._async_task = asyncio.create_task(self.run_loop())

    def pause(self):
        if self.status in ("RUNNING", "CONVERGED"):
            self._prev_status = self.status
            self.status = "PAUSED"
            if self._async_task:
                self._async_task.cancel()
            self.emit("sim_pause", {"status": "PAUSED"})

    def resume(self):
        if self.status == "PAUSED":
            self.status = getattr(self, "_prev_status", "RUNNING")
            self._async_task = asyncio.create_task(self.run_loop())
            self.emit("sim_resume", {"status": self.status})

    def stop(self):
        self.status = "STOPPED"
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
        self.emit("sim_stop", {"status": "STOPPED"})
