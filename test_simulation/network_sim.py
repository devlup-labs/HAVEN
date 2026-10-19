import random
import networkx as nx
import numpy as np
import hashlib
import hmac
import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from test_simulation.turboblom import assign_spaces
except ModuleNotFoundError:
    try:
        from sim.turboblom import assign_spaces
    except ModuleNotFoundError:
        from turboblom import assign_spaces

# Parameters
N_NODES = 50
RADIUS = 0.25
M_SPACES = 50
K_SPACES_PER_NODE = 5
LAMBDA_THRESHOLD = 3  # Blom scheme threshold
K_MASTER = bytes(range(32, 64))

def run_connectivity_simulation():
    """
    Generates a Random Geometric Graph, assigns spaces to each node,
    and checks if neighbors in radio range share at least 1 space.
    """
    # Generate random geometric graph
    G = nx.random_geometric_graph(N_NODES, RADIUS)
    
    # Assign spaces deterministically using M2 logic
    node_spaces = {}
    for node in G.nodes:
        # Use node ID as integer
        node_spaces[node] = assign_spaces(node, K_SPACES_PER_NODE, M_SPACES, K_MASTER)
        
    total_pairs = G.number_of_edges()
    sharing_pairs = 0
    
    for u, v in G.edges:
        shared = set(node_spaces[u]) & set(node_spaces[v])
        if len(shared) >= 1:
            sharing_pairs += 1
            
    connectivity = (
        sharing_pairs / total_pairs
        if total_pairs > 0
        else 0
    )

    return (
        G,
        node_spaces,
        total_pairs,
        sharing_pairs,
        connectivity
    )

def capture_nodes(node_spaces,n_captured):
    """
    Simulates capturing 10% of nodes (5 nodes) and calculates link compromise rates.
    We compare two models:
    1. Naive model: A link is compromised if any of its shared spaces is known to any captured node.
    2. Blom's threshold model (correct cryptographic model): A space is compromised
       if and only if it is known to >= lambda + 1 captured nodes (since Blom's scheme
       uses bivariate polynomials of degree lambda). A link is compromised if it shares
       a space and that space is compromised.
    """
    # Pick 5 random captured nodes (10% of 50 nodes)
    captured = random.sample(list(node_spaces.keys()),n_captured)
    
    # Track how many times each space is known by captured nodes
    known_spaces = set()

    for node in captured:
        known_spaces.update(node_spaces[node])

    return captured, known_spaces
            
def check_link_compromise(edges,node_spaces,known_spaces):
    #Checks which links are broken.

    total_links = 0
    compromised = 0
    
    for u, v in edges:
        shared = (set(node_spaces[u]) & set(node_spaces[v]))

        if shared:
            total_links += 1

            # attacker knows the space
            if shared & known_spaces:
                compromised += 1

    return compromised, total_links

def check_blom_compromise(edges,node_spaces,captured_nodes):
    """
    Blom model.
    A space is compromised only if lambda + 1 captured nodes know it.
    """

    space_count = {
        s:0
        for s in range(M_SPACES)
    }

    for node in captured_nodes:
        for s in node_spaces[node]:
            space_count[s] += 1

    compromised_spaces = {
        s
        for s,count in space_count.items()

        if count >= LAMBDA_THRESHOLD + 1
    }

    compromised = 0
    total = 0

    for u,v in edges:
        shared = (
            set(node_spaces[u])
            &
            set(node_spaces[v])
        )

        if shared:
            total += 1

            if shared & compromised_spaces:
                compromised += 1

    return compromised,total

def simulate_node_capture(node_spaces,edges,trials=1000,capture_count=5):
    """
    Simulate attacker capturing 5 nodes and calculate link compromise rate.
    """

    naive_rates = []
    blom_rates = []

    for _ in range(trials):
        # attacker captures nodes
        captured_nodes = random.sample(
            list(node_spaces.keys()),
            capture_count
        )

        # spaces known to attacker
        known_spaces = set()

        for node in captured_nodes:
            known_spaces.update(
                node_spaces[node]
            )

        # Naive model

        naive_compromised = 0
        total_links = 0

        for u,v in edges:
            shared = (set(node_spaces[u]) & set(node_spaces[v]))

            if shared:
                total_links += 1

                if shared & known_spaces:
                    naive_compromised += 1

        if total_links:
            naive_rates.append(naive_compromised / total_links)

        # Blom model

        space_count = {
            s:0
            for s in range(M_SPACES)
        }

        for node in captured_nodes:
            for s in node_spaces[node]:
                space_count[s] += 1

        compromised_spaces = {
            s
            for s,count in space_count.items()

            if count >= LAMBDA_THRESHOLD + 1
        }

        blom_compromised = 0
        total_links = 0

        for u,v in edges:
            shared = (set(node_spaces[u]) & set(node_spaces[v]))

            if shared:
                total_links += 1

                if shared & compromised_spaces:
                    blom_compromised += 1

        if total_links:
            blom_rates.append(blom_compromised / total_links)

    return (np.mean(naive_rates), np.mean(blom_rates))

def main():
    print("=== Layer 1: Connectivity Simulation (10 Runs) ===")
    
    connectivity_values = []

    for i in range(10):
        (
            G,
            spaces,
            total,
            sharing,
            ratio
        ) = run_connectivity_simulation()

        connectivity_values.append(ratio)

        print(
            f"Run {i+1:2}: "
            f"Pairs={total:3} "
            f"Shared={sharing:3} "
            f"Connectivity={ratio*100:.2f}%"
        )

    avg_connectivity = np.mean(connectivity_values)
    print(f"\nAverage connectivity over 10 runs: {avg_connectivity*100:.2f}%")
    print(f"Theoretical sharing probability: ~42.34% (Hypergeometric: 1 - comb(45, 5) / comb(50, 5))")
    print(f"Note: The sprint brief's 'roughly 50-60%' estimate likely comes from a naive Union Bound approximation")
    print(f"      (e.g., k * (k / m) = 5 * 0.10 = 50%), which overestimates due to ignoring overlap.")

    print("\n=== Layer 2: Node Capture & Security Simulation (1000 Trials) ===")
    
    # Generate one stable graph for the 1000 security trials
    G, spaces, _, _, _ = run_connectivity_simulation()

    edges = list(G.edges)

    naive, blom = simulate_node_capture(spaces, edges, trials=1000, capture_count=5)

    print("Captured nodes: 5")

    print(
        f"Average Naive Link Compromise Rate: "
        f"{naive*100:.4f}%"
    )

    print(
        f"Average Blom Link Compromise Rate: "
        f"{blom*100:.4f}%"
    )

    # Zhao 2019 Theoretical Prediction comparison
    # Under Blom's scheme, the probability of a space being compromised when 5 nodes are captured is:
    # P_comp_space = P(Binomial(5, 5/50) >= 4) = 5 * (0.1)^4 * 0.9 + (0.1)^5 = 0.00046 (0.046%)

    zhao_prediction = 0.00046

    print(
        f"Zhao prediction: "
        f"{zhao_prediction*100:.4f}%"
    )

    print(
        "Security Test:",
        "PASS" if blom < 0.01 else "FAIL"
    )

if __name__ == "__main__":
    # Set seed for reproducible results if desired, or let it be random
    random.seed(42)
    np.random.seed(42)
    main()
