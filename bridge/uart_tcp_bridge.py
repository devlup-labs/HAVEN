import socket
import sys
import time
import threading
import argparse

RETRY_SECONDS = 0.5
BUFFER_SIZE = 4096


def connect_tcp(host, port, node_id):
    while True:
        try:
            print(
                f"[bridge-{node_id}] connecting to {host}:{port}...",
                flush=True
            )

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))

            print(f"[bridge-{node_id}] TCP connected", flush=True)
            return sock

        except ConnectionRefusedError:
            print(
                f"[bridge-{node_id}] TCP server not available, retrying...",
                flush=True
            )
            time.sleep(RETRY_SECONDS)

def open_uart(uart_device, node_id):
    while True:
        try:
            print(
                f"[bridge-{node_id}] opening UART {uart_device}...",
                flush=True
            )

            uart = open(uart_device, "r+b", buffering=0)

            print(f"[bridge-{node_id}] UART opened", flush=True)
            return uart

        except FileNotFoundError:
            print(
                f"[bridge-{node_id}] UART device not available, retrying...",
                flush=True
            )
            time.sleep(RETRY_SECONDS)

def tcp_to_uart(tcp, uart, node_id):
    while True:
        data = tcp.recv(BUFFER_SIZE)

        if not data:
            print(f"[bridge-{node_id}] TCP connection closed", flush=True)
            break

        print(
            f"[bridge-{node_id}] TCP -> UART: {data!r}",
            flush=True
        )

        uart.write(data)

def uart_to_tcp(uart, tcp, node_id):
    try:
        while True:
            data = uart.read(BUFFER_SIZE)
            if data:
                print(f"[bridge-{node_id}] UART -> TCP: {data!r}", flush=True)
                tcp.sendall(data)
    except OSError:
        print(f"[bridge-{node_id}] UART closed", flush=True)


def main():
    parser = argparse.ArgumentParser(description="UART to TCP Bridge for HAVEN")
    parser.add_argument("--uart", default="/tmp/haven_uart", help="Path to UART device")
    parser.add_argument("--host", default="127.0.0.1", help="TCP Host")
    parser.add_argument("--port", type=int, default=5000, help="TCP Port")
    parser.add_argument("--node-id", type=int, default=1, help="Node ID for logging")
    args = parser.parse_args()

    uart = open_uart(args.uart, args.node_id)
    tcp = connect_tcp(args.host, args.port, args.node_id)

    print(f"[bridge-{args.node_id}] UART <-> TCP bridge running on {args.uart} <-> {args.host}:{args.port}", flush=True)

    uart_to_tcp_thread = threading.Thread(
        target=uart_to_tcp,
        args=(uart, tcp, args.node_id)
    )

    tcp_to_uart_thread = threading.Thread(
        target=tcp_to_uart,
        args=(tcp, uart, args.node_id)
    )

    uart_to_tcp_thread.start()
    tcp_to_uart_thread.start()

    try:
        uart_to_tcp_thread.join()
        tcp_to_uart_thread.join()

    except KeyboardInterrupt:
        print(f"\n[bridge-{args.node_id}] stopping", flush=True)

    finally:
        uart.close()
        tcp.close()


if __name__ == "__main__":
    main()