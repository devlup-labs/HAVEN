import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import random

# --- Simulation Parameters ---
LARGE_NETWORK_SIZE = 25
SMALL_NETWORK_SIZE = 6
MERGE_FRAME = 5  # Reduced from 15 to 5 (0.5 second wait)

class Node:
    def __init__(self, node_id, state):
        self.id = node_id
        self.state = state  # 'LEADER', 'FOLLOWER', 'ISOLATED', 'JOINING', 'ELECTING'
        self.leader_memory_count = 0 

class JoinProtocolSimulation:
    def __init__(self):
        # Generate Large Network (Left)
        self.G_large = nx.random_geometric_graph(LARGE_NETWORK_SIZE, 0.4, seed=42)
        pos_large = nx.get_node_attributes(self.G_large, 'pos')
        self.pos_large = {n: (x - 0.55, y) for n, (x, y) in pos_large.items()}
        
        # Generate Small Network (Right) - Radius 0.8 to ensure internal connection
        self.G_small = nx.random_geometric_graph(SMALL_NETWORK_SIZE, 0.8, seed=10)
        mapping = {n: n + LARGE_NETWORK_SIZE for n in self.G_small.nodes()}
        self.G_small = nx.relabel_nodes(self.G_small, mapping)
        pos_small = nx.get_node_attributes(self.G_small, 'pos')
        self.pos_small = {n: (x + 0.55, y) for n, (x, y) in pos_small.items()}
        
        # Combine into global graph
        self.G = nx.compose(self.G_large, self.G_small)
        self.pos = {**self.pos_large, **self.pos_small}
        
        self.nodes = {}
        for n in self.G_large.nodes():
            self.nodes[n] = Node(n, 'FOLLOWER')
        for n in self.G_small.nodes():
            self.nodes[n] = Node(n, 'ISOLATED')
            
        # Initial Leader
        self.leader_id = max(self.G_large.nodes(), key=lambda n: self.G_large.degree(n))
        self.nodes[self.leader_id].state = 'LEADER'
        
        self.frame_count = 0
        self.msg_queue = []
        self.bridge_edges = []
        self.phase = "ISOLATED"
        self.election_timer = 0

    def _add_bridge_edges(self):
        for u in self.G_large.nodes():
            for v in self.G_small.nodes():
                dist = np.linalg.norm(np.array(self.pos[u]) - np.array(self.pos[v]))
                if dist < 0.65:  
                    self.G.add_edge(u, v)
                    self.bridge_edges.append((u, v))

    def get_next_hop(self, current, target):
        try:
            path = nx.shortest_path(self.G, current, target)
            if len(path) > 1:
                return path[1]
        except nx.NetworkXNoPath:
            pass
        return current

    def step(self):
        self.frame_count += 1
        
        # 1. Trigger Merge
        if self.frame_count == MERGE_FRAME:
            self.phase = "MERGING"
            self._add_bridge_edges()
            for node_id, node in self.nodes.items():
                if node.state == 'ISOLATED':
                    node.state = 'JOINING'
                    self.msg_queue.append((node_id, node_id, self.leader_id, 'PING'))

        # 2. Check if Merge is Complete -> Trigger Resignation
        if self.phase == "MERGING" and not self.msg_queue and self.frame_count > MERGE_FRAME + 2:
            if all(n.state != 'JOINING' for n in self.nodes.values()):
                self.phase = "RESIGNATION"
                
        # 3. Handle Resignation & Start Election
        if self.phase == "RESIGNATION":
            for n in self.nodes.values():
                n.state = 'ELECTING'
            self.phase = "ELECTION"
            self.election_timer = 15  # 1.5 seconds of election flood visuals

        # 4. Handle Election Visuals and Resolution
        elif self.phase == "ELECTION":
            self.election_timer -= 1
            self.msg_queue = []  # Clear normal routing
            
            # Generate random local broadcasts to simulate the High-Water Mark flood
            for _ in range(8):
                u = random.choice(list(self.G.nodes()))
                neighbors = list(self.G.neighbors(u))
                if neighbors:
                    v = random.choice(neighbors)
                    self.msg_queue.append((u, u, v, 'ELECTION'))
                    
            if self.election_timer <= 0:
                self.msg_queue = []
                # Pick the true new leader (Highest degree in the newly combined network)
                new_leader = max(self.G.nodes(), key=lambda n: self.G.degree(n))
                
                for n in self.nodes.values():
                    n.state = 'FOLLOWER'
                self.nodes[new_leader].state = 'LEADER'
                self.leader_id = new_leader
                self.nodes[new_leader].leader_memory_count = 0  # Reset for new leader
                self.phase = "STABLE (NEW LEADER)"
                
        # 5. Process normal PING/ACK routing (Only active during MERGING phase)
        elif self.phase == "MERGING":
            next_queue = []
            for originator, current, target, p_type in self.msg_queue:
                if current == target:
                    if p_type == 'PING' and current == self.leader_id:
                        self.nodes[self.leader_id].leader_memory_count += 1
                        next_queue.append((self.leader_id, self.leader_id, originator, 'ACK'))
                    elif p_type == 'ACK':
                        self.nodes[current].state = 'FOLLOWER'
                else:
                    next_hop = self.get_next_hop(current, target)
                    next_queue.append((originator, next_hop, target, p_type))
            self.msg_queue = next_queue


# --- Visualization Setup ---
sim = JoinProtocolSimulation()
fig, ax = plt.subplots(figsize=(11, 7))

def get_node_color(state):
    colors = {
        'LEADER': '#2ecc71',    # Green
        'FOLLOWER': '#3498db',  # Blue
        'ISOLATED': '#e74c3c',  # Red
        'JOINING': '#f1c40f',   # Yellow
        'ELECTING': '#9b59b6'   # Purple
    }
    return colors.get(state, '#95a5a6')

def update(frame):
    ax.clear()
    sim.step()
    
    sim_time_seconds = sim.frame_count * 0.1 
    node_colors = [get_node_color(sim.nodes[i].state) for i in sim.G.nodes()]
    
    nx.draw_networkx_edges(sim.G, sim.pos, ax=ax, alpha=0.3, edge_color="gray")
    if sim.bridge_edges:
        nx.draw_networkx_edges(sim.G, sim.pos, edgelist=sim.bridge_edges, ax=ax, edge_color='green', width=2.0, style='dashed')
        
    nx.draw_networkx_nodes(sim.G, sim.pos, ax=ax, node_color=node_colors, node_size=400, edgecolors='black')
    
    labels = {i: "L" if sim.nodes[i].state == 'LEADER' else "" for i in sim.G.nodes()}
    nx.draw_networkx_labels(sim.G, sim.pos, labels=labels, font_size=10, font_weight="bold", ax=ax)
    
    for _, current, target, p_type in sim.msg_queue:
        if current != target:
            p1 = np.array(sim.pos[current])
            
            if p_type == 'ELECTION':
                p2 = np.array(sim.pos[target])
            else:
                next_hop = sim.get_next_hop(current, target)
                p2 = np.array(sim.pos[next_hop])
                
            midpoint = 0.5 * p1 + 0.5 * p2
            
            packet_colors = {'PING': 'red', 'ACK': 'green', 'ELECTION': 'purple'}
            ax.plot(midpoint[0], midpoint[1], marker='o', color=packet_colors.get(p_type, 'black'), markersize=8)

    ax.text(0.98, 0.98, f"⏱️ Timer: {sim_time_seconds:.1f}s", 
            transform=ax.transAxes, fontsize=12, fontweight='bold',
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='black'))

    leader = sim.nodes[sim.leader_id]
    status_text = (
        f"HAVEN Network Merge | Phase: {sim.phase}\n"
        f"Leader Memory: {leader.leader_memory_count} New Nodes Registered"
    )
    ax.set_title(status_text, fontsize=12, fontweight="bold", pad=15)
    
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', label='Leader', markerfacecolor='#2ecc71', markersize=10),
        Line2D([0], [0], marker='o', color='w', label='Follower', markerfacecolor='#3498db', markersize=10),
        Line2D([0], [0], marker='o', color='w', label='Joining', markerfacecolor='#f1c40f', markersize=10),
        Line2D([0], [0], marker='o', color='w', label='Electing', markerfacecolor='#9b59b6', markersize=10),
        Line2D([0], [0], marker='o', color='w', label='PING/ACK', markerfacecolor='red', markersize=7),
        Line2D([0], [0], marker='o', color='w', label='Election Packet', markerfacecolor='purple', markersize=7),
    ]
    ax.legend(handles=legend_elements, loc='lower left', fontsize=9, bbox_to_anchor=(0, -0.1), ncol=3)
    ax.axis("off")

# Increased frames to 100 to allow time for the new election sequence to finish visually
ani = animation.FuncAnimation(fig, update, interval=400, repeat=False, frames=100)
plt.tight_layout()
plt.show()