#include "haven_config.h"

void node_config_load(void)
{
    g_cfg.id = 1;                                        /* TODO: per-node source */
    static const uint8_t spaces[HAVEN_NUM_SPACES] = {5, 17, 24, 29, 45};  /* from main.c spaces_a */
    for (int i = 0; i < HAVEN_NUM_SPACES; i++) g_cfg.spaces[i] = spaces[i];
    for (int i = 0; i < 32; i++) g_cfg.k_master[i] = (uint8_t)i;          /* from main.c key[] */
    g_cfg.battery_pct = 100;                             /* TODO: source */
}
