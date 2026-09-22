#include "crypto.h"
#include "turboblom.h"
#include "uart.h"
#include "neighbor_table.h"
#include "protocol.h"
#include <stdint.h>
#include <stddef.h>

void uart_print_hex(const uint8_t *buf, size_t len)
{
    static const char hex_chars[] = "0123456789abcdef";

    for (size_t i = 0; i < len; i++)
    {
        uart_putchar(hex_chars[(buf[i] >> 4) & 0xF]);
        uart_putchar(hex_chars[buf[i] & 0xF]);
    }
    uart_putchar('\n');
}

int main(void)
{
    uart_init();
    NeighborTable_Init();

    // UART transmit testing
    const uint8_t message[] = "UART boot OK\r\n";
    uart_transmit(message, sizeof(message) - 1);

    // HMAC testing
    uint8_t key[32] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31};
    uint8_t msg[] = "HAVEN test";
    uint8_t out[32];

    haven_hmac(key, 32, msg, 10, out);
    uart_print("HMAC Key:  ");
    uart_print_hex(out, 16);

    // Protocol testing: Build and SEND a message over the network
    PresenceHeartbeat_t hb;
    protocol_build_presence_hb(&hb, 42, 1, 100);
    uart_print("Presence HB built (Node: 42, Leader: 1). Transmitting to network...\r\n");
    
    // Transmit the raw packet bytes over UART. 
    // The Python bridge picks this up and injects it into the NS-3 WiFi simulation!
    uart_transmit((uint8_t*)&hb, sizeof(PresenceHeartbeat_t));

    // Idle Loop
    while (1)
        ;
    return 0;
}
