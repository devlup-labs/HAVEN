import random
import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# ============================================================
# SIMULATION PARAMETERS
# ============================================================

NODE_NUMBER = 15
NEAREST_NEIGHBORS = 5
LEADER_EPOCHS = 20
RESONANCE_THRESHOLD = 3
TIMEOUT = 10

# ---------------- Battery & Energy Parameters ----------------
INITIAL_BATTERY = 100.0
NORMAL_DRAIN = 0.015         # Energy consumed by normal node per epoch
LEADER_EXTRA_DRAIN = 0.04    # Extra energy consumed by leader per epoch
TX_COST = 0.002              # Transmission cost
RX_COST = 0.001              # Reception cost


# ============================================================
# NODE CLASS
# ============================================================

class Node:
    def __init__(self, node_id, unique_score):
        self.id = node_id
        self.initial_score = unique_score
        self.battery = INITIAL_BATTERY
        self.score = self.calculate_score()
        self.reset_election_state()

    def calculate_score(self):
        # Score dynamically scales down linearly with remaining battery percentage
        return round(
            self.initial_score * (self.battery / INITIAL_BATTERY),
            1
        )

    def update_battery(self, amount):
        self.battery = round(max(0.0, self.battery - amount), 2)
        self.score = self.calculate_score()
        self.best_candidate = (self.score, self.id)

    def normal_energy_drain(self):
        self.update_battery(NORMAL_DRAIN)

    def leader_energy_drain(self):
        self.update_battery(LEADER_EXTRA_DRAIN)

    def transmit_energy(self):
        self.update_battery(TX_COST)

    def receive_energy(self):
        self.update_battery(RX_COST)

    @property
    def alive(self):
        return self.battery > 0

    def reset_election_state(self):
        self.state = "IDLE"  # IDLE, ELECTING, LISTENING, VOTED, LEADER
        self.best_candidate = (self.score, self.id)
        self.last_packet = None
        self.resonance_count = 0
        self.timeout_counter = 0
        self.voted_leader = None


# ============================================================
# PROTOCOL SIMULATION
# ============================================================

class ProtocolSimulation:
    def __init__(self, n_nodes, k_neighbors, leader_epochs, resonance_thresh, timeout):
        self.n_nodes = n_nodes
        self.k_neighbors = k_neighbors
        self.leader_epochs = leader_epochs
        self.resonance_thresh = resonance_thresh
        self.timeout = timeout
        
        self.graph, self.pos = self._create_random_knn_graph()
        
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
            
            # Normal drain for all alive nodes
            for node in self.nodes.values():
                if node.alive:
                    node.normal_energy_drain()
            
            # Extra penalty drain for active leader
            leader = self.nodes[self.leader_id]
            if leader.alive:
                leader.leader_energy_drain()
            
            # Check if leader died from energy depletion
            if not leader.alive or self.current_epoch >= self.leader_epochs:
                self.phase = "ELECTION"
                self.current_epoch = 0
                
                for node in self.nodes.values():
                    if node.alive:
                        node.reset_election_state()
                    else:
                        node.state = "VOTED"

                old_leader_id = self.leader_id
                neighbors = list(self.graph.neighbors(old_leader_id))
                for neighbor in neighbors:
                    n_node = self.nodes[neighbor]
                    if not n_node.alive:
                        continue
                        
                    n_node.state = "ELECTING"
                    packet = n_node.best_candidate
                    
                    for target in self.graph.neighbors(neighbor):
                        if target != old_leader_id and self.nodes[target].alive:
                            n_node.transmit_energy()
                            self.msg_queue.append((neighbor, target, packet))

        elif self.phase == "ELECTION":
            next_queue = []
            
            for sender, receiver, packet in self.msg_queue:
                sender_node = self.nodes[sender]
                recv_node = self.nodes[receiver]
                
                if not sender_node.alive or not recv_node.alive:
                    continue

                # Energy costs for comms
                recv_node.receive_energy()
                sender_node.transmit_energy()
                
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
                    
                    for target in self.graph.neighbors(receiver):
                        if target != sender and self.nodes[target].alive:
                            recv_node.transmit_energy()
                            next_queue.append((receiver, target, packet))

                # 2. Local candidate is strictly BETTER than incoming packet
                elif recv_node.best_candidate > packet:
                    better_packet = recv_node.best_candidate
                    recv_node.state = "ELECTING"
                    
                    for target in self.graph.neighbors(receiver):
                        if target != sender and self.nodes[target].alive:
                            recv_node.transmit_energy()
                            next_queue.append((receiver, target, better_packet))

                # 3. Duplicate candidate received -> check resonance threshold
                elif recv_node.resonance_count >= self.resonance_thresh:
                    recv_node.state = "LISTENING"

            self.msg_queue = next_queue

            for node_id, node in self.nodes.items():
                if not node.alive:
                    node.state = "VOTED"
                    node.voted_leader = None
                    continue

                if node.state == "LISTENING":
                    node.timeout_counter += 1
                    if node.timeout_counter >= self.timeout:
                        node.state = "VOTED"
                        node.voted_leader = node.best_candidate[1]
                elif node.state in ("IDLE", "ELECTING") and not self.msg_queue:
                    node.state = "VOTED"
                    node.voted_leader = node.best_candidate[1]

            if all(node.state == "VOTED" for node in self.nodes.values()):
                votes = [
                    node.voted_leader for node in self.nodes.values() 
                    if node.voted_leader is not None and self.nodes[node.voted_leader].alive
                ]
                if votes:
                    self.leader_id = max(set(votes), key=votes.count)
                    self.nodes[self.leader_id].state = "LEADER"
                    
                    for node in self.nodes.values():
                        if node.id != self.leader_id:
                            node.state = "IDLE"
                            
                    self.current_epoch = 0
                    self.phase = "LEADER_ACTIVE"

# ============================================================
# VISUALIZATION SETUP
# ============================================================

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
        i: f"N{i}\nBat:{sim.nodes[i].battery:.0f}%\nS:{sim.nodes[i].score:.1f}" 
        for i in sim.graph.nodes()
    }
    nx.draw_networkx_labels(sim.graph, sim.pos, labels=labels, font_size=5, ax=ax)
    
    for sender, receiver, _ in sim.msg_queue:
        p1 = np.array(sim.pos[sender])
        p2 = np.array(sim.pos[receiver])
        midpoint = 0.6 * p1 + 0.4 * p2
        ax.plot(midpoint[0], midpoint[1], 'ro', markersize=3)

    leader_node = sim.nodes[sim.leader_id]
    status_text = (
        f"Frame: {frame} | Phase: {sim.phase}\n"
        f"Active Leader: N{sim.leader_id} (Battery: {leader_node.battery:.1f}%, Score: {leader_node.score:.1f}) | Term: {sim.current_epoch}/{LEADER_EPOCHS}"
    )
    ax.set_title(status_text, fontsize=10, fontweight="bold")
    ax.axis("off")

ani = animation.FuncAnimation(fig, update, interval=400, repeat=True, cache_frame_data=False)
plt.show()