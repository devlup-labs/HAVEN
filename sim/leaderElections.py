import random
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# --- Simulation Parameters ---
NODE_NUMBER = 20
NEAREST_NEIGHBORS = 4
LEADER_EPOCHS = 5
RESONANCE_THRESHOLD = 2
TIMEOUT = 5

class Node:
    def __init__(self, node_id):
        self.id = node_id
        self.score = round(random.uniform(10, 100), 2)
        self.state = "IDLE"
        self.best_candidate = (self.score, self.id)
        self.last_packet = None
        self.resonance_count = 0
        self.timeout_counter = 0
        self.voted_leader = None

class ProtocolSimulation:
    def __init__(self, n_nodes, k_neighbors, leader_epochs, resonance_thresh, timeout):
        self.n_nodes = n_nodes
        self.k_neighbors = k_neighbors
        self.leader_epochs = leader_epochs
        self.resonance_thresh = resonance_thresh
        self.timeout = timeout
        
        self.graph, self.pos = self._create_random_knn_graph()
        self.nodes = {i: Node(i) for i in range(n_nodes)}
        
        self.current_epoch = 0
        self.phase = "LEADER_ACTIVE"
        self.msg_queue = []
        
        self.leader_id = random.choice(list(self.nodes.keys()))
        self.nodes[self.leader_id].state = "LEADER"

    def _create_random_knn_graph(self):
        G = nx.Graph()
        
        # 1. Generate random 2D coordinates for all nodes
        pos = {i: (random.uniform(0, 100), random.uniform(0, 100)) for i in range(self.n_nodes)}
        
        for i in range(self.n_nodes):
            G.add_node(i)
            
        # 2. Connect each node to its k-nearest Euclidean spatial neighbors
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
                old_leader = self.nodes[self.leader_id]
                old_leader.state = "IDLE"
                
                neighbors = list(self.graph.neighbors(self.leader_id))
                for neighbor in neighbors:
                    n_node = self.nodes[neighbor]
                    n_node.state = "ELECTING"
                    packet = n_node.best_candidate
                    for target in self.graph.neighbors(neighbor):
                        self.msg_queue.append((neighbor, target, packet))

        elif self.phase == "ELECTION":
            next_queue = []
            
            for sender, receiver, packet in self.msg_queue:
                recv_node = self.nodes[receiver]
                
                if recv_node.state == "VOTED":
                    continue

                if packet == recv_node.last_packet:
                    recv_node.resonance_count += 1
                else:
                    recv_node.last_packet = packet
                    recv_node.resonance_count = 1

                if packet > recv_node.best_candidate:
                    recv_node.best_candidate = packet
                    recv_node.resonance_count = 1
                    recv_node.state = "ELECTING"
                    for target in self.graph.neighbors(receiver):
                        if target != sender:
                            next_queue.append((receiver, target, packet))
                            
                elif recv_node.resonance_count >= self.resonance_thresh:
                    recv_node.state = "LISTENING"
                else:
                    if recv_node.state == "ELECTING":
                        for target in self.graph.neighbors(receiver):
                            if target != sender:
                                next_queue.append((receiver, target, packet))

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

            all_voted = all(node.state == "VOTED" for node in self.nodes.values())

            if all_voted:
                votes = [node.voted_leader for node in self.nodes.values() if node.voted_leader is not None]
                if votes:
                    self.leader_id = max(set(votes), key=votes.count)
                    self.nodes[self.leader_id].state = "LEADER"
                    self.phase = "CONVERGED"

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
        i: f"N{i}\n({sim.nodes[i].best_candidate[0]:.1f}, N{sim.nodes[i].best_candidate[1]})" 
        for i in sim.graph.nodes()
    }
    nx.draw_networkx_labels(sim.graph, sim.pos, labels=labels, font_size=6, ax=ax)
    
    for sender, receiver, _ in sim.msg_queue:
        p1 = np.array(sim.pos[sender])
        p2 = np.array(sim.pos[receiver])
        midpoint = 0.6 * p1 + 0.4 * p2
        ax.plot(midpoint[0], midpoint[1], 'ro', markersize=4)

    status_text = (
        f"Frame: {frame} | Phase: {sim.phase}\n"
        f"Active Leader: N{sim.leader_id} | Leader Epoch: {sim.current_epoch}/{LEADER_EPOCHS}"
    )
    ax.set_title(status_text, fontsize=11, fontweight="bold")
    ax.axis("off")

ani = animation.FuncAnimation(fig, update, frames=80, interval=500, repeat=False)
plt.show()