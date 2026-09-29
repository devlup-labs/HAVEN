#include "uart.h"
#include <stdint.h>

#define UART_BASE 0x40004400UL

/* STM32 USART2 registers */
#define USART_CR1 (*(volatile uint32_t *)(UART_BASE + 0x00))
#define USART_BRR (*(volatile uint32_t *)(UART_BASE + 0x0C))
#define USART_ISR (*(volatile uint32_t *)(UART_BASE + 0x1C))
#define USART_TDR (*(volatile uint32_t *)(UART_BASE + 0x28))
#define USART_RDR (*(volatile uint32_t *)(UART_BASE + 0x24))

/* CR1 bits */
#define USART_CR1_UE (1U << 0)
#define USART_CR1_TE (1U << 3)
#define USART_CR1_RE (1U << 2)

/* ISR bits */
#define USART_ISR_TXE_TXFNF (1U << 7)
#define USART_ISR_RXNE_RXFNE (1U << 5)

void uart_init(void)
{
    /*
     * Enable USART and transmitter.
     *
     * BRR is intentionally left at its reset value for this
     * first Renode bring-up test.
     */
    USART_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

void uart_putchar(char c)
{
    while ((USART_ISR & USART_ISR_TXE_TXFNF) == 0) {
    }

    USART_TDR = (uint32_t)c;
}

void uart_print(const char *s)
{
    while (*s) {
        uart_putchar(*s++);
    }
}


char uart_getchar(void)
{
    while ((USART_ISR & USART_ISR_RXNE_RXFNE) == 0) {
    }

    return (char)USART_RDR;
}

void uart_transmit(const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        uart_putchar((char)data[i]);
    }
}

int uart_receive(uint8_t *buffer, size_t max_len)
{
    size_t rx_len = 0;

    while (rx_len < max_len - 1) {
        char c = uart_getchar();

        if (c == '\n') {
            break;
        }

        if (c != '\r') {
            buffer[rx_len++] = (uint8_t)c;
        }
    }

    buffer[rx_len] = '\0';

    return (int)rx_len;
}

int uart_try_getchar(char *c)
{
    if ((USART_ISR & USART_ISR_RXNE_RXFNE) == 0) return 0;
    *c = (char)USART_RDR;
    return 1;
}