#ifndef HAVEN_CRYPTO_H
#define HAVEN_CRYPTO_H

#include <stdint.h>
#include <stddef.h>



void haven_hmac(const uint8_t *key,  size_t key_len,
                  const uint8_t *msg,  size_t msg_len,
                  uint8_t *out);


#endif /* HAVEN_CRYPTO_H */
