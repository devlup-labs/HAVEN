import socket
import threading

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

def send_data():
    while True:
        message = input()

        if message:
            conn.sendall(message.encode())

receive_thread = threading.Thread(target=receive_data)
send_thread = threading.Thread(target=send_data)

receive_thread.start()
send_thread.start()