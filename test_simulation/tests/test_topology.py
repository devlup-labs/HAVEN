"""
Tests for sim/gen_topology.py.

Verifies:
1. Generator is deterministic given fixed seed.
2. Generated graphs are fully connected.
3. Every link only connects pairs that share >= 1 space.
4. Generated degrees respect max_adj_nodes.
5. Ring topology generator works for N=3, 5, 10.
"""

import json
from pathlib import Path
import pytest

try:
    from test_simulation.gen_topology import generate_topology, is_connected
    from test_simulation.turboblom import assign_spaces
except ModuleNotFoundError:
    try:
        from sim.gen_topology import generate_topology, is_connected
        from sim.turboblom import assign_spaces
    except ModuleNotFoundError:
        from gen_topology import generate_topology, is_connected
        from turboblom import assign_spaces


def test_topology_deterministic():
    t1 = generate_topology(num_nodes=10, seed=12345)
    t2 = generate_topology(num_nodes=10, seed=12345)
    assert t1 == t2


def test_topology_seed_variation():
    t1 = generate_topology(num_nodes=10, seed=111)
    t2 = generate_topology(num_nodes=10, seed=222)
    assert t1["links"] != t2["links"]


@pytest.mark.parametrize("n", [3, 5, 10, 15, 20])
def test_topology_connectivity(n):
    topo = generate_topology(num_nodes=n, target_avg_degree=4.5, seed=42 + n)
    edges = [(link["a"], link["b"]) for link in topo["links"]]
    assert is_connected(n, edges)


@pytest.mark.parametrize("n", [5, 10, 15])
def test_all_links_share_spaces(n):
    topo = generate_topology(num_nodes=n, m_spaces=12, k_spaces=5, seed=99)
    spaces_map = {node["id"]: set(node["spaces"]) for node in topo["nodes"]}

    for link in topo["links"]:
        u, v = link["a"], link["b"]
        shared = spaces_map[u] & spaces_map[v]
        assert len(shared) >= 1, f"Link between {u} and {v} has no shared spaces!"


def test_respects_max_adj_nodes():
    topo = generate_topology(num_nodes=12, target_avg_degree=4.0, max_adj_nodes=6, seed=777)
    deg = {i: 0 for i in range(1, 13)}
    for link in topo["links"]:
        deg[link["a"]] += 1
        deg[link["b"]] += 1
    assert max(deg.values()) <= 6


@pytest.mark.parametrize("n", [3, 5, 10])
def test_ring_topology_generation(n):
    topo = generate_topology(num_nodes=n, graph_type="ring")
    assert len(topo["links"]) == n
    deg = {i: 0 for i in range(1, n + 1)}
    for link in topo["links"]:
        deg[link["a"]] += 1
        deg[link["b"]] += 1
    assert all(d == 2 for d in deg.values())


def test_node_spaces_match_turboblom():
    topo = generate_topology(num_nodes=8, m_spaces=12, k_spaces=5, seed=1)
    k_master = bytes(range(32))
    for node in topo["nodes"]:
        expected = assign_spaces(node["id"], 5, 12, k_master)
        assert node["spaces"] == expected
