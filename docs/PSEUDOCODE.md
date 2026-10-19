# HAVEN: Leader Election Protocol Specification & Pseudocode
**Unified Master Pseudocode: Core Max-Consensus & Extended Fault Handling (Phases 1–14)**

---

## 1. Protocol Parameters & State Model

### 1.1 Constants & Compile-Time Tunables
```python
ECHO_THRESHOLD          = 2       # Number of returned candidate echos required before claim
T_CLAIM_MS              = 5000    # Safety timeout after resonance before broadcasting claim
T_WINDOW_MS             = 5000    # Claim window for objection collection and vote locking
REPLAY_WINDOW_S         = 10      # Tolerance window (+/- seconds) for packet timestamp freshness
HEARTBEAT_PERIOD_MS     = 1000    # Periodic beacon interval for active leader
SESSION_TTL_S           = 30      # Neighbor link authentication lifetime before re-keying
MAX_ADJ_NODES           = 8       # Maximum physical neighbors supported per node
M_SPACES                = 12      # Total TurboBlom key spaces available in network
K_SPACES                = 5       # Key spaces assigned per node (ensures ~99% pairwise linkability)
```

### 1.2 Per-Node Persistent & Volatile State
```python
# Identity & Hardware Attributes
self.id                 : uint8_t         # Node unique hardware identifier (1..255)
self.battery_pct        : uint8_t         # Remaining battery percentage (0..100)
self.space_list         : list[uint8_t]   # k TurboBlom key space IDs assigned offline
self.k_master           : bytes[32]       # Network-wide secret deployment key

# Protocol Operational Mode
self.mode               : enum            # DISCOVERY | ELECTION | PASSTHROUGH | CLAIMING | LEADER
self.internal_score     : uint16_t        # Locally evaluated election fitness score
self.epoch_counter      : uint32_t        # Monotonic epoch counter (persisted to EEPROM)
self.leader_id          : uint8_t         # Current recognized leader ID (0xFF if unset)

# Consensus & Tracking Variables
self.best_known_score   : uint16_t        # Highest authenticated candidate score observed
self.best_known_origin  : uint8_t         # Origin node ID corresponding to best_known_score
self.echo_count         : uint8_t         # Resonant echos returned to candidate origin
self.timeout_started    : bool            # True if T_claim timer is actively running
self.vote_locked        : bool            # True if local vote locked for a claimant
self.vote_origin        : uint8_t         # Candidate ID for which local vote is committed

# Neighbor Table & Cryptographic Links
self.neighbour_list     : list[uint8_t]   # List of discovered, authenticated physical neighbors
self.neighbour_table    : dict[uint8_t -> NeighborEntry]
# NeighborEntry fields:
#   - auth_status       : UNVERIFIED | AUTHENTICATED | SUSPECT
#   - countdown_timer   : int (seconds remaining until session expiry)
#   - penalty_count     : int (malicious/malformed frame counter)
#   - K_AB              : bytes[16] (pairwise link key derived via TurboBlom)
```

---

## PART I: Core Election State Machine (Phases 1–9)
*Implemented in bare-metal embedded C (`firmware/src/haven.c`).*

### Phase 1: Neighbour Discovery & Pairwise Key Derivation
```python
# 1. Broadcast Discovery Frame at boot
discovery_packet = {
    type        : MSG_DISCOVERY,
    origin_id   : self.id,
    spaces      : self.space_list,
    time        : current_time_ms(),
    hmac        : HMAC_SHA256(self.k_master, "DISC" || self.id || spaces || time)[:16]
}
broadcast(discovery_packet, destination=BROADCAST_ID)

# 2. Ingest discovery responses during boot window (randomized 5.0s to 6.0s)
ON RECEIVE discovery_packet FROM sender:
    if abs(discovery_packet.time - current_time_ms()) > REPLAY_WINDOW_S * 1000:
        drop packet  # Replay/stale frame rejected

    if not verify_hmac(discovery_packet.hmac, self.k_master):
        drop packet  # Unauthenticated origin rejected

    # Find overlapping TurboBlom key spaces
    shared_spaces = set(self.space_list) & set(discovery_packet.spaces)
    if not shared_spaces:
        drop packet  # Cannot form physical link without shared cryptographic space

    # Derive 16-byte pairwise symmetric link key K_AB
    K_AB = derive_turboblom_key(self.id, discovery_packet.origin_id, shared_spaces, self.k_master)
    
    self.neighbour_list.append(discovery_packet.origin_id)
    self.neighbour_table[discovery_packet.origin_id] = NeighborEntry(
        auth_status     = AUTHENTICATED,
        countdown_timer = SESSION_TTL_S,
        penalty_count   = 0,
        K_AB            = K_AB
    )
```

### Phase 2: Fitness Score Computation & Mode Decision
```python
# Calculate fitness score: battery reserve + network connectivity
self.internal_score = self.battery_pct + len(self.neighbour_list)

# Evaluate probabilistic contention threshold
# Weighting parameters: l = battery weight, m = connectivity weight
weighted_ratio = ( (self.battery_pct / 100.0) + (len(self.neighbour_list) / MAX_ADJ_NODES) ) / 2.0
odds = max(1, int(weighted_ratio * 1000))  # Scale to per-mille (1..1000)

# Pseudorandom roll to prevent synchronized flood storms
random_roll = hardware_prng() % 1000

if odds > random_roll:
    self.mode = ELECTION      # Contend for network leadership
else:
    self.mode = PASSTHROUGH   # Act as voter and relay
```

### Phase 3: Election Candidacy Broadcast
```python
if self.mode == ELECTION:
    self.best_known_score  = self.internal_score
    self.best_known_origin = self.id
    self.echo_count        = 0
    self.timeout_started   = false

    # Broadcast candidate claim to all authenticated neighbors
    for neighbor_id in self.neighbour_list:
        election_packet = {
            type            : MSG_ELECTION,
            score           : self.internal_score,
            origin_id       : self.id,
            origin_tag      : HMAC_SHA256(self.k_master, self.internal_score || self.id)[:16],
            replayer_id     : self.id,
            timestamp       : current_time_ms(),
            link_tag        : HMAC_SHA256(self.neighbour_table[neighbor_id].K_AB, 
                                          replayer_id || timestamp)[:16]
        }
        send(election_packet, destination=neighbor_id)
```

### Phase 4: Priority-Pruned Flooding & Echo Resonance Counting
```python
ON RECEIVE election_packet FROM neighbor_id:
    # 1. Verify link authentication
    if not verify_hmac(election_packet.link_tag, self.neighbour_table[neighbor_id].K_AB):
        drop packet
    if abs(election_packet.timestamp - current_time_ms()) > REPLAY_WINDOW_S * 1000:
        drop packet

    # 2. Case A: Own candidate message has returned (Resonant Echo)
    if election_packet.origin_id == self.id:
        self.echo_count += 1
        # Once resonance threshold is reached, arm claim timer
        if self.echo_count >= ECHO_THRESHOLD and not self.timeout_started:
            start_timer(T_CLAIM_MS, on_expiry=trigger_phase_6)
            self.timeout_started = true
        drop packet  # Prevent endless re-circulation

    # 3. Case B: Received strictly better candidate (Higher score or deterministic ID tie-break)
    elif (election_packet.score > self.best_known_score) or \
         (election_packet.score == self.best_known_score and election_packet.origin_id > self.best_known_origin):
        
        # Verify master score tag to prevent score fabrication
        if not verify_hmac(election_packet.origin_tag, self.k_master, 
                           election_packet.score || election_packet.origin_id):
            drop packet

        # Adopt superior candidate
        self.best_known_score  = election_packet.score
        self.best_known_origin = election_packet.origin_id
        self.echo_count        = 0
        self.timeout_started   = false  # Disarm any active claim timer
        self.mode              = PASSTHROUGH

        # Forward updated candidate packet to all other neighbors
        for next_neighbor in self.neighbour_list:
            if next_neighbor != neighbor_id:
                forward_packet = copy(election_packet)
                forward_packet.replayer_id = self.id
                forward_packet.timestamp   = current_time_ms()
                forward_packet.link_tag    = HMAC_SHA256(self.neighbour_table[next_neighbor].K_AB,
                                                         self.id || forward_packet.timestamp)[:16]
                send(forward_packet, destination=next_neighbor)

    # 4. Case C: Suboptimal or redundant candidate
    else:
        drop packet  # Suppress lower priority claims
```

### Phase 5 & 6: Claim Window & Formal Leadership Claim
```python
# Triggered on T_claim timer expiry at candidate node
ON TIMER T_CLAIM_MS EXPIRY:
    # Abort if a higher candidate was received during T_claim
    if self.best_known_origin != self.id:
        self.mode = PASSTHROUGH
        return

    # Broadcast definitive CLAIM packet
    self.mode = CLAIMING
    for neighbor_id in self.neighbour_list:
        claim_packet = {
            type        : MSG_CLAIM,
            origin_id   : self.id,
            score       : self.internal_score,
            origin_tag  : HMAC_SHA256(self.k_master, "CLAIM" || self.id || self.internal_score)[:16],
            timestamp   : current_time_ms(),
            link_tag    : HMAC_SHA256(self.neighbour_table[neighbor_id].K_AB, self.id || timestamp)[:16]
        }
        send(claim_packet, destination=neighbor_id)

    # Open final claim objection window
    start_timer(T_WINDOW_MS, on_expiry=trigger_phase_8)
```

### Phase 7: Claim Propagation & Vote Locking (Follower Nodes)
```python
ON RECEIVE claim_packet FROM neighbor_id:
    if not verify_hmac(claim_packet.link_tag, self.neighbour_table[neighbor_id].K_AB):
        drop packet
    if not verify_hmac(claim_packet.origin_tag, self.k_master):
        drop packet

    # Forward claim across remaining topology
    for next_neighbor in self.neighbour_list:
        if next_neighbor != neighbor_id:
            forward_claim = copy(claim_packet)
            forward_claim.link_tag = HMAC_SHA256(self.neighbour_table[next_neighbor].K_AB, 
                                                 self.id || current_time_ms())[:16]
            send(forward_claim, destination=next_neighbor)

    # Commit local vote to candidate for the duration of T_window
    self.vote_locked = true
    self.vote_origin = claim_packet.origin_id
    start_timer(T_WINDOW_MS, on_expiry=lambda: clear_vote_lock())
```

### Phase 8 & 9: Consensus Finalization & Leader Heartbeats
```python
# At claiming node:
ON TIMER T_WINDOW_MS EXPIRY:
    if self.mode == CLAIMING and self.best_known_origin == self.id:
        self.mode          = LEADER
        self.leader_id     = self.id
        self.epoch_counter = 0
        persist_to_eeprom(self.epoch_counter)
        start_periodic_timer(HEARTBEAT_PERIOD_MS, on_tick=emit_leader_heartbeat)

# Leader periodic heartbeat emission
def emit_leader_heartbeat():
    self.epoch_counter += 1
    persist_to_eeprom(self.epoch_counter)
    
    for neighbor_id in self.neighbour_list:
        heartbeat = {
            type        : MSG_HEARTBEAT,
            leader_id   : self.id,
            epoch_seq   : self.epoch_counter,
            origin_tag  : HMAC_SHA256(self.k_master, "HB" || self.id || self.epoch_counter)[:16],
            link_tag    : HMAC_SHA256(self.neighbour_table[neighbor_id].K_AB, 
                                      self.id || self.epoch_counter)[:16]
        }
        send(heartbeat, destination=neighbor_id)

# Follower node heartbeat processing:
ON RECEIVE heartbeat FROM neighbor_id:
    if not verify_hmac(heartbeat.link_tag, self.neighbour_table[neighbor_id].K_AB):
        drop packet
    if not verify_hmac(heartbeat.origin_tag, self.k_master):
        drop packet

    # Monotonic freshness check
    if heartbeat.epoch_seq <= self.last_seen_epoch:
        drop packet  # Stale/replayed heartbeat

    self.last_seen_epoch = heartbeat.epoch_seq
    self.leader_id       = heartbeat.leader_id
    self.mode            = PASSTHROUGH

    # Disarm any pending promotion timers to prevent split-brain dual leaders
    cancel_timer(T_WINDOW_MS)
    cancel_timer(T_CLAIM_MS)
    self.timeout_started = false
```

---

## PART II: Extended Fault-Tolerance & Resilience Mechanics (Phases 10–14)
*Extended protocol logic for dynamic edge recovery, partitions, and re-election.*

### Phase 10: Objection Handling & Claim Retraction
```python
ON RECEIVE claim_packet AT node possessing higher score:
    # A node discovers a claimant has claimed leadership, but this node
    # either has a higher internal score or knows of a higher candidate
    if (self.internal_score > claim_packet.score) or \
       (self.best_known_score > claim_packet.score and self.best_known_origin != claim_packet.origin_id):

        higher_candidate = self.id if (self.internal_score > self.best_known_score) else self.best_known_origin
        higher_score     = max(self.internal_score, self.best_known_score)

        objection_packet = {
            type            : MSG_OBJECTION,
            objector_id     : self.id,
            target_claimant : claim_packet.origin_id,
            higher_origin   : higher_candidate,
            higher_score    : higher_score,
            origin_tag      : HMAC_SHA256(self.k_master, "OBJ" || higher_candidate || higher_score)[:16],
            timestamp       : current_time_ms()
        }
        send(objection_packet, destination=neighbor_id)

ON RECEIVE objection_packet AT claimant node (during T_window):
    if not verify_hmac(objection_packet.origin_tag, self.k_master):
        drop packet

    if objection_packet.higher_score > self.internal_score:
        # Yield leadership claim immediately
        cancel_timer(T_WINDOW_MS)
        self.best_known_score  = objection_packet.higher_score
        self.best_known_origin = objection_packet.higher_origin
        self.mode              = PASSTHROUGH
        # Higher candidate will initiate its own claim cycle
```

### Phase 11: Periodic Session Expiry & 3-Way Re-Authentication
```python
# Executed periodically (e.g. every 1 second) on all nodes
EVERY 1 SECOND:
    for neighbor_id, entry in list(self.neighbour_table.items()):
        entry.countdown_timer -= 1
        
        # When session TTL expires, trigger 3-way HELLO handshake
        if entry.countdown_timer <= 0:
            initiate_hello_handshake(neighbor_id)

def initiate_hello_handshake(neighbor_id):
    # Step 1: Transmit Challenge Nonce
    nonce_a = generate_crypto_nonce()
    send(MSG_HELLO_1, payload={ "nonce_a": nonce_a }, destination=neighbor_id)

ON RECEIVE MSG_HELLO_1:
    nonce_b = generate_crypto_nonce()
    mac_b = HMAC_SHA256(self.neighbour_table[sender].K_AB, nonce_a || nonce_b)
    send(MSG_HELLO_2, payload={ "nonce_b": nonce_b, "mac": mac_b }, destination=sender)

ON RECEIVE MSG_HELLO_2:
    if verify_hmac(packet.mac, entry.K_AB, nonce_a || packet.nonce_b):
        mac_a = HMAC_SHA256(entry.K_AB, packet.nonce_b || nonce_a)
        send(MSG_HELLO_3, payload={ "mac": mac_a }, destination=sender)
        # Session re-authenticated
        entry.countdown_timer = SESSION_TTL_S
        entry.penalty_count   = 0
    else:
        entry.penalty_count += 1
        if entry.penalty_count >= 3:
            purge_neighbor(sender)  # Sever untrusted link
```

### Phase 12: Link Severance, Loop Closure & Partition Segmentation
```python
ON DETECT SEVERED LINK WITH neighbor N:
    remove N from self.neighbour_list
    
    # Check if network is partitioned or remains a closed loop
    find_leader_packet = {
        type        : MSG_FIND_LEADER,
        requester   : self.id,
        lost_node   : N,
        timestamp   : current_time_ms()
    }
    broadcast(find_leader_packet)

ON EVALUATION OF PROBE RESPONSES:
    if probe returned from alternate loop path:
        # Ring/Mesh remains connected via redundant paths; no partition
        pass
    else:
        # Network partition confirmed: isolated segment
        self.leader_id = 0xFF
        self.mode      = PASSTHROUGH
        # Trigger localized re-election within isolated segment
        trigger_phase_2_election()
```

### Phase 13: Partition Re-Merge & Dynamic Leader Resignation
```python
# When two previously severed partitions reconnect, their respective leaders
# will receive conflicting heartbeats or join requests.
ON RECEIVE FOREIGN HEARTBEAT FROM foreign_leader_id (foreign_leader_id != self.leader_id):
    if self.mode == LEADER:
        # Compare leader credentials
        if foreign_leader_score > self.internal_score or \
           (foreign_leader_score == self.internal_score and foreign_leader_id > self.id):
            # Resign in favor of superior partition leader
            broadcast_resignation(self.id)
            self.mode      = PASSTHROUGH
            self.leader_id = foreign_leader_id
        else:
            # Maintain leadership; foreign partition will yield upon receiving our heartbeat
            emit_leader_heartbeat()
```

### Phase 14: Ambient Presence Tracking & Neighbor Blacklisting
```python
EVERY AMBIENT_PERIOD:
    # Broadcast periodic passive beacon
    send_unaddressed(MSG_PRESENCE, payload={ "id": self.id, "leader": self.leader_id })

ON DETECT MALFORMED/INVALID FRAME FROM node M:
    self.neighbour_table[M].penalty_count += 1
    if self.neighbour_table[M].penalty_count >= PENALTY_THRESHOLD:
        self.neighbour_table[M].auth_status = SUSPECT
        # Blacklist physical link; cease forwarding or voting for M
        drop_all_traffic_from(M)
```

---

## 3. Wire Frame Formats & Field Layouts

Every frame transmitted over physical serial/radio links conforms to the standard 5-byte header prefixed by Start-of-Frame delimiter `0xA5`:

```
Byte 0       Byte 1       Byte 2       Byte 3       Byte 4       Bytes 5..(5+Len-1)   Bytes (5+Len)..End
┌────────────┬────────────┬────────────┬────────────┬────────────┬────────────────────┬────────────────────┐
│ SOF (0xA5) │ Type (1B)  │ Len (1B)   │ Src ID(1B) │ Dst ID(1B) │ Payload Data (Var) │ HMAC-SHA256 (16B)  │
└────────────┴────────────┴────────────┴────────────┴────────────┴────────────────────┴────────────────────┘
```

| Type Code | Hex Value | Name | Payload Data Structure |
|:---:|:---:|:---|:---|
| `1` | `0x01` | `MSG_DISCOVERY` | `[Spaces Count (1B)][Space IDs (k B)][Timestamp (4B)]` |
| `2` | `0x02` | `MSG_ELECTION` | `[Score (2B)][Origin ID (1B)][Origin Tag (16B)][Replayer ID (1B)][Timestamp (4B)]` |
| `3` | `0x03` | `MSG_CLAIM` | `[Score (2B)][Origin ID (1B)][Origin Tag (16B)][Timestamp (4B)]` |
| `4` | `0x04` | `MSG_HEARTBEAT` | `[Leader ID (1B)][Epoch Counter (4B)][Origin Tag (16B)]` |
| `5` | `0x05` | `MSG_OBJECTION` | `[Objector ID (1B)][Higher Score (2B)][Higher Origin (1B)][Origin Tag (16B)]` |
