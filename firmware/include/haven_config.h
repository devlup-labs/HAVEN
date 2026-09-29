#ifndef HAVEN_CONFIG_H
#define HAVEN_CONFIG_H
#include <stdint.h>

#define HAVEN_CPU_HZ          16000000UL  /* haven.repl systickFrequency */
#define HAVEN_NUM_SPACES      5           /* main.c test uses 5 */
#define HAVEN_KEY_LEN         16          /* keyFinal[16] in main.c */
#define HAVEN_REPLAY_WINDOW_S 10          /* pseudocode */

/* ---- TODO: not defined anywhere, fill in ---- */
#define HAVEN_MAX_ADJ_NODES   8
#define HAVEN_TAG_LEN         16          /* truncated HMAC length */
#define HAVEN_HASH_LEN        8           /* discovery hash length */
#define HAVEN_ECHO_THRESHOLD  2
#define HAVEN_T_CLAIM_MS      5000
#define HAVEN_T_WINDOW_MS     5000
#define HAVEN_EPOCH_MS        1000
#define HAVEN_L_WEIGHT        1
#define HAVEN_M_WEIGHT        1
#define HAVEN_PRNG_A          1664525ULL
#define HAVEN_PRNG_B          1013904223ULL
#define HAVEN_PRNG_M          4294967296ULL

#define HAVEN_ID_NONE         0xFF        /* also broadcast; node id 0xFF reserved */
#define HAVEN_MAX_PAYLOAD     64

typedef struct {
    uint8_t id;
    uint8_t spaces[HAVEN_NUM_SPACES];
    uint8_t k_master[32];
    uint8_t battery_pct;
} node_config_t;

extern node_config_t g_cfg;
void node_config_load(void);   /* TODO: how does each node get id/spaces/K_master/battery? */

#define HAVEN_LOG(...) ((void)0) /* UART is the radio channel; don't print on it */
#endif