# Run Multi-Node HAVEN System

### Running the Full System (Default: 5 nodes)
```bash
./start_haven.sh
```

### Running with a Custom Number of Nodes (e.g. 5, 8, etc.)
```bash
./start_haven.sh 5
```

---

# For Individual Component Testing

### 1. Build Firmware
```bash
cd firmware && ./build.sh
```

### 2. Generate Renode Topology for N Nodes
```bash
python3 renode/generate_network.py 5
```
This generates `renode/haven.resc` instantiating machines `haven_1` to `haven_5` with dedicated UART PTY endpoints:
- `/tmp/haven_uart_1`
- `/tmp/haven_uart_2`
- ...
- `/tmp/haven_uart_5`

### 3. Start Renode
```bash
renode renode/haven.resc
```

### 4. Check PTY Endpoints
```bash
ls -l /tmp/haven_uart_*
```

### 5. Multi-Node Network Server Options

#### Option A: Built-in Multi-Node Wireless Mesh Server (TCP)
```bash
cd bridge && python3 tcp_test_server.py 5
```
Simulates wireless broadcast medium across ports `5001..5005`. Any packet transmitted by node $i$ is relayed to all other nodes.

#### Option B: ns-3 Wireless Simulation Bridge (IEEE 802.15.4 LR-WPAN)
Copy `bridge/haven_ns3_bridge.cc` into your ns-3 `scratch/` directory:
```bash
# In your ns-3 directory:
cp ../kuppa/bridge/haven_ns3_bridge.cc scratch/
./ns3 run "scratch/haven_ns3_bridge --nNodes=5 --distance=25"
```
Simulates true 802.15.4 wireless propagation, distance-based attenuation, path loss, and collisions across ports `5001..5005`.

### 6. Start Multi-Node UART <-> TCP Bridge
```bash
cd bridge && python3 uart_tcp_bridge.py 5
```
Bridges each `/tmp/haven_uart_X` PTY to port `5000 + X`.