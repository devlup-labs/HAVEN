import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np

# --- Simulation Parameters ---
TOTAL_NODES = 50
SEARCH_TIMEOUT = 8

class SegmentNode:
    def __init__(self, node_id, is_leader=False):
        self.id = node_id
        self.is_leader = is_leader
        self.state = "LEADER" if is_leader else "IDLE" 
        # States: IDLE, LEADER, INITIATOR, SEARCHING, ORPHANED
        
        self.seen_initiators = set()
        self.search_timer = 0
        self.leader_found = False

class SegmentationSimulation:
    def __init__(self, n_nodes, timeout):
        self.n_nodes = n_nodes
        self.timeout = timeout
        self.half_n = n_nodes // 2
        
        # Build Topology: Two chordal rings connected by one link
        self.graph = nx.Graph()
        self.pos = {}
        
        # Group A (Left Ring)
        for i in range(self.half_n):
            self.graph.add_node(i)
            self.graph.add_edge(i, (i + 1) % self.half_n)
            self.graph.add_edge(i, (i + 2) % self.half_n) # Chord
            angle = 2 * np.pi * i / self.half_n
            self.pos[i] = (np.cos(angle) - 1.5, np.sin(angle))
            
        # Group B (Right Ring)
        for i in range(self.half_n, self.n_nodes):
            self.graph.add_node(i)
            offset_i = i - self.half_n
            self.graph.add_edge(i, self.half_n + (offset_i + 1) % self.half_n)
            self.graph.add_edge(i, self.half_n + (offset_i + 2) % self.half_n) # Chord
            angle = 2 * np.pi * offset_i / self.half_n
            self.pos[i] = (np.cos(angle) + 1.5, np.sin(angle))
            
        # The Bridge Link
        self.bridge = (self.half_n - 1, self.half_n)
        self.graph.add_edge(*self.bridge)
        
        # Initialize Nodes (Assign Leader to Group A arbitrarily)
        self.nodes = {i: SegmentNode(i, is_leader=(i == 0)) for i in range(n_nodes)}
        
        self.phase = "CONNECTED"
        self.msg_queue = []
        self.frame_count = 0
        self.initiators = []

    def step(self):
        if self.phase == "CONNECTED":
            self.frame_count += 1
            if self.frame_count > 3: # Break link after a brief pause
                self.phase = "LINK_BROKEN"
                self.graph.remove_edge(*self.bridge)
                
                n1, n2 = self.bridge
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
                            print(f"Intersection at Node {recv_id}. Network is still connected!")
                            self.phase = "RESOLVED"
                            return

                        if recv_node.is_leader:
                            # Leader found! Send ACK back towards initiator
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
                                    
                elif msg["type"] == "LEADER_ACK":
                    init_id = msg["initiator"]
                    if recv_id == init_id:
                        recv_node.leader_found = True
                        recv_node.state = "IDLE" # Search satisfied
                    else:
                        # Forward ACK back towards initiator (simplified routing)
                        for neighbor in self.graph.neighbors(recv_id):
                            # Pass to the neighbor that has seen the search from this initiator
                            if init_id in self.nodes[neighbor].seen_initiators:
                                next_queue.append({
                                    "sender": recv_id, "receiver": neighbor,
                                    "type": "LEADER_ACK", "initiator": init_id
                                })

            self.msg_queue = next_queue
            
            # Check Timeout for Initiators
            active_search = False
            for init_id in self.initiators:
                node = self.nodes[init_id]
                if node.state == "INITIATOR":
                    active_search = True
                    node.search_timer += 1
                    if node.search_timer >= self.timeout:
                        if not node.leader_found:
                            node.state = "ORPHANED"
                            # Trigger segment-wide election state
                            self.trigger_election(init_id)
            
            if not active_search:
                self.phase = "SEGMENTED"

    def trigger_election(self, source_id):
        """Flood the orphaned segment to switch to election mode."""
        visited = set([source_id])
        queue = [source_id]
        
        while queue:
            curr = queue.pop(0)
            if self.nodes[curr].state != "INITIATOR":
                self.nodes[curr].state = "ORPHANED"
            for neighbor in self.graph.neighbors(curr):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

# --- Visualization Setup ---
sim = SegmentationSimulation(n_nodes=TOTAL_NODES, timeout=SEARCH_TIMEOUT)
fig, ax = plt.subplots(figsize=(10, 6))

def get_node_color(state):
    colors = {
        "LEADER": "#2ecc71",     # Green
        "IDLE": "#95a5a6",       # Grey
        "INITIATOR": "#f1c40f",  # Yellow
        "SEARCHING": "#3498db",  # Blue
        "ORPHANED": "#e74c3c"    # Red (Starting Election)
    }
    return colors.get(state, "#95a5a6")

def update(frame):
    ax.clear()
    sim.step()
    
    node_colors = [get_node_color(sim.nodes[i].state) for i in sim.graph.nodes()]
    
    # Draw Graph
    nx.draw_networkx_edges(sim.graph, sim.pos, ax=ax, alpha=0.5, edge_color="gray")
    nx.draw_networkx_nodes(sim.graph, sim.pos, ax=ax, node_color=node_colors, node_size=500)
    
    labels = {i: f"N{i}" for i in sim.graph.nodes()}
    nx.draw_networkx_labels(sim.graph, sim.pos, labels=labels, font_size=8, ax=ax, font_color="white")
    
    # Draw Messages
    for msg in sim.msg_queue:
        sender, receiver = msg["sender"], msg["receiver"]
        p1 = np.array(sim.pos[sender])
        p2 = np.array(sim.pos[receiver])
        midpoint = 0.5 * p1 + 0.5 * p2
        
        color = "cyan" if msg["type"] == "SEARCH" else "lime"
        ax.plot(midpoint[0], midpoint[1], marker='o', markersize=6, color=color)

    # UI Details
    status_text = f"Phase: {sim.phase} | Frame: {frame}\n"
    if sim.phase == "CONNECTED":
        status_text += "Network intact. Bridge N9-N10 active."
    elif sim.phase == "LINK_BROKEN":
        status_text += "Link Broken! N9 and N10 detecting disconnect."
    elif sim.phase == "SEARCH_PROPAGATING":
        status_text += "Cyan: Search Packets | Green: Leader ACK"
    elif sim.phase == "SEGMENTED":
        status_text += "Search complete. Isolated segment triggered ELECTION (Red)."

    ax.set_title(status_text, fontsize=12, fontweight="bold")
    ax.axis("off")

ani = animation.FuncAnimation(fig, update, interval=600, repeat=False, cache_frame_data=False)

manager = plt.get_current_fig_manager()
manager.full_screen_toggle()

plt.show()