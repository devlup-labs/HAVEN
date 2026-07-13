#include <stdint.h>
#include <string.h>
#include "mbedtls/sha256.h"
#include "crypto.h"
#include "turboblom.h"

int compute_K_AB(
    uint8_t node_a,
    uint8_t node_b,
    const uint8_t *seed,
    const uint8_t *spaces_a,
    const uint8_t *spaces_b,
    uint8_t k,
    uint8_t *out_key
) {
    uint8_t id_low = node_a < node_b ? node_a : node_b;
    uint8_t id_high = node_a > node_b ? node_a : node_b;
    unsigned int shared_count = 0;
    
    // Shared buffers
    uint8_t xor_sum[32];    // Used for XOR sum and later as buffer for hash output
    uint8_t payload[40];    // Used as buffer for row-wise operation and for final payload

    memset(xor_sum, 0, 32);     // Setting variable state to 0

    for (int i = 0; i < k; i++) {
        for (int j = 0; j < k; j++) {
            if (spaces_a[i] == spaces_b[j]) {

                uint8_t msg[5] = {
                    'r', 'o', 'w',
                    (spaces_a[i] >> 8) & 0xFF, spaces_a[i] & 0xFF
                };

                // Row-wise operations in payload, payload contains row data
                haven_hmac(seed, 32, msg, 5, payload);

                for (int b = 0; b < 32; b++) {
                    xor_sum[b] ^= payload[b];
                }

                shared_count++;
            }
        }
    }
    
    if (shared_count == 0) {
        return -1;
    }

    else {
        // Data from 'xor_sum' copied into first 32 bytes payload, 'xor_sum' is redundant
        memcpy(payload, xor_sum, 32);

        // Conversion to big endian
        payload[32] = (id_low >> 24) & 0xFF;
        payload[33] = (id_low >> 16) & 0xFF;
        payload[34] = (id_low >> 8) & 0xFF;
        payload[35] = (id_low) & 0xFF;

        payload[36] = (id_high >> 24) & 0xFF;
        payload[37] = (id_high >> 16) & 0xFF;
        payload[38] = (id_high >> 8) & 0xFF;
        payload[39] = (id_high) & 0xFF;

        //Using 'xor_sum' as a buffer to hold sha256 hash of payload
        mbedtls_sha256_ret(payload, 40, xor_sum, 0);
        memcpy(out_key, xor_sum, 16);
        return 0;
    }
}