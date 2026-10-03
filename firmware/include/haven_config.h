#ifndef HAVEN_CONFIG_H
#define HAVEN_CONFIG_H
#include <stdint.h>

#define HAVEN_CPU_HZ          16000000UL  /* haven.repl systickFrequency */
#define HAVEN_NUM_SPACES      5           /* k: spaces per node */
#define HAVEN_KEY_LEN         16          /* keyFinal[16] in main.c */
#define HAVEN_REPLAY_WINDOW_S 10          /* pseudocode */

/* m: total spaces in the deployment.
   m/k ratio drives whether a ring can form at all. Two nodes can only become
   neighbours if their k-subsets intersect, and the chance that a random 5-subset
   of m is disjoint from another is C(m-k,k)/C(m,k):
       m=50  -> 0.577   only 42% of pairs can link. A numeric id-ordered ring is
                          IMPOSSIBLE (5 of 10 adjacent pairs share nothing) and
                          even the best 10-node cycle is a lucky find.
       m=20  -> 0.166   83% link, but the id-ordered ring still breaks one edge
                          for N>=5.
       m=12  -> 0.007   ~99% link. Every node here links to all others and the
                          id-ordered ring works for every N from 3 to 10, so
                          nodes can simply be wired 1-2-...-N-1.
   Lower m is strictly better up to a point: it costs key-distinctness, which
   does not matter here because the deployment is trusted (non-Byzantine nodes).
   If you raise this, recompute the ring order: sim/compute_ring_order.py */
#define HAVEN_M_SPACES        12

/* ---- TODO: not defined anywhere, fill in ---- */
/* Chordal ring: exactly two neighbours (left + right). Forwarding excludes the
   sender, so one hop per forward. Raising this degrades to mesh semantics and
   makes HAVEN_ECHO_THRESHOLD meaningless. */
#ifndef HAVEN_MAX_ADJ_NODES
#define HAVEN_MAX_ADJ_NODES   2
#endif

#define HAVEN_TAG_LEN         16          /* truncated HMAC length */
#define HAVEN_HASH_LEN        8           /* discovery hash length */

#ifndef HAVEN_ECHO_THRESHOLD
#define HAVEN_ECHO_THRESHOLD  2
#endif

#ifndef HAVEN_PROV_NUM_NODES
#define HAVEN_PROV_NUM_NODES  20
#endif
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