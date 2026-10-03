#include "provision.h"
#include "crypto.h"
#include <string.h>

/*
 * Port of assign_spaces() from sim/turboblom.py.
 *
 * Deliberately identical to the Python reference so that firmware and the
 * simulation derive the same space lists for the same node id:
 *   msg  = "spaces" || BE32(node_id) || BE32(counter)
 *   out  = first k distinct (byte % m) values seen, then sorted
 *
 * Spaces are unique by construction, so the k x k scan in compute_K_AB()
 * cannot double-count a space.
 */
int provision_spaces(uint8_t node_id, uint8_t k, uint8_t m,
                     const uint8_t *k_master, uint8_t *out)
{
    uint8_t seen[HAVEN_PROV_SEEN_BYTES];
    uint8_t got = 0;
    uint32_t counter = 0;

    /* m is uint8_t so it can never exceed 256; the bitmap covers that range. */
    if (k == 0 || m == 0) return -1;

    memset(seen, 0, sizeof seen);

    while (got < k) {
        uint8_t msg[14], full[32];
        uint32_t c = counter++;

        memcpy(msg, "spaces", 6);
        msg[6]  = (uint8_t)(node_id >> 24); msg[7]  = (uint8_t)(node_id >> 16);
        msg[8]  = (uint8_t)(node_id >> 8);  msg[9]  = (uint8_t)node_id;
        msg[10] = (uint8_t)(c >> 24);       msg[11] = (uint8_t)(c >> 16);
        msg[12] = (uint8_t)(c >> 8);        msg[13] = (uint8_t)c;

        haven_hmac(k_master, 32, msg, 14, full);

        for (int b = 0; b < 32 && got < k; b++) {
            uint8_t idx = (uint8_t)(full[b] % m);
            if (seen[idx >> 3] & (uint8_t)(1u << (idx & 7))) continue;
            seen[idx >> 3] |= (uint8_t)(1u << (idx & 7));
            out[got++] = idx;
        }

        /* Bounded: 32*m distinct indices can be produced per counter round. */
        if (counter > 0xFFFFFFFFu) return -1;
    }

    /* Python returns sorted(spaces); match it so both sides agree. */
    for (uint8_t i = 1; i < k; i++) {
        uint8_t v = out[i], j = i;
        while (j > 0 && out[j - 1] > v) { out[j] = out[j - 1]; j--; }
        out[j] = v;
    }
    return 0;
}

int provision_battery(uint8_t node_id)
{
    if (node_id == 0 || node_id > HAVEN_PROV_NUM_NODES) return -1;
    return (int)provision_battery_table()[node_id - 1];
}

const uint8_t *provision_battery_table(void)
{
    static const uint8_t table[HAVEN_PROV_NUM_NODES] =
        { 100, 80, 60, 40, 20, 90, 70, 50, 30, 10 };
    return table;
}

int provision_k_master(uint8_t *out)
{
    for (int i = 0; i < 32; i++) out[i] = (uint8_t)i;
    return 0;
}