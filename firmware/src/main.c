#include "crypto.h"
#include <stdint.h>
#include <stddef.h>

static void haven_putchar(char c)
{
    __asm volatile (
        "mov r0, #0x03    \n"
        "mov r1, %0       \n"
        "bkpt 0xAB        \n"
        :
        : "r" (&c)
        : "r0", "r1"
    );
}

void haven_print_hex(const uint8_t *buf, size_t len)
{
    static const char hex_chars[] = "0123456789abcdef";

    for (size_t i = 0; i < len; i++) {
        haven_putchar(hex_chars[(buf[i] >> 4) & 0xF]);
        haven_putchar(hex_chars[ buf[i]       & 0xF]);
    }
    haven_putchar('\n');
}

static inline void haven_print(const char *s) {
    register int r0 asm("r0") = 4; // SYS_WRITE0
    register const char *r1 asm("r1") = s;
    asm volatile(
        "bkpt 0xAB"
        :
        : "r"(r0), "r"(r1)
        : "memory"
    );
}

int main(void) {
    haven_print("HAVEN boot\n");
    uint8_t key[32] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31};   
    uint8_t msg[]   = "HAVEN test";
    uint8_t out[32];
    haven_hmac(key, 32, msg, 10, out);
    haven_print_hex(out, 16);
    while(1);
    return 0;
}


