#include "haven.h"
#include "haven_config.h"
#include "haven_link.h"
#include "haven_time.h"
#include "crypto.h"
#include "turboblom.h"
#include <string.h>

enum { T_DISCOVERY = 1, T_ELECTION, T_CLAIM, T_HEARTBEAT };
typedef enum { M_DISCOVERY, M_ELECTION, M_PASSTHROUGH, M_CLAIMING, M_LEADER } hv_mode;

#define TAG HAVEN_TAG_LEN
#define ELEC_LEN  (2 + 1 + TAG + 1 + 4 + TAG)
#define CLAIM_LEN (1 + 2 + TAG + 4 + TAG)
#define HB_LEN    (4 + 1 + TAG + TAG)
#define DISC_LEN  (1 + HAVEN_NUM_SPACES + 4 + HAVEN_HASH_LEN)

/* ---------- state ---------- */
node_config_t g_cfg;
typedef struct { uint8_t id; uint8_t key[HAVEN_KEY_LEN]; } nbr_t;
static nbr_t   nb[HAVEN_MAX_ADJ_NODES];
static uint8_t nb_n;

/* PHASE 4 forwarding memory, one bit per origin per neighbour direction.
   On a ring the same election packet arrives twice -- once travelling each way
   -- and the two copies meet head-on at the antipodal node. The strictly-better
   test in on_election alone drops the second copy as a duplicate, so BOTH copies
   die mid-ring, no echo ever returns, ECHO_THRESHOLD is never met and no leader
   is ever elected. Keying the memory on (origin, incoming neighbour) lets each
   copy complete the ring, yielding exactly one echo per direction. */
static uint8_t fwd_mask[HAVEN_MAX_ADJ_NODES][32];

static hv_mode  mode = M_DISCOVERY;
static uint16_t internal_score;
static uint16_t best_score;
static uint8_t  best_origin, best_hs[TAG];
static uint8_t  my_hs[TAG];
static uint8_t  echo_count, timeout_started;
static uint32_t epoch_counter, last_hb_counter;
static uint8_t  leader_id = HAVEN_ID_NONE;

static uint32_t claim_dl, window_dl, vote_dl, epoch_dl;
static uint8_t  claim_on, window_on, vote_on, vote_origin;

static uint64_t prng_seed;

/* ---------- helpers ---------- */
static void put16(uint8_t *p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static uint16_t get16(const uint8_t *p) { return p[0] | (p[1] << 8); }
static void put32(uint8_t *p, uint32_t v) { p[0]=v; p[1]=v>>8; p[2]=v>>16; p[3]=v>>24; }
static uint32_t get32(const uint8_t *p) { return p[0] | (p[1]<<8) | (p[2]<<16) | ((uint32_t)p[3]<<24); }

static uint32_t now_s(void) { return time_ms() / 1000u; }
static int expired(uint32_t dl) { return (int32_t)(time_ms() - dl) >= 0; }
static int fresh(uint32_t t)
{
    int32_t d = (int32_t)(t - now_s());
    return d >= -HAVEN_REPLAY_WINDOW_S && d <= HAVEN_REPLAY_WINDOW_S;
}

static void tag(uint8_t *key, size_t klen, uint8_t *msg, size_t mlen, uint8_t *out)
{
    uint8_t full[32];
    haven_hmac(key, klen, msg, mlen, full);
    memcpy(out, full, TAG);
}
static int tag_ok(uint8_t *key, size_t klen, uint8_t *msg, size_t mlen, const uint8_t *rx)
{
    uint8_t t[TAG], d = 0, nz = 0;
    tag(key, klen, msg, mlen, t);
    for (int i = 0; i < TAG; i++) { d |= t[i] ^ rx[i]; nz |= t[i]; }
    return d == 0 && nz != 0;
}
static nbr_t *nb_find(uint8_t id)
{
    for (uint8_t i = 0; i < nb_n; i++) if (nb[i].id == id) return &nb[i];
    return 0;
}

/* score tag: HMAC(K_master, score||origin)  [CONFIRM key/input] */
static void score_tag(uint16_t score, uint8_t origin, uint8_t *out)
{
    uint8_t m[3]; put16(m, score); m[2] = origin;
    tag(g_cfg.k_master, 32, m, 3, out);
}
static int score_tag_ok(uint16_t score, uint8_t origin, const uint8_t *rx)
{
    uint8_t m[3]; put16(m, score); m[2] = origin;
    return tag_ok(g_cfg.k_master, 32, m, 3, rx);
}

/* ---------- PRNG (pseudocode phase 2) ---------- */
static uint32_t prng_next(void)
{
    prng_seed = (HAVEN_PRNG_A * prng_seed + HAVEN_PRNG_B) % HAVEN_PRNG_M;
    return (uint32_t)prng_seed;
}

/* ---------- PHASE 1: discovery ---------- */
static void discovery_hash(const uint8_t *body, uint8_t *out)   /* [CONFIRM] */
{
    uint8_t full[32], m[1 + HAVEN_NUM_SPACES + 4];
    memcpy(m, body, sizeof m);
    haven_hmac(g_cfg.k_master, 32, m, sizeof m, full);
    memcpy(out, full, HAVEN_HASH_LEN);
}
static void tx_discovery(void)
{
    uint8_t p[DISC_LEN];
    p[0] = g_cfg.id;
    memcpy(p + 1, g_cfg.spaces, HAVEN_NUM_SPACES);
    put32(p + 1 + HAVEN_NUM_SPACES, now_s());
    discovery_hash(p, p + 1 + HAVEN_NUM_SPACES + 4);
    link_send(HAVEN_ID_NONE, T_DISCOVERY, p, DISC_LEN);
}
static void on_discovery(const frame_t *f)
{
    if (f->len != DISC_LEN) return;
    const uint8_t *p = f->payload;
    if (!fresh(get32(p + 1 + HAVEN_NUM_SPACES))) return;
    uint8_t h[HAVEN_HASH_LEN];
    discovery_hash(p, h);
    if (memcmp(h, p + 1 + HAVEN_NUM_SPACES + 4, HAVEN_HASH_LEN)) return;

    uint8_t peer = p[0], k[HAVEN_KEY_LEN];
    if (peer == g_cfg.id) return;
    if (compute_K_AB(g_cfg.id, peer, g_cfg.k_master, g_cfg.spaces,
                     p + 1, HAVEN_NUM_SPACES, k) != 0) return;

    nbr_t *n = nb_find(peer);
    if (!n) { if (nb_n >= HAVEN_MAX_ADJ_NODES) return; n = &nb[nb_n++]; n->id = peer; }
    memcpy(n->key, k, HAVEN_KEY_LEN);
}

/* ---------- PHASE 3/4: election ---------- */
static void tx_election(uint16_t score, uint8_t origin, const uint8_t *hs, uint8_t exclude)
{
    for (uint8_t i = 0; i < nb_n; i++) {
        if (nb[i].id == exclude) continue;
        uint8_t p[ELEC_LEN], m[8]; uint32_t t = now_s();
        put16(p, score); p[2] = origin; memcpy(p + 3, hs, TAG);
        p[3 + TAG] = g_cfg.id; put32(p + 4 + TAG, t);
        put16(m, score); m[2] = origin; m[3] = g_cfg.id; put32(m + 4, t);
        tag(nb[i].key, HAVEN_KEY_LEN, m, 8, p + 8 + TAG);   /* hmac_replay, per-neighbour K_AB [CONFIRM] */
        link_send(nb[i].id, T_ELECTION, p, ELEC_LEN);
    }
}
static void on_election(const frame_t *f)
{
    if (f->len != ELEC_LEN) return;
    const uint8_t *p = f->payload;
    uint16_t score = get16(p); uint8_t origin = p[2];
    uint8_t replayer = p[3 + TAG]; uint32_t t = get32(p + 4 + TAG);
    if (!fresh(t)) return;
    nbr_t *n = nb_find(replayer); if (!n) return;
    uint8_t m[8]; put16(m, score); m[2] = origin; m[3] = replayer; put32(m + 4, t);
    if (!tag_ok(n->key, HAVEN_KEY_LEN, m, 8, p + 8 + TAG)) return;
    if (!score_tag_ok(score, origin, p + 3)) return;

    if (origin == g_cfg.id) {
        echo_count++;
        if (echo_count >= HAVEN_ECHO_THRESHOLD && !timeout_started) {
            claim_dl = time_ms() + HAVEN_T_CLAIM_MS; claim_on = 1; timeout_started = 1;
        }
        return;
    }
    /* Adopt a strictly better candidate (pseudocode:95-96). The echo counters
       reset on improvement, but forwarding is separately gated below so that the
       antipodal copy is not lost. */
    int better = score > best_score || (score == best_score && origin > best_origin);
    if (better) {
        best_score = score; best_origin = origin; memcpy(best_hs, p + 3, TAG);
        echo_count = 0; timeout_started = 0;
        if (mode == M_ELECTION) mode = M_PASSTHROUGH;
    }

    /* Forward each (origin, incoming neighbour) at most once per ring, so both
       directional copies traverse the whole ring instead of annihilating.
       Slot i is selected by nb[i].id == replayer, so the key is the PAIR
       (neighbour, origin): a node legitimately receives the same origin from
       both of its neighbours, and an origin-only key would collide. */
    for (uint8_t i = 0; i < nb_n; i++) {
        if (nb[i].id != replayer) continue;
        uint8_t *slot = fwd_mask[i];
        if (slot[origin >> 3] & (uint8_t)(1u << (origin & 7))) return;
        slot[origin >> 3] |= (uint8_t)(1u << (origin & 7));
        break;
    }
    /* Forward the received packet's own score tag (identical to best_hs when
       `better`); forwarding a not-strictly-better packet is required for the
       ring to close, since a node holding a higher score must still relay it. */
    tx_election(score, origin, p + 3, replayer);
}

/* ---------- PHASE 6/7: claim ---------- */
static void claim_tag(uint8_t origin, uint32_t t, uint8_t *out)
{
    uint8_t m[5]; m[0] = origin; put32(m + 1, t);
    tag(g_cfg.k_master, 32, m, 5, out);
}
static void tx_claim(uint16_t score, uint8_t origin, const uint8_t *hs, uint32_t t, uint8_t exclude)
{
    uint8_t p[CLAIM_LEN];
    p[0] = origin; put16(p + 1, score); memcpy(p + 3, hs, TAG);
    put32(p + 3 + TAG, t); claim_tag(origin, t, p + 7 + TAG);
    for (uint8_t i = 0; i < nb_n; i++)
        if (nb[i].id != exclude) link_send(nb[i].id, T_CLAIM, p, CLAIM_LEN);
}
static void on_claim(const frame_t *f)
{
    if (f->len != CLAIM_LEN) return;
    const uint8_t *p = f->payload;
    uint8_t origin = p[0]; uint16_t score = get16(p + 1); uint32_t t = get32(p + 3 + TAG);
    if (!fresh(t)) return;
    if (!score_tag_ok(score, origin, p + 3)) return;
    uint8_t m[5]; m[0] = origin; put32(m + 1, t);
    if (!tag_ok(g_cfg.k_master, 32, m, 5, p + 7 + TAG)) return;

    if (vote_on && vote_origin == origin) return;      /* [GAP] loop guard, not in pseudocode */
    tx_claim(score, origin, p + 3, t, f->src);
    vote_origin = origin; vote_on = 1; vote_dl = time_ms() + HAVEN_T_WINDOW_MS;
}

/* ---------- PHASE 9: heartbeat ---------- */
static void on_heartbeat(const frame_t *f)
{
    if (f->len != HB_LEN) return;
    const uint8_t *p = f->payload;
    uint32_t ctr = get32(p); uint8_t lid = p[4];
    if (lid == g_cfg.id) return;
    uint8_t mc[4], ml[1]; put32(mc, ctr); ml[0] = lid;
    if (!tag_ok(g_cfg.k_master, 32, mc, 4, p + 5)) return;
    if (!tag_ok(g_cfg.k_master, 32, ml, 1, p + 5 + TAG)) return;
    if (ctr <= last_hb_counter) return;                /* "counter freshness" [CONFIRM] */
    last_hb_counter = ctr; leader_id = lid; mode = M_PASSTHROUGH;
    /* Deliberate deviation: pseudocode:165-168 only sets leader_id and mode, but
       a pending T_window would otherwise fire PHASE 8 and make this node LEADER
       too. PASSTHROUGH means yield, so clear every timer that could promote us. */
    claim_on = 0; window_on = 0; vote_on = 0;
}
static void tx_heartbeat(void)
{
    uint8_t p[HB_LEN], mc[4], ml[1];
    epoch_counter++;
    put32(p, epoch_counter); p[4] = g_cfg.id;
    put32(mc, epoch_counter); ml[0] = g_cfg.id;
    tag(g_cfg.k_master, 32, mc, 4, p + 5);
    tag(g_cfg.k_master, 32, ml, 1, p + 5 + TAG);
    for (uint8_t i = 0; i < nb_n; i++) link_send(nb[i].id, T_HEARTBEAT, p, HB_LEN);
}

/* ---------- dispatch ---------- */
static void dispatch(const frame_t *f)
{
    if (f->dst != g_cfg.id && f->dst != HAVEN_ID_NONE) return;
    switch (f->type) {
    case T_DISCOVERY: on_discovery(f); break;
    case T_ELECTION:  on_election(f);  break;
    case T_CLAIM:     on_claim(f);     break;
    case T_HEARTBEAT: on_heartbeat(f); break;
    }
}

/* ---------- main protocol loop ---------- */
void haven_run(void)
{
    frame_t f;
    prng_seed = g_cfg.id;                               /* [CONFIRM] initial_random_seed() */

    /* PHASE 1 */
    tx_discovery();
    uint32_t end = time_ms() + 5000u + (prng_next() % 1000u);   /* 5 < x < 6 s */
    while (!expired(end)) if (link_poll(&f)) dispatch(&f);

    /* PHASE 2 */
    internal_score = g_cfg.battery_pct + nb_n;
    uint32_t odds = (((uint32_t)HAVEN_L_WEIGHT * g_cfg.battery_pct * 1000u) / 100u +
                     ((uint32_t)HAVEN_M_WEIGHT * nb_n * 1000u) / HAVEN_MAX_ADJ_NODES) / 2u;
    if (odds < 1u) odds = 1u;                            /* max(1, ...) is a FLOOR (pseudocode:48) */
    uint32_t prob = (uint32_t)(((uint64_t)prng_next() * 1000u) / HAVEN_PRNG_M);
    mode = (odds > prob) ? M_ELECTION : M_PASSTHROUGH;

    /* PHASE 3 */
    /* best_score and best_origin are preserved from any early ELECTION packets */
    if (mode == M_ELECTION) {
        if (internal_score > best_score || (internal_score == best_score && g_cfg.id > best_origin)) {
            best_score = internal_score; best_origin = g_cfg.id;
            score_tag(internal_score, g_cfg.id, my_hs);
            memcpy(best_hs, my_hs, TAG);
            echo_count = 0; timeout_started = 0;
            tx_election(internal_score, g_cfg.id, my_hs, HAVEN_ID_NONE);
        } else {
            mode = M_PASSTHROUGH;
        }
    }

    for (;;) {
        if (link_poll(&f)) dispatch(&f);

        if (claim_on && expired(claim_dl)) {            /* PHASE 5 */
            claim_on = 0;
            if (best_origin != g_cfg.id) mode = M_PASSTHROUGH;
            else {                                      /* PHASE 6 */
                uint32_t t = now_s();
                tx_claim(internal_score, g_cfg.id, my_hs, t, HAVEN_ID_NONE);
                vote_origin = g_cfg.id; vote_on = 1; vote_dl = time_ms() + HAVEN_T_WINDOW_MS;
                window_dl = time_ms() + HAVEN_T_WINDOW_MS; window_on = 1;
                mode = M_CLAIMING;
            }
        }
        if (window_on && expired(window_dl)) {          /* PHASE 8 */
            window_on = 0; mode = M_LEADER; epoch_counter = 0;
            epoch_dl = time_ms() + HAVEN_EPOCH_MS;
        }
        if (vote_on && expired(vote_dl)) vote_on = 0;
        if (mode == M_LEADER && expired(epoch_dl)) {    /* PHASE 9 */
            tx_heartbeat(); epoch_dl = time_ms() + HAVEN_EPOCH_MS;
        }
    }
}