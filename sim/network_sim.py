import random
import networkx as nx
import numpy as np
import hashlib
import hmac
from sim.turboblom import assign_spaces

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
            
    connectivity_ratio = sharing_pairs / total_pairs if total_pairs > 0 else 0
    return total_pairs, sharing_pairs, connectivity_ratio

def run_compromise_trial(node_spaces, edges):
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
    captured_nodes = random.sample(range(N_NODES), int(0.1 * N_NODES))
    
    # Track how many times each space is known by captured nodes
    space_counts = {s: 0 for s in range(M_SPACES)}
    captured_spaces = set()
    for node in captured_nodes:
        for space in node_spaces[node]:
            space_counts[space] += 1
            captured_spaces.add(space)
            
    # Compromised spaces based on Blom's threshold (>= lambda + 1)
    compromised_spaces_blom = {s for s, count in space_counts.items() if count >= LAMBDA_THRESHOLD + 1}
    
    total_links = 0
    compromised_links_naive = 0
    compromised_links_blom = 0
    
    for u, v in edges:
        shared = set(node_spaces[u]) & set(node_spaces[v])
        if len(shared) >= 1:
            total_links += 1
            # Naive model: compromised if any shared space is known by any captured node
            if shared & captured_spaces:
                compromised_links_naive += 1
            # Blom model: compromised if any shared space is cryptographically compromised
            if shared & compromised_spaces_blom:
                compromised_links_blom += 1
                
    return total_links, compromised_links_naive, compromised_links_blom

def main():
    print("=== Layer 1: Connectivity Simulation (10 Runs) ===")
    connectivities = []
    total_pairs_list = []
    sharing_pairs_list = []
    
    for i in range(10):
        total_p, sharing_p, ratio = run_connectivity_simulation()
        connectivities.append(ratio)
        total_pairs_list.append(total_p)
        sharing_pairs_list.append(sharing_p)
        print(f"Run {i+1:2d}: Total pairs in range = {total_p:3d}, Sharing pairs = {sharing_p:3d}, Connectivity = {ratio*100:5.2f}%")
        
    avg_connectivity = np.mean(connectivities)
    print(f"Average connectivity over 10 runs: {avg_connectivity*100:.2f}%")
    print(f"Expected connectivity (theoretical): ~42.3% (pure random)")
    
    print("\n=== Layer 2: Node Capture & Security Simulation (1000 Trials) ===")
    # Generate one stable graph for the 1000 security trials
    G = nx.random_geometric_graph(N_NODES, RADIUS)
    node_spaces = {node: assign_spaces(node, K_SPACES_PER_NODE, M_SPACES, K_MASTER) for node in G.nodes}
    edges = list(G.edges)
    
    naive_compromise_rates = []
    blom_compromise_rates = []
    
    for _ in range(1000):
        total_l, comp_n, comp_b = run_compromise_trial(node_spaces, edges)
        if total_l > 0:
            naive_compromise_rates.append(comp_n / total_l)
            blom_compromise_rates.append(comp_b / total_l)
            
    avg_naive_rate = np.mean(naive_compromise_rates)
    avg_blom_rate = np.mean(blom_compromise_rates)
    
    print(f"Average Naive Link Compromise Rate: {avg_naive_rate*100:.4f}%")
    print(f"Average Blom (lambda={LAMBDA_THRESHOLD}) Link Compromise Rate: {avg_blom_rate*100:.4f}%")
    
    # Zhao 2019 Theoretical Prediction comparison
    # Under Blom's scheme, the probability of a space being compromised when 5 nodes are captured is:
    # P_comp_space = P(Binomial(5, 5/50) >= 4) = 5 * (0.1)^4 * 0.9 + (0.1)^5 = 0.00046 (0.046%)
    zhao_prediction = 0.00046
    print(f"Zhao 2019 Theoretical Prediction for link compromise: {zhao_prediction*100:.4f}%")
    print(f"Is Blom compromise rate under 1%? {'YES' if avg_blom_rate < 0.01 else 'NO'}")

if __name__ == '__main__':
    # Set seed for reproducible results if desired, or let it be random
    random.seed(42)
    np.random.seed(42)
    main()
