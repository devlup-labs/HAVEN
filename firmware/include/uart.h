#ifndef HAVEN_UART_H
#define HAVEN_UART_H

#include <stdint.h>
#include <stddef.h>

void uart_init(void);
void uart_putchar(char c);
void uart_print(const char *s);
char uart_getchar(void);

void uart_transmit(const uint8_t *data, size_t len);
int uart_receive(uint8_t *buffer, size_t max_len);
int uart_try_getchar(char *c);

#endif
