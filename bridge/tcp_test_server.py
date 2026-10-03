import socket
import threading
import os, hmac, hashlib, struct, time   # added

HOST = "127.0.0.1"
PORT = 5000
BUFFER_SIZE = 4096


server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server.bind((HOST, PORT))
server.listen(1)

print(f"[server] listening on {HOST}:{PORT}", flush=True)

conn, addr = server.accept()

print(f"[server] connection from {addr}", flush=True)

def receive_data():
    while True:
        data = conn.recv(BUFFER_SIZE)

        if not data:
            print("[server] connection closed", flush=True)
            break

        print(
            f"[server] received: {data!r}",
            flush=True
        )

def send_data():                                   # replaced
    while True:
        message = input()
        if not message:
            continue
        if message.startswith("hex:"):
            raw = bytes.fromhex(message[4:].replace(" ", ""))
        else:
            raw = (message + "\r\n").encode()
        print("[server] Sending message...", flush=True)
        conn.sendall(raw)
        print("[server] message sent", flush=True)

def fake_peer_frame():                             # added
    K = bytes(range(32)); pid = 2; spaces = bytes([7, 10, 19, 24, 37])
    body = bytes([pid]) + spaces + struct.pack('<I', 1)
    payload = body + hmac.new(K, body, hashlib.sha256).digest()[:8]
    return bytes([0xA5, 1, len(payload), pid, 0xFF]) + payload

def fake_peer():                                   # added
    end = time.time() + 15
    while time.time() < end:
        conn.sendall(fake_peer_frame())
        time.sleep(0.4)

if os.environ.get("HAVEN_FAKE_PEER"):              # added
    threading.Thread(target=fake_peer, daemon=True).start()

receive_thread = threading.Thread(target=receive_data)
send_thread = threading.Thread(target=send_data)

receive_thread.start()
send_thread.start()