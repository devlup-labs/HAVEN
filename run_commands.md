# Run GUI Visualizer Studio

### Start Web GUI (Simulation Controller & Live Network Graph)
../HAVEN -> ```./start_gui.sh```
(Or with custom port: `./start_gui.sh --port 8080`)

Then open **http://localhost:8080** in your browser.
- Interactive network canvas with live flying packet animations
- Start / Pause / Step / Reset controls
- Fast discrete-event simulation or full Renode + ns-3 hardware co-simulation
- Real-time fault injection (link drop, node crash, battery drain)
- Live node inspector with TurboBlom key spaces and authenticated neighbors
- Packet chronicle & serial log console

---

# Run full system (CLI)

### first time running
../HAVEN -> ```chmod +x start_haven.sh``` 

above command only needs to be executed once, then run:

../HAVEN -> ```./start_haven.sh```

---

# For individual testing

### build
../firmware -> ```./build.sh```

### run renode
../HAVEN -> ```renode renode/haven.resc```

### To check for pty endpoint connection that has been created
../HAVEN -> ```ls -l /tmp/haven_uart```


### To check for data that has been sent into uart and pty endpoint
../HAVEN -> ```cat /dev/pts/X```
(X derived from above command)

### To check the data that has reached the tcp bridge
../Haven/bridge -> ```python3 uart_tcp_bridge.py```

### To check the data that has reached the tcp server(to be replaced by ns3)
../Haven/bridge -> ```python3 tcp_test_server.py```