#include "uart.h"
#include <stdint.h>

#define UART_BASE 0x40004400UL

/* STM32 USART2 registers */
#define USART_CR1 (*(volatile uint32_t *)(UART_BASE + 0x00))
#define USART_BRR (*(volatile uint32_t *)(UART_BASE + 0x0C))
#define USART_ISR (*(volatile uint32_t *)(UART_BASE + 0x1C))
#define USART_TDR (*(volatile uint32_t *)(UART_BASE + 0x28))

/* CR1 bits */
#define USART_CR1_UE (1U << 0)
#define USART_CR1_TE (1U << 3)

/* ISR bits */
#define USART_ISR_TXE_TXFNF (1U << 7)

void uart_init(void)
{
    /*
     * Enable USART and transmitter.
     *
     * BRR is intentionally left at its reset value for this
     * first Renode bring-up test.
     */
    USART_CR1 = USART_CR1_UE | USART_CR1_TE;
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