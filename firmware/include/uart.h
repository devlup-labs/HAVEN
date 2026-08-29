#ifndef HAVEN_UART_H
#define HAVEN_UART_H

#include <stdint.h>

void uart_init(void);
void uart_putchar(char c);
void uart_print(const char *s);

#endif
