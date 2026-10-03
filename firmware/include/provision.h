#ifndef HAVEN_PROVISION_H
#define HAVEN_PROVISION_H

#include <stdint.h>

/* Space assignment is bounded by a bitmap; 8 bytes covers m <= 256 spaces. */
#define HAVEN_PROV_SEEN_BITS  8
#define HAVEN_PROV_SEEN_BYTES 8

/* Nodes this build can be provisioned as. */
#ifndef HAVEN_PROV_NUM_NODES
#define HAVEN_PROV_NUM_NODES 10
#endif

/* Total spaces in the deployment. Derived from HAVEN_M_SPACES rather than
   duplicated, so the two can never drift; override -DHAVEN_M_SPACES at build
   time to retune. */
#include "haven_config.h"
#ifndef HAVEN_M_SPACES
#define HAVEN_M_SPACES 12
#endif

/* Byte length of the K_master key material. */
#define HAVEN_PROV_K_MASTER_LEN 32

int provision_spaces(uint8_t node_id, uint8_t k, uint8_t m,
                     const uint8_t *k_master, uint8_t *out);
int provision_battery(uint8_t node_id);
const uint8_t *provision_battery_table(void);
int provision_k_master(uint8_t *out);

#endif /* HAVEN_PROVISION_H */