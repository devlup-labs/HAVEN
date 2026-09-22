#include "protocol.h"
#include <string.h>

void protocol_build_presence_hb(PresenceHeartbeat_t *hb, uint16_t node_id, uint16_t leader_id, uint16_t seq)
{
    if (!hb)
        return;
    hb->node_id = node_id;
    hb->leader_id = leader_id;
    hb->sequence = seq;
}

void protocol_build_election(ElectionPacket_t *ep, uint32_t score, uint16_t origin, uint16_t sender, const uint8_t *score_hmac, const uint8_t *origin_hmac)
{
    if (!ep)
        return;
    ep->score = score;
    ep->origin_id = origin;
    ep->sender_id = sender;
    if (score_hmac)
        memcpy(ep->score_hmac, score_hmac, 16);
    else
        memset(ep->score_hmac, 0, 16);

    if (origin_hmac)
        memcpy(ep->origin_hmac, origin_hmac, 16);
    else
        memset(ep->origin_hmac, 0, 16);
}

void protocol_build_leader_hb(LeaderHeartbeat_t *lhb, uint32_t counter, uint16_t leader_id, const uint8_t *counter_hmac, const uint8_t *leader_hmac)
{
    if (!lhb)
        return;
    lhb->counter = counter;
    lhb->leader_id = leader_id;
    if (counter_hmac)
        memcpy(lhb->counter_hmac, counter_hmac, 16);
    else
        memset(lhb->counter_hmac, 0, 16);

    if (leader_hmac)
        memcpy(lhb->leader_hmac, leader_hmac, 16);
    else
        memset(lhb->leader_hmac, 0, 16);

    lhb->padding[0] = 0;
    lhb->padding[1] = 0;
}
