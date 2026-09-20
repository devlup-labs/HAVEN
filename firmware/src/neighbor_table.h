#ifndef NEIGHBOR_TABLE_H
#define NEIGHBOR_TABLE_H

#include <stdint.h>
#include <stdbool.h>

#define MAX_NEIGHBORS 16
#define KEY_SIZE 16 // 128-bit key
#define MAX_EPOCHS 10 // Number of tick epochs before session expires
#define MAX_PENALTIES 3

typedef enum {
    AUTH_STATE_NONE,
    AUTH_STATE_HANDSHAKING,
    AUTH_STATE_AUTHENTICATED,
    AUTH_STATE_EXPIRED
} AuthState_t;

typedef struct {
    uint32_t node_id;
    AuthState_t auth_status;
    uint16_t epoch_countdown;
    uint8_t penalty_count;
    uint8_t symmetric_key[KEY_SIZE];
    bool is_active;
} NeighborProfile_t;

// Initialize the neighbor table
void NeighborTable_Init(void);

// Interceptor: Check if we have a cached, authenticated session for a destination
bool NeighborTable_IsSessionValid(uint32_t dest_id, uint8_t** out_key);

// Start Handshake or Update existing session
void NeighborTable_UpdateSession(uint32_t node_id, const uint8_t* key);

// Background tick to decrement epochs and handle expiry
void NeighborTable_EpochTick(void);

// Record a failure (e.g. invalid MAC)
void NeighborTable_AddPenalty(uint32_t node_id);

#endif // NEIGHBOR_TABLE_H
