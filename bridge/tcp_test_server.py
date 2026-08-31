import socket

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

while True:
    data = conn.recv(BUFFER_SIZE)

    if not data:
        print("[server] connection closed", flush=True)
        break

    print(
        f"[server] received: {data!r}",
        flush=True
    )