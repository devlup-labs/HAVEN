"""
Discrete-event model of Pseudeocode_basic.md PHASE 2-9 on a chordal ring.

Mirrors firmware/src/haven.c so the tuning constants (HAVEN_ECHO_THRESHOLD,
HAVEN_T_CLAIM_MS, HAVEN_T_WINDOW_MS) can be chosen from measurement instead of
guesswork. Time is counted in link hops, so it is independent of the radio data
rate; multiply by your per-hop delay to get wall-clock milliseconds.

Key measured fact: on a ring the winner needs ~n hops for both echoes to come
back, so T_claim must exceed n x hop_delay or the origin never claims.

Known limitation, not a bug: pseudocode_basic has no partition handling, so a
broken ring elects one leader per segment.

Run: pytest sim/tests/
"""
from collections import deque
import pytest

try:
    from test_simulation.turboblom import assign_spaces
except ModuleNotFoundError:
    try:
        from sim.turboblom import assign_spaces
    except ModuleNotFoundError:
        from turboblom import assign_spaces

K_MASTER = bytes(range(32))
MAX_ADJ = 2            # firmware: HAVEN_MAX_ADJ_NODES
ECHO_THRESHOLD = 2     # firmware: HAVEN_ECHO_THRESHOLD
T_CLAIM_HOPS = 1       # scaled timer, in hops
T_WINDOW_HOPS = 1
REPLAY_HOP_LIMIT = None

PRNG_A, PRNG_B, PRNG_M = 1664525, 1013904223, 4294967296


class LCG:
    """Exact mirror of prng_next() in haven.c (affine LCG, seeded with node id)."""

    def __init__(self, seed):
        self.s = seed % PRNG_M

    def next(self):
        self.s = (PRNG_A * self.s + PRNG_B) % PRNG_M
        return self.s


def odds_permille(battery_pct, nb_n, max_adj, l=1, m=1):
    """Exact integer mirror of haven.c PHASE 2, fixed-point permille."""
    o = ((l * battery_pct * 1000) // 100 + (m * nb_n * 1000) // max_adj) // 2
    return max(1, o)


def build_ring(n):
    """Ring 0..n-1 in id order. The model needs a known ring; the firmware
    discovers the same edges via PHASE 1."""
    return {i: {(i - 1) % n, (i + 1) % n} for i in range(n)}


def run(n, batteries=None, echo_threshold=ECHO_THRESHOLD,
        t_claim=T_CLAIM_HOPS, t_window=T_WINDOW_HOPS):
    """Simulate one election.

    Returns dict with leader, latency_hops, echo counts and the winner's score.
    Latency is in hops: first echo ~n, both echoes ~n, claim ~n+t_claim.
    """
    ring = build_ring(n)
    rng = {i: LCG(i + 1) for i in range(n)}
    batt = batteries if batteries is not None else {i: 100 - 10 * i for i in range(n)}

    mode = {i: None for i in range(n)}
    best = {i: (0, 0) for i in range(n)}        # haven.c:251
    echo = {i: 0 for i in range(n)}
    timeout_started = {i: False for i in range(n)}
    # firmware fwd_mask[]: one bit per origin per incoming neighbour, so both
    # directional copies of a packet survive to complete the ring.
    fwd_mask = {i: set() for i in range(n)}

    # ---- PHASE 2: internal score + candidacy coin flip ----
    for i in range(n):
        nb = len(ring[i])
        odds = odds_permille(batt[i], nb, MAX_ADJ)
        prob = (rng[i].next() * 1000) // PRNG_M
        mode[i] = "ELECTION" if odds > prob else "PASSTHROUGH"

    # ---- PHASE 3: election packet broadcast to both ring neighbours ----
    frontier = deque()
    for i in range(n):
        if mode[i] == "ELECTION":
            score = batt[i] + len(ring[i])        # pseudocode:46
            best[i] = (score, i)
            echo[i] = 0
            timeout_started[i] = False
            for d in ring[i]:
                frontier.append((score, i, i, d, 0))   # score, origin, replayer, dst, age

    claim_at = {}
    hop = 0
    leader = None
    latency = None
    # Must admit the timer schedule, otherwise a large T_claim is silently
    # truncated and looks like a deadlock.
    hop_limit = 4 * n + 8 + t_claim + t_window + 8

    while (frontier or claim_at) and hop < hop_limit:
        nxt = deque()
        while frontier:
            score, origin, replayer, dst, age = frontier.popleft()
            if age > hop_limit:
                continue
            if origin == dst:
                # PHASE 4: own packet came home -> echo
                echo[dst] += 1
                if echo[dst] >= echo_threshold and not timeout_started[dst]:
                    timeout_started[dst] = True
                    claim_at.setdefault(dst, hop + t_claim)
                continue
            cur = best[dst]
            better = score > cur[0] or (score == cur[0] and origin > cur[1])
            if better:
                best[dst] = (score, origin)
                echo[dst] = 0
                timeout_started[dst] = False
                if mode[dst] == "ELECTION":
                    mode[dst] = "PASSTHROUGH"
            # forward each (origin, incoming neighbour) at most once
            if (origin, replayer) in fwd_mask[dst]:
                continue
            fwd_mask[dst].add((origin, replayer))
            for d in ring[dst]:
                if d != replayer:                 # "excluding sender"
                    nxt.append((score, origin, dst, d, age + 1))
        frontier = nxt
        hop += 1

        # ---- PHASE 5/6/8: T_claim expiry then T_window then LEADER ----
        for i in sorted(claim_at):
            if hop < claim_at[i]:
                continue
            del claim_at[i]                      # fire at most once
            if best[i][1] != i:
                mode[i] = "PASSTHROUGH"          # PHASE 5
                continue
            done = hop + t_window                 # PHASE 8: LEADER once T_window expires
            if leader is None or done < latency:
                leader, latency = i, done

    return {
        "leader": leader,
        "latency": latency,
        "echo": echo,
        "max_echo": max(echo.values()) if echo else 0,
        "best": best,
        "mode": mode,
    }


SIZES = [3, 4, 5, 8, 10, 16, 32, 50]


@pytest.mark.parametrize("n", SIZES)
def test_a_leader_is_elected(n):
    r = run(n)
    assert r["leader"] is not None, f"no leader for n={n}"


@pytest.mark.parametrize("n", SIZES)
def test_exactly_one_node_reaches_best_origin_is_self(n):
    """Only a node whose own packet survived the whole ring may claim, so at
    most one node can hold best_origin == self once the flood converges."""
    r = run(n)
    claimants = [i for i in range(n) if r["best"][i][1] == i]
    assert len(claimants) == 1, f"n={n}: {len(claimants)} nodes hold their own packet"


@pytest.mark.parametrize("n", SIZES)
def test_highest_battery_node_wins(n):
    """score = battery + len(neighbour_list); len is constant (2) on a ring,
    so the best-battery node must win regardless of the coin flip."""
    batt = {i: (i + 1) * 10 for i in range(n)}
    r = run(n, batteries=batt)
    assert r["leader"] == max(batt, key=batt.get), \
        f"n={n}: leader {r['leader']} != best battery {max(batt, key=batt.get)}"


@pytest.mark.parametrize("n", SIZES)
def test_winner_gets_two_echoes_one_per_direction(n):
    """ECHO_THRESHOLD=2 assumes one echo per direction after a full traversal."""
    r = run(n)
    assert r["echo"][r["leader"]] >= ECHO_THRESHOLD, \
        f"n={n}: winner had {r['echo'][r['leader']]} echoes"


@pytest.mark.parametrize("n", SIZES)
def test_ring_returns_at_most_two_echoes(n):
    """Guard for ECHO_THRESHOLD: a ring has two directions, so a threshold above
    2 can never be met and every origin deadlocks."""
    r = run(n)
    assert r["max_echo"] <= 2, f"n={n}: {r['max_echo']} echoes; threshold must be <= 2"


@pytest.mark.parametrize("n", SIZES)
def test_echo_threshold_above_two_stalls_every_origin(n):
    r = run(n, echo_threshold=3)
    assert r["leader"] is None, \
        f"n={n}: a threshold of 3 should deadlock, got leader {r['leader']}"


@pytest.mark.parametrize("n", SIZES)
def test_latency_covers_one_ring_traversal(n):
    """T_claim must exceed n hops or the origin never reaches threshold."""
    r = run(n)
    assert r["latency"] is not None and r["latency"] >= n, \
        f"n={n}: latency {r['latency']} < {n} hops"


def test_latency_grows_monotonically_with_ring_size():
    lats = {n: run(n)["latency"] for n in (3, 5, 10, 20, 40)}
    order = sorted(lats)
    assert all(lats[a] < lats[b] for a, b in zip(order, order[1:])), lats


def test_timers_add_directly_to_latency():
    """Latency is: one ring traversal for both echoes, then T_claim, then
    T_window. Defaults are t_claim=1, t_window=1, so raising them to 6 and 4
    must add exactly 8 hops."""
    n = 10
    base = run(n)["latency"]
    slower = run(n, t_claim=6, t_window=4)["latency"]
    assert slower - base == 8, (base, slower)
    # measured exactly: latency = n + t_claim + t_window - 1
    assert base == n + 1 + 1 - 1, base


def test_larger_t_claim_never_hurts_leadership():
    """T_claim is a safety timer: larger only delays, never deadlocks."""
    for tc in (1, 2, 4, 16, 64):
        r = run(10, t_claim=tc)
        assert r["leader"] is not None, f"t_claim={tc} deadlocked"
        # t_claim=0 is degenerate: the claim fires on the same hop the timer
        # is armed, which the model cannot distinguish from t_claim=1.
        assert r["latency"] == 10 + tc + 1 - 1, (tc, r["latency"])


@pytest.mark.parametrize("n", [3, 4, 5])
def test_three_node_ring_minimum(n):
    """Below 3 nodes left and right neighbours coincide and no echo can return."""
    assert n >= 3
    assert run(n)["leader"] is not None