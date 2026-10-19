#!/usr/bin/env python3
"""
Compute a valid ring order for the HAVEN firmware from the shared-space graph.

Two nodes can only become neighbours if their provisioned spaces intersect:
compute_K_AB() returns None otherwise, and firmware on_discovery() drops the
peer. At the default m=50, k=5 that happens for roughly 58% of node pairs, so
a ring wired in numeric id order is usually impossible -- 5 of the 10
id-adjacent pairs share no space.

A ring order must therefore be a Hamiltonian cycle of the shared-space graph.
This script finds one (exactly, by backtracking; N is at most 10 so the search
is instant) and prints it ready to paste into haven_ring.conf.

Usage:
    ./sim/compute_ring_order.py                # default m=50 k=5, nodes 1..10
    ./sim/compute_ring_order.py --nodes 3      # cycle over the first 3 nodes
    ./sim/compute_ring_order.py --m 20 --k 10
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from turboblom import assign_spaces, compute_K_AB, generate_key_matrix


def build_graph(ids, k, m, k_master):
    matrix = generate_key_matrix(m, k_master)
    spaces = {i: assign_spaces(i, k, m, k_master) for i in ids}
    adj = {i: set() for i in ids}
    for a in ids:
        for b in ids:
            if a >= b:
                continue
            if compute_K_AB(a, b, matrix, spaces[a], spaces[b]) is not None:
                adj[a].add(b)
                adj[b].add(a)
    return spaces, adj


def hamiltonian(adj, start):
    """Backtracking search for a cycle through every node, starting at `start`."""
    nodes = sorted(adj)
    path = [start]
    used = {start}

    def extend():
        # A cycle is only closable if the current endpoint has an unvisited
        # neighbour and the start still has an unvisited neighbour.
        if len(path) == len(nodes):
            return start in adj[path[-1]]
        for nxt in sorted(adj[path[-1]]):
            if nxt in used:
                continue
            used.add(nxt)
            path.append(nxt)
            if extend():
                return True
            used.discard(nxt)
            path.pop()
        return False

    if not any(start in adj[n] for n in nodes if n != start):
        return None
    return path if extend() else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nodes", type=int, default=10, help="number of nodes (default 10)")
    ap.add_argument("--k", type=int, default=5, help="spaces per node (default 5)")
    ap.add_argument("--m", type=int, default=12, help="total spaces (default 12)")
    args = ap.parse_args()

    if not 3 <= args.nodes <= 20:
        sys.exit("error: --nodes must be between 3 and 20")

    k_master = bytes(range(32))
    ids = list(range(1, args.nodes + 1))
    spaces, adj = build_graph(ids, args.k, args.m, k_master)

    order = None
    for start in ids:
        order = hamiltonian(adj, start)
        if order:
            break

    for i in ids:
        print(f"  node {i:>2}  spaces {spaces[i]}  links to {sorted(adj[i])}")

    if not order:
        print(f"\nNo Hamiltonian cycle exists for k={args.k}, m={args.m}, "
              f"N={args.nodes}.")
        print("k must grow with m; try a smaller ring or a larger k.")
        return 1

    print(f"\nValid ring order: {' '.join(str(i) for i in order)}")
    print(f'Paste into haven_ring.conf:\nRING_ORDER="{" ".join(str(i) for i in order)}"')

    broken = [(i, j) for i in range(1, args.nodes + 1)
              for j in [i + 1 if i < args.nodes else 1]
              if j not in adj[i]]
    print(f"\nFor comparison, a numeric id-ordered ring would break "
          f"{len(broken)} of {args.nodes} edges.")
    return 0


if __name__ == "__main__":
    sys.exit(main())