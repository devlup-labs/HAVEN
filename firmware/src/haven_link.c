#include "haven_link.h"
#include "uart.h"
#define SOF 0xA5
void link_send(uint8_t dst, uint8_t type, const uint8_t *p, uint8_t len)
{
    uint8_t h[5] = { SOF, type, len, g_cfg.id, dst };
    uart_transmit(h, 5);
    uart_transmit(p, len);
}
int link_poll(frame_t *out)
{
    static uint8_t st, idx; static frame_t f; char c;
    while (uart_try_getchar(&c)) {
        uint8_t b = (uint8_t)c;
        switch (st) {
        case 0: if (b == SOF) st = 1; break;
        case 1: f.type = b; st = 2; break;
        case 2: if (b > HAVEN_MAX_PAYLOAD) { st = 0; break; } f.len = b; st = 3; break;
        case 3: f.src = b; st = 4; break;
        case 4: f.dst = b; idx = 0;
                if (f.len == 0) { st = 0; *out = f; return 1; }
                st = 5; break;
        case 5: f.payload[idx++] = b;
                if (idx == f.len) { st = 0; *out = f; return 1; }
                break;
        }
    }
    return 0;
}