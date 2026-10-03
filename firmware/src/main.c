#include "haven.h"
#include "haven_time.h"
#include "uart.h"
#include "haven_config.h"

int main(void)
{
    uart_init();
    time_init();
    node_config_load();   /* you implement: id, spaces, K_master, battery */
    haven_run();
    return 0;
}
