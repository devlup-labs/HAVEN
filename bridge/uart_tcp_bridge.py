import socket
import sys
import time

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


def main():
    uart = open_uart()
    tcp = connect_tcp()

    print("[bridge] UART <-> TCP bridge running", flush=True)

    try:
        while True:
            data = uart.read(BUFFER_SIZE)

            if data:
                print(
                    f"[bridge] UART -> TCP: {data!r}",
                    flush=True
                )
                tcp.sendall(data)

    except KeyboardInterrupt:
        print("\n[bridge] stopping", flush=True)

    finally:
        uart.close()
        tcp.close()


if __name__ == "__main__":
    main()