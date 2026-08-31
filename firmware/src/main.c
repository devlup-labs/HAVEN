#include "crypto.h"
#include "turboblom.h"
#include "uart.h"
#include <stdint.h>
#include <stddef.h>


void uart_print_hex(const uint8_t *buf, size_t len)
{
    static const char hex_chars[] = "0123456789abcdef";

    for (size_t i = 0; i < len; i++) {
        uart_putchar(hex_chars[(buf[i] >> 4) & 0xF]);
        uart_putchar(hex_chars[ buf[i]       & 0xF]);
    }
    uart_putchar('\n');
}


int main(void) {
    //Test uart_init and uart_print
    uart_init();
    uart_print("UART boot OK\r\n");


    //HMAC testing
    uint8_t key[32] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};   
    uint8_t msg[]   = "HAVEN test";
    uint8_t out[32];

    haven_hmac(key, 32, msg, 10, out);
    uart_print("HMAC Key:  ");
    uart_print_hex(out, 16);

    // Turboblom testing
    uint8_t spaces_a[5] = {5, 17, 24, 29, 45};
    uint8_t spaces_b[5] = {7, 10, 19, 24, 37};
    uint8_t keyFinal[16];

    if (compute_K_AB(1, 2, key, spaces_a, spaces_b, 5, keyFinal) == 0) {
        uart_print("Hex Key:   ");
        uart_print_hex(keyFinal, 16);
    }

    // Idle Loop
    while(1);
    return 0;
}


