#include "haven_time.h"
#include "haven_config.h"
#define SYST_CSR (*(volatile uint32_t *)0xE000E010UL)
#define SYST_RVR (*(volatile uint32_t *)0xE000E014UL)
#define SYST_CVR (*(volatile uint32_t *)0xE000E018UL)
#define SYST_ENABLE    (1u << 0)
#define SYST_CLKSOURCE (1u << 2)
#define SYST_COUNTFLAG (1u << 16)
static uint32_t ms;

void time_init(void)
{
    SYST_RVR = (HAVEN_CPU_HZ / 1000u) - 1u;
    SYST_CVR = 0;
    SYST_CSR = SYST_ENABLE | SYST_CLKSOURCE;
}
uint32_t time_ms(void)
{
    if (SYST_CSR & SYST_COUNTFLAG) ms++;   /* the read clears COUNTFLAG */
    return ms;
}