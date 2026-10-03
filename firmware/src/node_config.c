#include "haven_config.h"
#include "provision.h"

/*
 * Per-node identity, derived deterministically from the build-time
 * HAVEN_NODE_ID define (see CMakeLists.txt / NODE_ID cache variable).
 *
 * Ring position is NOT provisioned: PHASE 1 discovery learns the two
 * neighbours, and HAVEN_MAX_ADJ_NODES == 2 makes that a chordal ring.
 *
 * Battery comes from a table rather than a constant because
 * internal_score = battery_pct + len(neighbour_list) (pseudocode:46). Uniform
 * battery makes every score tie, which resolves on the ID tiebreak and tests
 * nothing. The table makes node 1 score highest and win deterministically.
 */
void node_config_load(void)
{
    g_cfg.id = (uint8_t)HAVEN_NODE_ID;

    provision_k_master(g_cfg.k_master);
    provision_spaces(g_cfg.id, HAVEN_NUM_SPACES, HAVEN_M_SPACES,
                     g_cfg.k_master, g_cfg.spaces);

    int b = provision_battery(g_cfg.id);
    g_cfg.battery_pct = (b < 0) ? 0 : (uint8_t)b;
}