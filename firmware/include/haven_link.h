#include <stdint.h>
#include "haven_config.h"
typedef struct { uint8_t type, len, src, dst; uint8_t payload[HAVEN_MAX_PAYLOAD]; } frame_t;
void link_send(uint8_t dst, uint8_t type, const uint8_t *p, uint8_t len);
int  link_poll(frame_t *out);   /* non-blocking; 1 = frame ready */