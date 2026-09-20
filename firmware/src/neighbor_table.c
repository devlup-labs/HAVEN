#include "neighbor_table.h"
#include <string.h>

static NeighborProfile_t neighbor_table[MAX_NEIGHBORS];

void NeighborTable_Init(void) {
    memset(neighbor_table, 0, sizeof(neighbor_table));
}

static NeighborProfile_t* FindNeighbor(uint32_t node_id) {
    for (int i = 0; i < MAX_NEIGHBORS; i++) {
        if (neighbor_table[i].is_active && neighbor_table[i].node_id == node_id) {
            return &neighbor_table[i];
        }
    }
    return NULL;
}

static NeighborProfile_t* AllocateNeighbor(uint32_t node_id) {
    // Try to find an inactive slot
    for (int i = 0; i < MAX_NEIGHBORS; i++) {
        if (!neighbor_table[i].is_active) {
            neighbor_table[i].node_id = node_id;
            neighbor_table[i].is_active = true;
            return &neighbor_table[i];
        }
    }
    return NULL; // Table full
}

bool NeighborTable_IsSessionValid(uint32_t dest_id, uint8_t** out_key) {
    NeighborProfile_t* profile = FindNeighbor(dest_id);
    if (profile != NULL) {
        if (profile->auth_status == AUTH_STATE_AUTHENTICATED && profile->epoch_countdown > 0) {
            if (out_key != NULL) {
                *out_key = profile->symmetric_key;
            }
            return true;
        }
    }
    return false;
}

void NeighborTable_UpdateSession(uint32_t node_id, const uint8_t* key) {
    NeighborProfile_t* profile = FindNeighbor(node_id);
    if (profile == NULL) {
        profile = AllocateNeighbor(node_id);
    }
    
    if (profile != NULL) {
        profile->auth_status = AUTH_STATE_AUTHENTICATED;
        profile->epoch_countdown = MAX_EPOCHS;
        profile->penalty_count = 0;
        memcpy(profile->symmetric_key, key, KEY_SIZE);
    }
}

void NeighborTable_EpochTick(void) {
    for (int i = 0; i < MAX_NEIGHBORS; i++) {
        if (neighbor_table[i].is_active) {
            if (neighbor_table[i].epoch_countdown > 0) {
                neighbor_table[i].epoch_countdown--;
                if (neighbor_table[i].epoch_countdown == 0) {
                    neighbor_table[i].auth_status = AUTH_STATE_EXPIRED;
                }
            }
        }
    }
}

void NeighborTable_AddPenalty(uint32_t node_id) {
    NeighborProfile_t* profile = FindNeighbor(node_id);
    if (profile != NULL) {
        profile->penalty_count++;
        if (profile->penalty_count >= MAX_PENALTIES) {
            // Force re-auth / delete profile
            profile->is_active = false;
        }
    }
}
