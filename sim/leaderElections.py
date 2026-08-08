import random
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# --- Simulation Parameters ---
NODE_NUMBER = 50
NEAREST_NEIGHBORS = 4
LEADER_EPOCHS = 20
RESONANCE_THRESHOLD = 3
TIMEOUT = 5
LEADER_PENALTY = 5.0

class Node:
    def __init__(self, node_id, unique_score):
        self.id = node_id
        self.score = unique_score   
        self.reset_election_state()

    def reset_election_state(self):
        self.state = "IDLE"  # IDLE, ELECTING, LISTENING, VOTED, LEADER
        self.best_candidate = (self.score, self.id)
        self.last_packet = None
        self.resonance_count = 0
        self.timeout_counter = 0
        self.voted_leader = None

    def deduct_battery(self, penalty=LEADER_PENALTY):
        self.score = round(max(0.0, self.score - penalty), 1)
        self.best_candidate = (self.score, self.id)

class ProtocolSimulation:
    def __init__(self, n_nodes, k_neighbors, leader_epochs, resonance_thresh, timeout):
        self.n_nodes = n_nodes
        self.k_neighbors = k_neighbors
        self.leader_epochs = leader_epochs
        self.resonance_thresh = resonance_thresh
        self.timeout = timeout
        
        self.graph, self.pos = self._create_random_knn_graph()
        
        # Unique initial scores (10.0 to 99.0)
        unique_scores = [round(s, 1) for s in random.sample(
            [x / 10.0 for x in range(100, 990)], self.n_nodes
        )]
        self.nodes = {i: Node(i, unique_scores[i]) for i in range(n_nodes)}
        
        self.current_epoch = 0
        self.phase = "LEADER_ACTIVE"
        self.msg_queue = []
        
        self.leader_id = random.choice(list(self.nodes.keys()))
        self.nodes[self.leader_id].state = "LEADER"

    def _create_random_knn_graph(self):
        G = nx.Graph()
        pos = {i: (random.uniform(0, 100), random.uniform(0, 100)) for i in range(self.n_nodes)}
        
        for i in range(self.n_nodes):
            G.add_node(i)
            
        for i in range(self.n_nodes):
            distances = []
            for j in range(self.n_nodes):
                if i != j:
                    dist = np.linalg.norm(np.array(pos[i]) - np.array(pos[j]))
                    distances.append((dist, j))
            distances.sort()
            for _, neighbor in distances[:self.k_neighbors]:
                G.add_edge(i, neighbor)
                
        return G, pos

    def step(self):
        if self.phase == "LEADER_ACTIVE":
            self.current_epoch += 1
            
            if self.current_epoch >= self.leader_epochs:
                self.phase = "ELECTION"
                self.current_epoch = 0
                
                for node in self.nodes.values():
                    node.reset_election_state()

                # Retiring leader triggers election via adjacent neighbors
                old_leader_id = self.leader_id
                neighbors = list(self.graph.neighbors(old_leader_id))
                for neighbor in neighbors:
                    n_node = self.nodes[neighbor]
                    n_node.state = "ELECTING"
                    packet = n_node.best_candidate
                    
                    # Prevent sending election packets back to the retiring leader
                    for target in self.graph.neighbors(neighbor):
                        if target != old_leader_id:
                            self.msg_queue.append((neighbor, target, packet))

        elif self.phase == "ELECTION":
            next_queue = []
            
            for sender, receiver, packet in self.msg_queue:
                recv_node = self.nodes[receiver]
                
                if recv_node.state == "VOTED":
                    continue

                # Echo Resonance Tracking
                if packet == recv_node.last_packet:
                    recv_node.resonance_count += 1
                else:
                    recv_node.last_packet = packet
                    recv_node.resonance_count = 1

                # 1. Incoming packet is strictly BETTER
                if packet > recv_node.best_candidate:
                    recv_node.best_candidate = packet
                    recv_node.resonance_count = 1
                    recv_node.timeout_counter = 0
                    recv_node.state = "ELECTING"
                    
                    # Forward new better packet to neighbors EXCEPT sender
                    for target in self.graph.neighbors(receiver):
                        if target != sender:
                            next_queue.append((receiver, target, packet))

                # 2. Local candidate is strictly BETTER than incoming packet
                elif recv_node.best_candidate > packet:
                    better_packet = recv_node.best_candidate
                    recv_node.state = "ELECTING"
                    
                    # Broadcast local superior candidate to neighbors EXCEPT sender
                    for target in self.graph.neighbors(receiver):
                        if target != sender:
                            next_queue.append((receiver, target, better_packet))

                # 3. Duplicate candidate received -> check resonance threshold
                elif recv_node.resonance_count >= self.resonance_thresh:
                    recv_node.state = "LISTENING"

            self.msg_queue = next_queue

            for node_id, node in self.nodes.items():
                if node.state == "LISTENING":
                    node.timeout_counter += 1
                    if node.timeout_counter >= self.timeout:
                        node.state = "VOTED"
                        node.voted_leader = node.best_candidate[1]
                elif node.state in ("IDLE", "ELECTING") and not self.msg_queue:
                    node.state = "VOTED"
                    node.voted_leader = node.best_candidate[1]

            if all(node.state == "VOTED" for node in self.nodes.values()):
                votes = [node.voted_leader for node in self.nodes.values() if node.voted_leader is not None]
                if votes:
                    self.leader_id = max(set(votes), key=votes.count)
                    self.nodes[self.leader_id].state = "LEADER"
                    self.nodes[self.leader_id].deduct_battery(LEADER_PENALTY)
                    
                    self.current_epoch = 0
                    self.phase = "LEADER_ACTIVE"

# --- Visualization Setup ---
sim = ProtocolSimulation(
    n_nodes=NODE_NUMBER, 
    k_neighbors=NEAREST_NEIGHBORS, 
    leader_epochs=LEADER_EPOCHS, 
    resonance_thresh=RESONANCE_THRESHOLD, 
    timeout=TIMEOUT
)

fig, ax = plt.subplots(figsize=(9, 9))

def get_node_color(state):
    colors = {
        "LEADER": "#2ecc71",     # Green
        "IDLE": "#95a5a6",       # Grey
        "ELECTING": "#e74c3c",   # Red
        "LISTENING": "#f39c12",  # Orange
        "VOTED": "#3498db"       # Blue
    }
    return colors.get(state, "#95a5a6")

def update(frame):
    ax.clear()
    sim.step()
    
    node_colors = [get_node_color(sim.nodes[i].state) for i in sim.graph.nodes()]
    
    nx.draw_networkx_edges(sim.graph, sim.pos, ax=ax, alpha=0.3, edge_color="gray")
    nx.draw_networkx_nodes(sim.graph, sim.pos, ax=ax, node_color=node_colors, node_size=650)
    
    labels = {
        i: f"N{i}\nS:{sim.nodes[i].score:.1f}\n(N{sim.nodes[i].best_candidate[1]})" 
        for i in sim.graph.nodes()
    }
    nx.draw_networkx_labels(sim.graph, sim.pos, labels=labels, font_size=6, ax=ax)
    
    for sender, receiver, _ in sim.msg_queue:
        p1 = np.array(sim.pos[sender])
        p2 = np.array(sim.pos[receiver])
        midpoint = 0.6 * p1 + 0.4 * p2
        ax.plot(midpoint[0], midpoint[1], 'ro', markersize=4)

    leader_node = sim.nodes[sim.leader_id]
    status_text = (
        f"Frame: {frame} | Phase: {sim.phase}\n"
        f"Active Leader: N{sim.leader_id} (Score: {leader_node.score:.1f}) | Term Progress: {sim.current_epoch}/{LEADER_EPOCHS} Epochs"
    )
    ax.set_title(status_text, fontsize=11, fontweight="bold")
    ax.axis("off")

ani = animation.FuncAnimation(fig, update, interval=400, repeat=True, cache_frame_data=False)
plt.show()