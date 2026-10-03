#!/usr/bin/env python3
"""
HAVEN topology generator.

Generates a single-source-of-truth topology.json for ns-3 co-simulation and
Renode multi-node ring/mesh launcher.

Guarantees:
1. Links only connect pairs sharing >= 1 space (compute_K_AB feasibility).
2. Connected component check: graph is connected (single leader possible).
3. Max degree does not exceed max_adj_nodes.
4. Deterministic given --seed.
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from turboblom import assign_spaces

# 20-node battery table mirroring firmware/src/provision.c
DEFAULT_BATTERY_TABLE = [
    100, 80, 60, 40, 20, 90, 70, 50, 30, 10,
     95, 75, 55, 35, 15, 85, 65, 45, 25,  5
]


def is_connected(n, edges):
    if n <= 1:
        return True
    adj = {i: [] for i in range(1, n + 1)}
    for u, v in edges:
        adj[u].append(v)
        adj[v].append(u)
    visited = set()
    stack = [1]
    while stack:
        cur = stack.pop()
        if cur not in visited:
            visited.add(cur)
            stack.extend(adj[cur])
    return len(visited) == n


def generate_topology(num_nodes=12, m_spaces=12, k_spaces=5,
                      target_avg_degree=5.0, graph_type="erdos-renyi",
                      loss_pct=0.0, delay_ms=20, bw_bps=9600,
                      seed=20250103, echo_threshold=2, max_adj_nodes=None):
    rng = random.Random(seed)
    k_master = bytes(range(32))

    node_spaces = {
        i: assign_spaces(i, k_spaces, m_spaces, k_master)
        for i in range(1, num_nodes + 1)
    }

    # Feasible candidate pairs that share at least one space
    feasible_pairs = []
    for i in range(1, num_nodes + 1):
        for j in range(i + 1, num_nodes + 1):
            if set(node_spaces[i]) & set(node_spaces[j]):
                feasible_pairs.append((i, j))

    edges = []
    if graph_type == "ring":
        # Create a cycle over 1..num_nodes (or check feasibility)
        for i in range(1, num_nodes):
            edges.append((i, i + 1))
        edges.append((num_nodes, 1))

        # Verify all ring edges are feasible
        for u, v in edges:
            if not (set(node_spaces[u]) & set(node_spaces[v])):
                raise ValueError(
                    f"Ring edge ({u}, {v}) shares no spaces at m={m_spaces}, k={k_spaces}!"
                )
    else:
        # Erdos-Renyi or general random graph
        # target_edges = (num_nodes * target_avg_degree) / 2
        p = min(1.0, (target_avg_degree) / max(1, num_nodes - 1))

        attempts = 0
        max_attempts = 200
        found = False

        while attempts < max_attempts:
            attempts += 1
            cand_edges = []
            for u, v in feasible_pairs:
                if rng.random() < p:
                    cand_edges.append((u, v))

            # Ensure minimum spanning tree to guarantee connectivity if needed
            if not is_connected(num_nodes, cand_edges):
                # Add random feasible edges until connected
                shuffled_feas = list(feasible_pairs)
                rng.shuffle(shuffled_feas)
                for u, v in shuffled_feas:
                    if (u, v) not in cand_edges:
                        cand_edges.append((u, v))
                        if is_connected(num_nodes, cand_edges):
                            break

            # Degree check
            deg = {i: 0 for i in range(1, num_nodes + 1)}
            for u, v in cand_edges:
                deg[u] += 1
                deg[v] += 1

            max_deg = max(deg.values()) if deg else 0
            if max_adj_nodes is not None and max_deg > max_adj_nodes:
                continue

            if is_connected(num_nodes, cand_edges):
                edges = cand_edges
                found = True
                break

        if not found:
            raise RuntimeError(
                f"Failed to generate connected graph with max_adj_nodes<={max_adj_nodes} after {max_attempts} attempts."
            )

    deg = {i: 0 for i in range(1, num_nodes + 1)}
    for u, v in edges:
        deg[u] += 1
        deg[v] += 1
    actual_max_deg = max(deg.values()) if deg else 0
    effective_max_adj = max_adj_nodes if max_adj_nodes is not None else max(actual_max_deg, 2)

    # Spatial layout (for visualization / coordinates)
    nodes_data = []
    for i in range(1, num_nodes + 1):
        angle = (2.0 * math.pi * (i - 1)) / num_nodes
        x = round(500.0 + 350.0 * math.cos(angle), 1)
        y = round(500.0 + 350.0 * math.sin(angle), 1)
        b_val = (
            DEFAULT_BATTERY_TABLE[i - 1]
            if i <= len(DEFAULT_BATTERY_TABLE)
            else max(1, 100 - i * 4)
        )
        nodes_data.append({
            "id": i,
            "battery": b_val,
            "spaces": node_spaces[i],
            "x": x,
            "y": y
        })

    links_data = []
    for u, v in sorted(edges):
        links_data.append({
            "a": u,
            "b": v,
            "loss_pct": float(loss_pct),
            "delay_ms": int(delay_ms),
            "bw_bps": int(bw_bps)
        })

    actual_avg_deg = (2.0 * len(edges)) / num_nodes

    return {
        "version": 1,
        "meta": {
            "num_nodes": num_nodes,
            "seed": seed,
            "m_spaces": m_spaces,
            "k_spaces": k_spaces,
            "echo_threshold": echo_threshold,
            "max_adj_nodes": effective_max_adj,
            "generator": "Ring" if graph_type == "ring" else "Erdos-Renyi",
            "target_avg_degree": target_avg_degree,
            "actual_avg_degree": round(actual_avg_deg, 2),
            "actual_max_degree": actual_max_deg,
            "total_links": len(links_data)
        },
        "nodes": nodes_data,
        "links": links_data
    }


def main():
    parser = argparse.ArgumentParser(description="HAVEN topology generator")
    parser.add_argument("--nodes", type=int, default=12, help="number of nodes")
    parser.add_argument("--m", type=int, default=12, help="total spaces (m)")
    parser.add_argument("--k", type=int, default=5, help="spaces per node (k)")
    parser.add_argument("--avg-degree", type=float, default=5.0, help="target average degree")
    parser.add_argument("--type", choices=["erdos-renyi", "ring"], default="erdos-renyi", help="graph type")
    parser.add_argument("--loss-pct", type=float, default=0.0, help="per-link packet loss percentage")
    parser.add_argument("--delay-ms", type=int, default=20, help="per-link hop delay in ms")
    parser.add_argument("--bw-bps", type=int, default=9600, help="per-link bandwidth in bps")
    parser.add_argument("--seed", type=int, default=20250103, help="random seed")
    parser.add_argument("--echo-threshold", type=int, default=2, help="HAVEN echo threshold")
    parser.add_argument("--max-adj-nodes", type=int, default=None, help="max adjacent nodes limit")
    parser.add_argument("--out", type=str, default="topology.json", help="output file path")

    args = parser.parse_args()

    topo = generate_topology(
        num_nodes=args.nodes,
        m_spaces=args.m,
        k_spaces=args.k,
        target_avg_degree=args.avg_degree,
        graph_type=args.type,
        loss_pct=args.loss_pct,
        delay_ms=args.delay_ms,
        bw_bps=args.bw_bps,
        seed=args.seed,
        echo_threshold=args.echo_threshold,
        max_adj_nodes=args.max_adj_nodes
    )

    out_path = Path(args.out)
    out_path.write_text(json.dumps(topo, indent=2) + "\n")
    print(f"Wrote topology to {out_path} ({args.nodes} nodes, {len(topo['links'])} links, "
          f"avg deg={topo['meta']['actual_avg_degree']}, max deg={topo['meta']['actual_max_degree']})")


if __name__ == "__main__":
    main()
