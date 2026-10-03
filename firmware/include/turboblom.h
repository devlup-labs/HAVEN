#ifndef TURBOBLOM_C
#define TURBOBLOM_C

#include <stdint.h>

int compute_K_AB(
    uint8_t node_a,
    uint8_t node_b,
    const uint8_t *K_master,
    const uint8_t *spaces_a,
    const uint8_t *spaces_b,
    uint8_t k,                  // Size of spaces
    uint8_t *out_key
);


#endif