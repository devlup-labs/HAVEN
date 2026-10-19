import pytest
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "test_simulation") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "test_simulation"))
if str(ROOT_DIR / "sim") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "sim"))

from gui.haven_sim_engine import HavenSimEngine
try:
    from test_simulation.gen_topology import generate_topology
    from test_simulation.turboblom import assign_spaces
except ModuleNotFoundError:
    try:
        from sim.gen_topology import generate_topology
        from sim.turboblom import assign_spaces
    except ModuleNotFoundError:
        from gen_topology import generate_topology
        from turboblom import assign_spaces

K_MASTER = bytes(range(32))


def create_dual_ring_topology():
    """Create an 8-node dual ring topology with bridge links (4,5) and (8,1) initially disabled."""
    nodes = []
    # Ring A: 1..4 (left), Ring B: 5..8 (right)
    batt = [100, 80, 60, 40, 70, 90, 50, 30]
    for i in range(1, 9):
        nodes.append({
            "id": i,
            "battery": batt[i - 1],
            "spaces": assign_spaces(i, 5, 12, K_MASTER),
            "x": 280.0 if i <= 4 else 720.0,
            "y": 500.0
        })

    # Internal ring edges + crossing bridge links
    links = [
        {"a": 1, "b": 2, "delay_ms": 20, "loss_pct": 0},
        {"a": 2, "b": 3, "delay_ms": 20, "loss_pct": 0},
        {"a": 3, "b": 4, "delay_ms": 20, "loss_pct": 0},
        {"a": 4, "b": 1, "delay_ms": 20, "loss_pct": 0},
        {"a": 5, "b": 6, "delay_ms": 20, "loss_pct": 0},
        {"a": 6, "b": 7, "delay_ms": 20, "loss_pct": 0},
        {"a": 7, "b": 8, "delay_ms": 20, "loss_pct": 0},
        {"a": 8, "b": 5, "delay_ms": 20, "loss_pct": 0},
        {"a": 2, "b": 5, "delay_ms": 20, "loss_pct": 0, "disabled": True},
        {"a": 3, "b": 8, "delay_ms": 20, "loss_pct": 0, "disabled": True},
    ]

    return {
        "meta": {
            "m_spaces": 12,
            "k_spaces": 5,
            "echo_threshold": 2,
            "default_bridge_links": [[2, 5], [3, 8]]
        },
        "nodes": nodes,
        "links": links
    }


def test_split_and_independent_leader_election():
    """Test splitting an 8-node ring into two networks, each electing its own leader."""
    topo = generate_topology(num_nodes=8, graph_type="ring", loss_pct=0.0)
    engine = HavenSimEngine(topo)
    engine.start_sim()

    # Run until baseline unified election converges
    for _ in range(30):
        engine.step()
        if engine.status == "CONVERGED":
            break

    assert engine.status == "CONVERGED"
    original_leader = engine.leader
    assert original_leader is not None
    assert len(engine.leaders) == 1

    # Now split the network into two 4-node partitions: [1, 2, 3, 4] and [5, 6, 7, 8]
    split_res = engine.split_network()
    assert split_res["success"] is True
    assert len(split_res["partitions"]) == 2

    # Step simulation to let Phase 12 FIND_LEADER packets propagate and local re-election converge
    for _ in range(30):
        engine.step()
        if engine._is_converged():
            break

    partitions = engine.get_active_partitions()
    assert len(partitions) == 2

    active_leaders = engine.leaders
    assert len(active_leaders) == 2, f"Expected 2 leaders after split, got {active_leaders}"

    # Verify each partition has exactly one leader
    p0_nodes = set(partitions[0]["nodes"])
    p1_nodes = set(partitions[1]["nodes"])
    assert any(ldr in p0_nodes for ldr in active_leaders)
    assert any(ldr in p1_nodes for ldr in active_leaders)


def test_network_join_leader_resignation_and_global_convergence():
    """Test joining two independent networks: JOIN_REQUEST -> RESIGNATION -> GLOBAL_RE_ELECTION."""
    topo = create_dual_ring_topology()
    events = []

    def on_event(ev):
        events.append(ev)

    engine = HavenSimEngine(topo, event_callback=on_event)
    engine.start_sim()

    # Step simulation until both rings converge to independent leaders
    for _ in range(30):
        engine.step()
        if engine._is_converged():
            break

    partitions = engine.get_active_partitions()
    assert len(partitions) == 2
    assert len(engine.leaders) == 2
    leader_a, leader_b = engine.leaders

    assert leader_a in [1, 2, 3, 4]
    assert leader_b in [5, 6, 7, 8]

    # Now trigger Phase 13 Network Join!
    join_res = engine.join_networks()
    assert join_res["success"] is True
    assert len(join_res["reconnected_links"]) == 2

    # Step through simulation to observe JOIN_REQUEST, RESIGNATION, and GLOBAL_RE_ELECTION
    join_req_seen = False
    resignation_seen = False

    for _ in range(35):
        engine.step()
        event_types = [e["event"] for e in events]
        if "join_request_initiated" in event_types:
            join_req_seen = True
        if "leader_resigned" in event_types:
            resignation_seen = True
        if engine.status == "CONVERGED" and len(engine.leaders) == 1:
            break

    assert join_req_seen, "Expected join_request_initiated event"
    assert resignation_seen, "Expected leader_resigned event"

    # Verify single unified leader after merge
    assert len(engine.get_active_partitions()) == 1
    assert len(engine.leaders) == 1
    unified_leader = engine.leader
    assert unified_leader is not None
    # Highest score node should win global consensus (Node 1 has battery 100)
    assert unified_leader == 1


def test_gui_server_split_and_join_e2e():
    """End-to-end test of HavenGuiServer preset loading, split_network and join_networks commands."""
    import asyncio
    from gui.server import HavenGuiServer

    async def _async_flow():
        server = HavenGuiServer(host="127.0.0.1", port=0)
        # Load dual ring preset
        await server.load_preset("dual_ring_split")
        status = server.get_status()
        assert status["num_nodes"] == 8
        assert status["is_partitioned"] is True
        assert len(status["partitions"]) == 2

        # Start simulation
        server.sim_engine.start_sim()

        # Step simulation in engine until both partitions elect leaders
        for _ in range(30):
            server.sim_engine.step()

        assert len(server.sim_engine.leaders) == 2

        # Test WebSocket command split_network
        await server.handle_ws_command(None, {"action": "split_network"})
        topo = server.get_topology_data()
        assert topo["meta"]["is_partitioned"] is True

        # Test WebSocket command join_networks
        await server.handle_ws_command(None, {"action": "join_networks"})
        topo_joined = server.get_topology_data()
        assert topo_joined["meta"]["is_partitioned"] is False
        assert len(server.sim_engine.get_active_partitions()) == 1

        # Step simulation to finish convergence into a single leader
        for _ in range(35):
            server.sim_engine.step()
            if server.sim_engine.status == "CONVERGED":
                break

        assert len(server.sim_engine.leaders) == 1
        assert server.sim_engine.leader in range(1, 9)

    asyncio.run(_async_flow())


def test_rest_api_split_and_join():
    """Test REST API handlers api_split_network and api_join_networks."""
    import asyncio
    from unittest.mock import MagicMock
    from gui.server import HavenGuiServer

    async def _test():
        server = HavenGuiServer(host="127.0.0.1", port=0)
        await server.load_preset("mesh_10")
        server.sim_engine.battery_drain_enabled = False
        server.sim_engine.start_sim()

        # Step until initial leader
        for _ in range(25):
            server.sim_engine.step()

        # Mock request for split
        req_split = MagicMock()
        req_split.can_read_body = True
        req_split.json = MagicMock(return_value=asyncio.Future())
        req_split.json.return_value.set_result({})

        res_split = await server.api_split_network(req_split)
        assert res_split.status == 200

        status = server.get_status()
        assert status["is_partitioned"] is True

        # Mock request for join
        req_join = MagicMock()
        req_join.can_read_body = True
        req_join.json = MagicMock(return_value=asyncio.Future())
        req_join.json.return_value.set_result({})

        res_join = await server.api_join_networks(req_join)
        assert res_join.status == 200

        status_after = server.get_status()
        assert status_after["is_partitioned"] is False

    asyncio.run(_test())


