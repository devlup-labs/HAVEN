import socket
import sys
import time
import threading

UART_DEVICE = "/tmp/haven_uart"
TCP_HOST = "127.0.0.1"
TCP_PORT = 5000

RETRY_SECONDS = 0.5
BUFFER_SIZE = 4096


def connect_tcp():
    while True:
        try:
            print(
                f"[bridge] connecting to {TCP_HOST}:{TCP_PORT}...",
                flush=True
            )

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((TCP_HOST, TCP_PORT))

            print("[bridge] TCP connected", flush=True)
            return sock

        except ConnectionRefusedError:
            print(
                "[bridge] TCP server not available, retrying...",
                flush=True
            )
            time.sleep(RETRY_SECONDS)

def open_uart():
    while True:
        try:
            print(
                f"[bridge] opening UART {UART_DEVICE}...",
                flush=True
            )

            uart = open(UART_DEVICE, "r+b", buffering=0)

            print("[bridge] UART opened", flush=True)
            return uart

        except FileNotFoundError:
            print(
                "[bridge] UART device not available, retrying...",
                flush=True
            )
            time.sleep(RETRY_SECONDS)

def tcp_to_uart(tcp, uart):
    while True:
        data = tcp.recv(BUFFER_SIZE)

        if not data:
            print("[bridge] TCP connection closed", flush=True)
            break

        print(
            f"[bridge] TCP -> UART: {data!r}",
            flush=True
        )

        uart.write(data)

def uart_to_tcp(uart, tcp):
    while True:
        data = uart.read(BUFFER_SIZE)

        if data:
            print(
                f"[bridge] UART -> TCP: {data!r}",
                flush=True
            )
            tcp.sendall(data)


def main():
    uart = open_uart()
    tcp = connect_tcp()

    print("[bridge] UART <-> TCP bridge running", flush=True)

    #creating threads(so that we can do read and write simultaneously)
    uart_to_tcp_thread = threading.Thread(
        target=uart_to_tcp,
        args=(uart, tcp)
    )

    tcp_to_uart_thread = threading.Thread(
        target=tcp_to_uart,
        args=(tcp, uart)
    )

    uart_to_tcp_thread.start()
    tcp_to_uart_thread.start()

    try:
        uart_to_tcp_thread.join()
        tcp_to_uart_thread.join()

    except KeyboardInterrupt:
        print("\n[bridge] stopping", flush=True)

    finally:
        uart.close()
        tcp.close()


if __name__ == "__main__":
    main()