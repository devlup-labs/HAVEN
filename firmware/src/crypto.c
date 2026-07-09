#include "crypto.h"
#include "mbedtls/md.h"
#include <string.h>

void haven_hmac(const uint8_t *key, size_t key_len,
                  const uint8_t *msg, size_t msg_len,
                  uint8_t *out) 
    {
        const mbedtls_md_info_t *md_info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);

        if(md_info == NULL) {
            memset(out, 0, 32); // Set output to zero if md_info is NULL
            return;
        }

        int ret = mbedtls_md_hmac(md_info, key, key_len, msg, msg_len, out);

        if(ret != 0) {
            memset(out, 0, 32); // Set output to zero if HMAC computation fails
            return;
        }
    }