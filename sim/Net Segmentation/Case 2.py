import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import random

# --- Simulation Parameters ---
TOTAL_NODES = 50
NEAREST_NEIGHBORS = 4
SEARCH_TIMEOUT = 8

class SegmentNode:
    def __init__(self, node_id, is_leader=False):
        self.id = node_id
        self.is_leader = is_leader
        self.state = "LEADER" if is_leader else "IDLE" 
        # States: IDLE, LEADER, INITIATOR, SEARCHING, INTERSECTION
        
        self.seen_initiators = set()
        self.search_timer = 10

class RedundantSearchSimulation:
    def __init__(self, n_nodes, k_neighbors, timeout):
        self.n_nodes = n_nodes
        self.k_neighbors = k_neighbors
        self.timeout = timeout
        
        # Build Topology: Random physical placement with KNN connections
        self.graph = nx.Graph()
        self.pos = {i: (random.uniform(0, 100), random.uniform(0, 100)) for i in range(self.n_nodes)}
        
        for i in range(self.n_nodes):
            self.graph.add_node(i)
            
        for i in range(self.n_nodes):
            distances = []
            for j in range(self.n_nodes):
                if i != j:
                    dist = np.linalg.norm(np.array(self.pos[i]) - np.array(self.pos[j]))
                    distances.append((dist, j))
            distances.sort()
            for _, neighbor in distances[:self.k_neighbors]:
                self.graph.add_edge(i, neighbor)
                
        # Pick a random edge to break
        self.broken_link = random.choice(list(self.graph.edges()))
        
        # Pick a random leader
        leader_id = random.choice(list(self.graph.nodes()))
        self.nodes = {i: SegmentNode(i, is_leader=(i == leader_id)) for i in range(n_nodes)}
        
        self.phase = "CONNECTED"
        self.msg_queue = []
        self.frame_count = 0
        self.initiators = []
        self.intersection_node = None

    def step(self):
        if self.phase == "CONNECTED":
            self.frame_count += 1
            if self.frame_count > 3: # Break link after a brief pause
                self.phase = "LINK_BROKEN"
                self.graph.remove_edge(*self.broken_link)
                
                n1, n2 = self.broken_link
                self.initiators = [n1, n2]
                
                # Initiators start search
                for init_id in self.initiators:
                    target_id = n2 if init_id == n1 else n1
                    node = self.nodes[init_id]
                    node.state = "INITIATOR"
                    node.seen_initiators.add(init_id)
                    
                    # Broadcast search packet to neighbors
                    for neighbor in self.graph.neighbors(init_id):
                        self.msg_queue.append({
                            "sender": init_id, "receiver": neighbor,
                            "type": "SEARCH", "initiator": init_id, "target": target_id
                        })
                
                self.phase = "SEARCH_PROPAGATING"

        elif self.phase == "SEARCH_PROPAGATING":
            next_queue = []
            
            for msg in self.msg_queue:
                recv_id = msg["receiver"]
                recv_node = self.nodes[recv_id]
                
                if msg["type"] == "SEARCH":
                    init_id = msg["initiator"]
                    
                    if init_id not in recv_node.seen_initiators:
                        recv_node.seen_initiators.add(init_id)
                        
                        # Intersection Condition: Node received packets from BOTH disconnected nodes
                        if len(recv_node.seen_initiators) == 2:
                            print(f"Intersection at Node {recv_id}. Alternate path proven!")
                            recv_node.state = "INTERSECTION"
                            self.intersection_node = recv_id
                            self.phase = "RESOLVED_INTACT"
                            self.msg_queue = [] # Purge queue to terminate search instantly
                            return

                        if recv_node.is_leader:
                            next_queue.append({
                                "sender": recv_id, "receiver": msg["sender"],
                                "type": "LEADER_ACK", "initiator": init_id
                            })
                        else:
                            if recv_node.state == "IDLE":
                                recv_node.state = "SEARCHING"
                            # Forward search to neighbors
                            for neighbor in self.graph.neighbors(recv_id):
                                if neighbor != msg["sender"]:
                                    next_queue.append({
                                        "sender": recv_id, "receiver": neighbor,
                                        "type": "SEARCH", "initiator": init_id, "target": msg["target"]
                                    })
                                    
            self.msg_queue = next_queue

# --- Visualization Setup ---
sim = RedundantSearchSimulation(n_nodes=TOTAL_NODES, k_neighbors=NEAREST_NEIGHBORS, timeout=SEARCH_TIMEOUT)
fig, ax = plt.subplots(figsize=(10, 10))

def get_node_color(state):
    colors = {
        "LEADER": "#2ecc71",       # Green
        "IDLE": "#95a5a6",         # Grey
        "INITIATOR": "#f1c40f",    # Yellow
        "SEARCHING": "#3498db",    # Blue
        "INTERSECTION": "#9b59b6"  # Purple (Intersection Found)
    }
    return colors.get(state, "#95a5a6")

def update(frame):
    ax.clear()
    sim.step()
    
    node_colors = [get_node_color(sim.nodes[i].state) for i in sim.graph.nodes()]
    
    # Draw Graph
    nx.draw_networkx_edges(sim.graph, sim.pos, ax=ax, alpha=0.3, edge_color="gray")
    nx.draw_networkx_nodes(sim.graph, sim.pos, ax=ax, node_color=node_colors, node_size=250)
    
    labels = {i: f"{i}" for i in sim.graph.nodes()}
    nx.draw_networkx_labels(sim.graph, sim.pos, labels=labels, font_size=8, ax=ax, font_color="white")
    
    # Highlight Broken Link Placeholder (Red dashed line)
    if sim.phase != "CONNECTED":
        p1 = sim.pos[sim.broken_link[0]]
        p2 = sim.pos[sim.broken_link[1]]
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color="red", linestyle="--", linewidth=2.0, alpha=0.7)
    
    # Draw Messages
    for msg in sim.msg_queue:
        sender, receiver = msg["sender"], msg["receiver"]
        p1 = np.array(sim.pos[sender])
        p2 = np.array(sim.pos[receiver])
        midpoint = 0.5 * p1 + 0.5 * p2
        
        ax.plot(midpoint[0], midpoint[1], marker='o', markersize=5, color="cyan")

    # UI Details
    status_text = f"Phase: {sim.phase} | Frame: {frame}\n"
    if sim.phase == "CONNECTED":
        status_text += "Network intact. Random KNN topology active."
    elif sim.phase == "LINK_BROKEN":
        status_text += f"Link N{sim.broken_link[0]}-N{sim.broken_link[1]} Broken! Initiating Search."
    elif sim.phase == "SEARCH_PROPAGATING":
        status_text += "Initiators (Yellow) sending Search Packets (Cyan)"
    elif sim.phase == "RESOLVED_INTACT":
        status_text += f"SEARCH TERMINATED! Node {sim.intersection_node} (Purple) proved connection intact."

    ax.set_title(status_text, fontsize=11, fontweight="bold")
    ax.axis("off")

ani = animation.FuncAnimation(fig, update, interval=400, repeat=False, cache_frame_data=False)
plt.show()