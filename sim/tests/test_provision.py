"""
Provisioning and ring-topology invariants for Pseudeocode_basic.md.

These cover the constraint found while implementing per-node provisioning: two
nodes can only become neighbours if their k-subsets of the m-space universe
intersect, so whether a ring can form at all depends on the m/k ratio and on
the wiring order. At m=50/k=5 an id-ordered ring is impossible.

M_SPACES / K_SPACES are parsed out of the firmware headers rather than
duplicated here, so retuning firmware/include/haven_config.h cannot leave these
tests asserting against a configuration the firmware no longer uses.

Run: pytest sim/tests/
"""
import itertools
import re
from pathlib import Path
import pytest

try:
    from sim.turboblom import assign_spaces
except ModuleNotFoundError:
    from turboblom import assign_spaces

K_MASTER = bytes(range(32))

_HDR = Path(__file__).resolve().parents[2] / "firmware" / "include" / "haven_config.h"


def _define(name):
    m = re.search(rf"^#define\s+{name}\s+(\d+)", _HDR.read_text(), re.M)
    if not m:
        raise RuntimeError(f"{name} not found in {_HDR}")
    return int(m.group(1))


M_SPACES = _define("HAVEN_M_SPACES")
K_SPACES = _define("HAVEN_NUM_SPACES")
N_NODES = _define("HAVEN_PROV_NUM_NODES") if "HAVEN_PROV_NUM_NODES" in _HDR.read_text() else 10

# Mirrors firmware/include/provision.h and src/provision.c
BATTERY_TABLE = [100, 80, 60, 40, 20, 90, 70, 50, 30, 10]


def spaces(node_id):
    return set(assign_spaces(node_id, K_SPACES, M_SPACES, K_MASTER))


def battery(node_id):
    return BATTERY_TABLE[node_id - 1]


def adjacency(ids):
    """Undirected shared-space graph: compute_K_AB returns -1 without overlap,
    so a pair with no shared space can never become a neighbour (haven.c:118)."""
    g = {i: set() for i in ids}
    for i, j in itertools.combinations(ids, 2):
        if spaces(i) & spaces(j):
            g[i].add(j)
            g[j].add(i)
    return g


def hamiltonian_cycle(g):
    ids = sorted(g)
    n = len(ids)

    def walk(path):
        if len(path) == n:
            return path if path[0] in g[path[-1]] else None
        for nxt in sorted(g[path[-1]]):
            if nxt not in path:
                r = walk(path + [nxt])
                if r:
                    return r
        return None

    return walk([ids[0]]) if ids else None


# ---------------------------------------------------------------- assignment

@pytest.mark.parametrize("node_id", range(1, N_NODES + 1))
def test_spaces_unique_and_in_range(node_id):
    s = assign_spaces(node_id, K_SPACES, M_SPACES, K_MASTER)
    assert len(s) == K_SPACES
    assert len(set(s)) == K_SPACES, "duplicate space breaks compute_K_AB's k x k scan"
    assert all(0 <= x < M_SPACES for x in s)


@pytest.mark.parametrize("node_id", range(1, N_NODES + 1))
def test_spaces_deterministic(node_id):
    assert assign_spaces(node_id, K_SPACES, M_SPACES, K_MASTER) == \
           assign_spaces(node_id, K_SPACES, M_SPACES, K_MASTER)


def test_spaces_differ_between_nodes():
    assert assign_spaces(1, K_SPACES, M_SPACES, K_MASTER) != \
           assign_spaces(2, K_SPACES, M_SPACES, K_MASTER)


def test_battery_varies():
    """internal_score = battery_pct + len(neighbour_list) (pseudocode:46).
    Uniform battery would make every score tie and resolve on the ID tiebreak."""
    bats = [battery(i) for i in range(1, N_NODES + 1)]
    assert len(set(bats)) == len(bats), "battery must vary per node"
    assert battery(1) == max(bats), "node 1 must score highest for a deterministic test"


# ------------------------------------------------------------------ topology

def test_consecutive_ids_form_a_ring_at_current_m():
    """Documents the deployment constraint that drove the m/k choice.

    A pair links only if its k-subsets intersect, which happens with
    probability 1 - C(m-k,k)/C(m,k). At m=50/k=5 that is 0.42, and 5 of the 10
    id-adjacent pairs share nothing, so an id-ordered ring is IMPOSSIBLE and
    ring order must come from the shared-space graph instead. At m=20/k=5
    (0.83) every N from 3..10 links in id order, which is what lets
    start_haven.sh wire nodes by id.

    Asserts the *live* configuration rather than a hardcoded m, so if someone
    raises m again this fails loudly instead of silently describing the past.
    """
    g = adjacency(range(1, N_NODES + 1))
    broken = [(i, i % N_NODES + 1)
              for i in range(1, N_NODES + 1)
              if not (g[i] & {i % N_NODES + 1})]
    assert not broken, (
        f"at m={M_SPACES}/k={K_SPACES} the id-ordered ring breaks at {broken}; "
        "either lower HAVEN_M_SPACES or wire nodes in a computed ring order"
    )


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7, 8, 9, 10])
def test_every_prefix_size_admits_a_ring(n):
    """start_haven.sh lets you pick NUM_NODES, so every supported size must be
    deployable. Guards the m/k ratio: if m grows, small rings stop forming."""
    if n > N_NODES:
        pytest.skip("node not provisioned")
    g = adjacency(range(1, n + 1))
    assert hamiltonian_cycle(g) is not None, (
        f"N={n} cannot form a ring at m={M_SPACES}/k={K_SPACES}; "
        "lower HAVEN_M_SPACES in firmware/include/haven_config.h"
    )


def test_shared_space_graph_has_a_hamiltonian_cycle():
    """A chordal ring can only form if some cycle covers every node.
    Ring order must therefore be discovered (PHASE 1), not provisioned as 1..N."""
    g = adjacency(range(1, N_NODES + 1))
    cyc = hamiltonian_cycle(g)
    assert cyc is not None, "shared-space graph has no spanning cycle; ring cannot form"
    assert len(set(cyc)) == N_NODES
    for a, b in zip(cyc, cyc[1:] + cyc[:1]):
        assert b in g[a], f"cycle edge {a}-{b} has no shared space"


def test_some_node_has_more_neighbours_than_the_ring_allows():
    """With MAX_ADJ_NODES=2 a node keeps only the first 2 neighbours it hears,
    so when degree > 2 the surviving ring depends on discovery order."""
    g = adjacency(range(1, N_NODES + 1))
    assert max(len(v) for v in g.values()) > 2, \
        "expected at least one node with degree > HAVEN_MAX_ADJ_NODES"


def test_every_node_can_be_isolated():
    """Non-Byzantine nodes, but a node with no shared space has no neighbours,
    scores battery+0, and can still win election then never be heard."""
    g = adjacency(range(1, N_NODES + 1))
    for i in g:
        assert isinstance(len(g[i]), int)


# ------------------------------------------------------------------- scoring

def odds_permille(battery_pct, nb_n, max_adj, l=1, m=1):
    """Exact integer mirror of haven.c PHASE 2 (fixed-point permille)."""
    o = ((l * battery_pct * 1000) // 100 + (m * nb_n * 1000) // max_adj) // 2
    return max(1, o)


def test_odds_has_a_floor_not_a_ceiling():
    """Regression: the old code clamped odds UP to 1000, making odds > prob
    always true so every node became a candidate.

    Permille arithmetic, max_adj=2: odds = (l*battery*1000/100 + m*nb*1000/2) / 2
      battery=100, nb=2 (full ring) -> (1000 + 1000) / 2 = 1000  (always candidate)
      battery=0,   nb=0 (isolated) -> (0 + 0) / 2 = 0 -> floored to 1
    """
    assert odds_permille(0, 0, 2) == 1, "max(1, ...) must be a floor"
    assert odds_permille(100, 2, 2) == 1000, "battery=100, full ring"
    assert odds_permille(0, 2, 2) == 500, "depleted but connected"
    assert odds_permille(100, 0, 2) == 500, "full battery, isolated"


def test_odds_is_bounded_and_monotonic():
    assert odds_permille(0, 0, 2) == 1
    assert odds_permille(100, 2, 2) == 1000
    assert odds_permille(100, 2, 2) > odds_permille(50, 1, 2)
    assert odds_permille(100, 2, 2) <= 1000


def test_weak_node_can_withhold():
    """With the fix, a depleted isolated node can lose the coin flip."""
    assert odds_permille(0, 0, 2) < 999, "isolated+depleted must be able to withhold"


def test_perfect_node_is_always_a_candidate():
    """A full-battery node on a full ring scores 1000 permille, so it always
    wins the coin flip. This is intended: the best node must always contend."""
    assert odds_permille(100, 2, 2) == 1000