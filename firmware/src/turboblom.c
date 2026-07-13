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
    
    uint8_t xor_sum[32];
    uint8_t payload[40];
    memset(xor_sum, 0, 32);
    int shared_count = 0;

    for (int i = 0; i < k; i++) {
        for (int j = 0; j < k; j++) {
            if (spaces_a[i] == spaces_b[j]) {

                uint8_t msg[5] = {
                    'r', 'o', 'w',
                    (spaces_a[i] >> 8) & 0xFF, spaces_a[i] & 0xFF
                };

                uint8_t row[32];
                // 32 byte row fed into buffer
                haven_hmac(seed, 32, msg, 5, row);

                for (int b = 0; b < 32; b++) {
                    xor_sum[b] ^= row[b];
                }

                shared_count++;
            }
        }
    }
    
    if (shared_count == 0) {
        return -1;
    }

    else {
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

        uint8_t hashed[32];

        mbedtls_sha256_ret(payload, 40, hashed, 0);
        memcpy(out_key, hashed, 16);
        return 0;
    }
}