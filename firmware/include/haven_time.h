#include <stdint.h>
void     time_init(void);
uint32_t time_ms(void);   /* must be called more often than every 1 ms of sim time */