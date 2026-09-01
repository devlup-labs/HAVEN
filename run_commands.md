# Run full system

### first time running
../HAVEN -> ```chmod +x start_haven.sh``` 

above command only needs to be executed once, then run:

../HAVEN -> ```./start_haven.sh```

---

### build
../firmware -> ```./build.sh```

### run
../HAVEN -> ```renode renode/haven.resc```

### To check for pty endpoint connection that has been created
../HAVEN -> ```ls -l /tmp/haven_uart```


### To check for data that has been sent into uart and pty endpoint
../HAVEN -> ```cat /dev/pts/X```
(X derived from above command)

### To check the data that has reached the tcp bridge
../Haven/bridge -> python3 uart_tcp_bridge.py

### To check the data that has reached the tcp server(to be replaced by ns3)
../Haven/bridge -> python3 tcp_test_server.py