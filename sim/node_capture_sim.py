import networkx as nx
import random
import math
import numpy as np

def generate_key_ring(m, k):
    return set(random.sample(range(m), k))

def run_monte_carlo_simulation(trials=1000, n_nodes=20, radius=0.35, m=20, k=4, p_capture=0.10):
    num_captured = int(n_nodes * p_capture)
    compromise_rates = []

    for trial in range(trials):
        # 1. Topology (M6): Generate Random Geometric Graph
        G = nx.random_geometric_graph(n_nodes, radius)
        
        # 2. Key Pre-distribution (M6): Assign keys and find secure links
        key_rings = {node: generate_key_ring(m, k) for node in range(n_nodes)}
        
        secure_links = []
        for u, v in G.edges():
            shared_keys = key_rings[u].intersection(key_rings[v])
            if shared_keys:
                secure_links.append({'u': u, 'v': v, 'shared_keys': shared_keys})
                
        if not secure_links:
            continue # No secure links in this topology
            
        # 3. Node Capture Attack (M7): Randomly compromise 10% of nodes
        captured_nodes = set(random.sample(range(n_nodes), num_captured))
        
        # Pool attacker keys
        attacker_key_pool = set()
        for node in captured_nodes:
            attacker_key_pool.update(key_rings[node])
            
        # 4. Zhao 2019 Verification (M7)
        # Iterate surviving secure links (neither node is captured)
        surviving_links = [link for link in secure_links 
                           if link['u'] not in captured_nodes and link['v'] not in captured_nodes]
                           
        if not surviving_links:
            continue
            
        compromised_surviving_links = 0
        for link in surviving_links:
            # A link is compromised if ANY of its shared keys are in the attacker's pool
            # Assuming they use one of the shared keys (randomly or deterministically, 
            # worst case: attacker can decrypt if they have the key used for the link)
            # Typically, all shared keys or a derived key from all shared keys is used.
            # Let's say if they have at least one shared key, it's compromised.
            if link['shared_keys'].intersection(attacker_key_pool):
                compromised_surviving_links += 1
                
        compromise_rate = compromised_surviving_links / len(surviving_links)
        compromise_rates.append(compromise_rate)

    avg_compromise_rate = np.mean(compromise_rates)
    print(f"--- Node Capture Attack Monte Carlo Simulation ---")
    print(f"Trials: {trials}")
    print(f"Network Size: {n_nodes} nodes, Radius: {radius}")
    print(f"Key Pool (m): {m}, Keys per node (k): {k}")
    print(f"Nodes Captured: {num_captured} ({p_capture*100}%)")
    print(f"Empirical Compromise Rate (Collateral Damage): {avg_compromise_rate*100:.4f}%")
    
    if avg_compromise_rate < 0.01:
        print("VERIFICATION SUCCESS: Compromise rate is below 1%.")
    else:
        print("VERIFICATION FAILED: Compromise rate is 1% or higher.")

if __name__ == "__main__":
    run_monte_carlo_simulation()
