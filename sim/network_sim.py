import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import random
import math

# --- Simulation Parameters ---
NUM_NODES = 500
BROADCAST_INTERVAL = 2      
TIMEOUT_LIMIT = 5           
FAIL_PROB = 0.005            
RECOVER_PROB = 0.06         

class Node:
    def __init__(self, node_id, physical_neighbors):
        self.id = node_id
        self.physical_neighbors = physical_neighbors 
        self.active_neighbors = list(physical_neighbors) 
        self.last_heard = {n: 0 for n in physical_neighbors}
        self.is_active = True

    def update_status(self, current_time):
        if self.is_active:
            if random.random() < FAIL_PROB:
                self.is_active = False
                self.active_neighbors = []
        else:
            if random.random() < RECOVER_PROB:
                self.is_active = True
                self.last_heard = {}

    def broadcast(self, nodes_dict, current_time):
        if not self.is_active: 
            return
            
        for n_id in self.physical_neighbors:
            target = nodes_dict[n_id]
            if target.is_active:
                target.receive_broadcast(self.id, current_time)

    def receive_broadcast(self, sender_id, current_time):
        self.last_heard[sender_id] = current_time
        if sender_id not in self.active_neighbors:
            self.active_neighbors.append(sender_id)

    def check_neighbors_and_ping(self, nodes_dict, current_time):
        if not self.is_active: 
            return
            
        for n_id in list(self.active_neighbors):
            time_since_last_msg = current_time - self.last_heard.get(n_id, 0)
            if time_since_last_msg > TIMEOUT_LIMIT:
                target = nodes_dict[n_id]
                if target.is_active:
                    self.last_heard[n_id] = current_time
                else:
                    self.active_neighbors.remove(n_id)

# --- Network Initialization ---
G = nx.Graph()
G.add_nodes_from(range(NUM_NODES))
pos = {i: (random.random(), random.random()) for i in range(NUM_NODES)}

TARGET_CONNECTIONS = 4
for i in range(NUM_NODES):
    distances = []
    for j in range(NUM_NODES):
        if i != j:
            dist = math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
            distances.append((dist, j))
    
    distances.sort()
    for dist, j in distances[:TARGET_CONNECTIONS]:
        G.add_edge(i, j)

nodes = {i: Node(i, list(G.neighbors(i))) for i in range(NUM_NODES)}

print("\n=== WSN Search Parameters Setup ===")
try:
    SEARCH_TIME = int(input("Enter simulation tick to trigger search (e.g., 20): "))
    SOURCE_NODE = int(input(f"Enter SOURCE node ID (0 to {NUM_NODES-1}): "))
    TARGET_NODE = int(input(f"Enter TARGET node ID (0 to {NUM_NODES-1}): "))
except ValueError:
    print("Invalid input detected! Defaulting to: Tick=20, Source=0, Target=10")
    SEARCH_TIME = 20
    SOURCE_NODE = 0
    TARGET_NODE = 10

fig, ax = plt.subplots(figsize=(10, 8))
plt.subplots_adjust(left=0, right=1, bottom=0, top=0.93)
fig.canvas.manager.set_window_title('Tick-by-Tick Search Routing Simulation')

# --- Global Search State ---
search_state = {
    'started': False,
    'finished': False,
    'visited': {},       # Tracks {node: parent_node} to reconstruct path
    'frontier': [],      # Nodes currently exploring
    'final_path': []
}

def update(frame):
    ax.clear()
    current_time = frame
    
    # 1. State changes
    for n in nodes.values():
        n.update_status(current_time)
        
    # 2. Routine Broadcasts
    if current_time % BROADCAST_INTERVAL == 0:
        for n in nodes.values():
            n.broadcast(nodes, current_time)
            
    # 3. Timeouts & Pings
    for n in nodes.values():
        n.check_neighbors_and_ping(nodes, current_time)
        
    # Extract currently active logical edges
    active_edges = []
    for n in nodes.values():
        if n.is_active:
            for neighbor_id in n.active_neighbors:
                if n.id in nodes[neighbor_id].active_neighbors:
                    edge = tuple(sorted((n.id, neighbor_id)))
                    if edge not in active_edges:
                        active_edges.append(edge)

    # --- TICK-BY-TICK SEARCH LOGIC ---
    search_status = ""
    
    # Trigger search start
    if current_time == SEARCH_TIME:
        if nodes[SOURCE_NODE].is_active:
            search_state['started'] = True
            search_state['visited'] = {SOURCE_NODE: None}
            search_state['frontier'] = [SOURCE_NODE]
        else:
            search_status = f" | Search Failed: Source ({SOURCE_NODE}) is Offline!"
            search_state['finished'] = True

    # Advance search one hop (tick)
    if search_state['started'] and not search_state['finished']:
        next_frontier = []
        
        # Check if target is found in the current frontier
        if TARGET_NODE in search_state['frontier']:
            search_state['finished'] = True
            # Trace back path using the visited dictionary
            path = []
            curr = TARGET_NODE
            while curr is not None:
                path.append(curr)
                curr = search_state['visited'][curr]
            search_state['final_path'] = path[::-1]
            search_status = f" | Path Found: {' -> '.join(map(str, search_state['final_path']))}"
        else:
            # Expand to active neighbors
            for current_node in search_state['frontier']:
                if not nodes[current_node].is_active:
                    continue 
                
                for neighbor in nodes[current_node].active_neighbors:
                    # Verify bidirectional link
                    if current_node in nodes[neighbor].active_neighbors:
                        if neighbor not in search_state['visited']:
                            search_state['visited'][neighbor] = current_node
                            next_frontier.append(neighbor)
            
            search_state['frontier'] = list(set(next_frontier)) # Remove duplicates
            
            # If frontier is empty but we haven't found target, search failed
            if not search_state['frontier'] and not search_state['finished']:
                search_state['finished'] = True
                search_status = " | Search Failed: Target unreachable."
            else:
                search_status = " | Searching..."

    # Preserve status text once finished
    if search_state['finished'] and search_state['final_path']:
        search_status = f" | Path Found: {' -> '.join(map(str, search_state['final_path']))}"
    elif search_state['finished'] and not search_state['final_path'] and current_time >= SEARCH_TIME:
         search_status = " | Search Failed or Ended."

    # --- NODE COLORING LOGIC ---
    node_colors = []
    
    for n_id in range(NUM_NODES):
        if not nodes[n_id].is_active:
            node_colors.append('#e31a1c')  # Red: Failed node
            continue
            
        # Target node always Yellow after search starts (so user can see destination)
        if current_time >= SEARCH_TIME and n_id == TARGET_NODE:
            node_colors.append('#ffff99')
            continue

        if n_id == SOURCE_NODE and current_time >= SEARCH_TIME:
            node_colors.append('#33a02c')  # Green: Source node
        elif search_state['finished'] and n_id in search_state['final_path']:
            node_colors.append('#1f78b4')  # Blue: Confirmed final path
        elif not search_state['finished'] and n_id in search_state['visited']:
            node_colors.append('#a6cee3')  # Light Blue: Currently searching / visited
        else:
            node_colors.append('#b2df8a' if current_time < SEARCH_TIME else '#a9a9a9')

    ax.set_title(
        f"Tick: {current_time} | Active Nodes: {sum(1 for n in nodes.values() if n.is_active)}/{NUM_NODES}{search_status}",
        fontsize=11
    )

    nx.draw_networkx_edges(G, pos, ax=ax, edge_color='#e0e0e0', style='dashed')
    
    # Highlight edges differently based on search state
    if search_state['final_path']:
        path = search_state['final_path']
        path_edges = [(path[i], path[i+1]) for i in range(len(path)-1)]
        path_edges_set = {tuple(sorted(pe)) for pe in path_edges}
        
        nx.draw_networkx_edges(G, pos, edgelist=path_edges, ax=ax, edge_color='#1f78b4', width=3.5)
        other_active_edges = [e for e in active_edges if tuple(sorted(e)) not in path_edges_set]
        nx.draw_networkx_edges(G, pos, edgelist=other_active_edges, ax=ax, edge_color='#e0e0e0', width=1.0)
    else:
        # Before completion, show all active links
        nx.draw_networkx_edges(G, pos, edgelist=active_edges, ax=ax, edge_color='#a6cee3', width=1.5)
    
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, ax=ax, node_size=550)
    nx.draw_networkx_labels(G, pos, ax=ax, font_color='black', font_weight='bold')
    
    ax.axis('off')

# Keep interval a little slower (150ms) so you can actually watch the packet propagate
ani = animation.FuncAnimation(fig, update, frames=range(1, 10000), interval=150, repeat=False)

plt.show()