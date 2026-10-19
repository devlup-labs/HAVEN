// \============================================================  
// HAVEN — Leader Election Protocol (Full Pseudocode)  
// \============================================================

// \---------------- CONSTANTS \----------------  
ECHO\_THRESHOLD   \= \<tuned via simulation\>  
T\_claim          \= \<safety timeout before claimant broadcast\>  
T\_window         \= \<claim window for objections\>  
REPLAY\_WINDOW    \= 10   // seconds, \+/- tolerance on packet timestamps  
HEARTBEAT\_PERIOD \= \<per epoch tick\>

// \---------------- STATE (per node) \----------------  
self.id  
self.mode              \= DISCOVERY     
// DISCOVERY | ELECTION | PASSTHROUGH | CLAIMING | LEADER  
self.internal\_score  
self.neighbour\_list     \= \[\]          // populated in phase 2  
self.neighbour\_table     \= {} // node\_id \-\> { auth\_status, countdown\_timer, penalty\_count, K\_AB }  
self.best\_known\_score  
self.best\_known\_origin  
self.echo\_count         \= 0  
self.timeout\_started    \= false  
self.epoch\_counter      \= load\_from\_EEPROM()   // section 4.5  
self.leader\_id          \= null

// \============================================================  
// PHASE 1 — NEIGHBOUR DISCOVERY / KEY DERIVATION  
// \============================================================  
1\. BROADCAST discovery\_packet to all adjacent nodes:  
       { node\_id: self.id, turboblom\_spaces: self.space\_list, time: now(), hash }

2\. LISTEN for x seconds, where x is randomised per node (5 \< x \< 6\)  
       // random per-node duration avoids synchronized collision storms  
   for every received discovery\_packet:  
       if |packet.time \- now()| \> REPLAY\_WINDOW:  
           drop packet   // stale or replayed  
       else:  
           verify hash  
           if invalid: drop packet  
           else:  
               shared\_spaces \= self.space\_list ∩ packet.turboblom\_spaces  
               if shared\_spaces is empty:  
                   drop   // no basis for a pairwise key (section 2.3)  
               else:  
                   K\_AB \= derive\_turboblom\_key(self.id, packet.node\_id, shared\_spaces, K\_master)  
                       // idlow/idhigh sort, HMAC-SHA256 per shared space, XOR-accumulate (section 2.3)  
                   add packet.node\_id to self.neighbour\_list  
                   self.neighbour\_table\[packet.node\_id\] \= {  
                       auth\_status: AUTHENTICATED,  
                       countdown\_timer: SESSION\_TTL,  
                       penalty\_count: 0,  
                       K\_AB: K\_AB  
                   }

// \============================================================  
// PHASE 2 — SCORE COMPUTATION AND MODE DECISION  
// \============================================================  
3\. self.internal\_score \= battery\_pct \+ len(self.neighbour\_list)   // keep as int for packet field

   odds \= max(1, ( l\*(battery\_pct/100) \+ m\*(len(neighbour\_list)/MAX\_ADJ\_NODES) ) / 2\)  
       // l, m are weighting constants

   seed \= initial\_random\_seed()  
   prng \= (a\*seed \+ b) mod m\_prng  
   seed \= prng  
   prob \= prng / m\_prng

   if odds \> prob:  
       self.mode \= ELECTION  
   else:  
       self.mode \= PASSTHROUGH

// \============================================================  
// PHASE 3 — ELECTION MODE  
// \============================================================  
4\. if self.mode \== ELECTION:  
       election\_packet \= {  
           score: self.internal\_score,  
           origin\_id: self.id,  
           hmac\_score: hmac(K\_origin\_broadcast, score),  
           replayer\_id: self.id,  
           time: now(),  
           hmac\_replay: hmac(K\_link, replayer\_id ∥ time)  
       }  
       broadcast election\_packet to ring neighbours (left \+ right)

       self.best\_known\_score  \= self.internal\_score  
       self.best\_known\_origin \= self.id  
       self.echo\_count        \= 0  
       self.timeout\_started   \= false

// \============================================================  
// PHASE 4 — PACKET RECEPTION (election & passthrough nodes)  
// \============================================================  
5\. ON RECEIVE election\_packet:  
       if |packet.time \- now()| \> REPLAY\_WINDOW:  
           drop  
       if not verify\_hmac(packet, K\_link\_with\_sender):  
           drop

       if packet.origin\_id \== self.id:  
           // own candidacy propagated around the ring and returned  
           self.echo\_count \+= 1  
           if self.echo\_count \>= ECHO\_THRESHOLD and not self.timeout\_started:  
               start\_timer(T\_claim)  
               self.timeout\_started \= true  
           drop packet   // do not re-circulate own echo

       else if packet.score \> self.best\_known\_score  
             or (packet.score \== self.best\_known\_score and packet.origin\_id \> self.best\_known\_origin):  
           // deterministic tie-break on origin\_id  
           self.best\_known\_score  \= packet.score  
           self.best\_known\_origin \= packet.origin\_id  
           self.echo\_count        \= 0  
           self.timeout\_started   \= false

           forward\_packet \= { ...packet, replayer\_id: self.id, time: now(), hmac\_replay: recompute }  
           broadcast forward\_packet to ring neighbours, excluding sender

           if self.mode \== ELECTION:  
               self.mode \= PASSTHROUGH   // yield to stronger candidate

       else:  
           drop packet   // lower-priority / redundant, suppressed (per section 3.1)

// \============================================================  
// PHASE 5 — TIMEOUT / CLAIMANT BROADCAST  
// \============================================================  
6\. ON TIMER T\_claim EXPIRY:  
       if self.best\_known\_origin \!= self.id:  
           self.mode \= PASSTHROUGH  
           return  
       else:  
           goto PHASE 6

// \============================================================  
// PHASE 6 — CLAIMANT BROADCAST  
// \============================================================  
7\. claimant\_packet \= {  
       origin\_id: self.id,  
       score: self.internal\_score,  
       hmac\_score: hmac(...),  
       claim\_time: now(),  
       hmac\_claim\_time: hmac(...)  
   }  
   broadcast claimant\_packet to ring neighbours  
   start\_timer(T\_window)  
   self.mode \= CLAIMING

// \============================================================  
// PHASE 7 — CLAIMANT RECEPTION / OBJECTION (any node)  
// \============================================================  
8\. ON RECEIVE claimant\_packet:  
       verify hmac's and claim\_time freshness; drop if invalid

       if self.internal\_score \> packet.score  
          or (self.best\_known\_score \> packet.score and self.best\_known\_origin \!= packet.origin\_id):  
           // a higher-scoring candidate exists locally or is known but hasn't finished propagating  
           objection\_packet \= {  
               objector\_id: self.id,  
               higher\_score: max(self.internal\_score, self.best\_known\_score),  
               higher\_origin: \<corresponding origin\_id\>,  
               time: now(),  
               hmac  
           }  
           send objection\_packet back toward claimant (reverse ring path)

       else:  
           forward claimant\_packet onward (ring propagation, excluding sender)  
           lock local vote for origin\_id \= packet.origin\_id until T\_window expires

// \============================================================  
// PHASE 8 — CONSENSUS FINALIZATION (at claimant node)  
// \============================================================  
9\. ON RECEIVE objection\_packet (while T\_window active):  
       verify hmac \+ freshness; drop if invalid  
       if packet.higher\_score \> self.internal\_score:  
           cancel\_timer(T\_window)  
           self.best\_known\_score  \= packet.higher\_score  
           self.best\_known\_origin \= packet.higher\_origin  
           self.mode \= PASSTHROUGH  
           // abort claim; higher candidate will run its own claim cycle

   ON TIMER T\_window EXPIRY (no valid objection received):  
       self.mode \= LEADER  
       self.epoch\_counter \= 0  
       persist\_to\_EEPROM(self.epoch\_counter)   // section 4.5, write-on-advance only  
       start LEADER\_HEARTBEAT loop (PHASE 9\)

// \============================================================  
// PHASE 9 — PASSTHROUGH MODE  
// \============================================================  
10\. while self.mode \== PASSTHROUGH:  
        if self.leader\_id \!= null and neighbour\_table\[self.leader\_id\].countdown\_timer \> 0:  
            // fast path: known active leader, no election needed  
            on receive election\_packet or claimant\_packet:  
                apply PHASE 4 / PHASE 7 suppression \+ relay rules  
                optionally reply with cached leader\_id  
        else:  
            // no known active leader — still relay per suppression rules  
            // still eligible to emit an objection\_packet if a locally  
            // computed score turns out higher than an in-flight claimant

// \============================================================  
// PHASE 10 — LEADER\_ACTIVE / HEARTBEAT  
// \============================================================  
11\. LEADER loop (self.mode \== LEADER):  
        every HEARTBEAT\_PERIOD:  
            self.epoch\_counter \+= 1  
            leader\_heartbeat \= {  
                counter: self.epoch\_counter,  
                leader\_id: self.id,  
                hmac\_counter: hmac(...),  
                hmac\_leader\_id: hmac(...)  
            }  
            broadcast leader\_heartbeat to ring neighbours  
            persist\_to\_EEPROM(self.epoch\_counter)   // only on advance, wear-leveling

    ALL OTHER NODES, on valid leader\_heartbeat:  
        verify hmac \+ counter freshness (must be \> last seen counter, replay protection)  
        neighbour\_table\[leader\_id\].countdown\_timer \= SESSION\_TTL   // section 3.3  
        self.leader\_id \= leader\_id   // cache for passthrough fast path

// \============================================================  
// PHASE 11 — SESSION EXPIRY / RE-AUTHENTICATION (background, all nodes)  
// \============================================================  
12\. every epoch tick:  
        for each neighbour in neighbour\_table:  
            neighbour.countdown\_timer \-= 1  
            if neighbour.countdown\_timer \== 0:  
                initiate HELLO handshake with neighbour  
                if success:  
                    neighbour.countdown\_timer \= SESSION\_TTL  
                    neighbour.penalty\_count \= 0  
                else:  
                    delete neighbour\_table\[neighbour\]   // full purge, section 3.3

// \============================================================  
// PHASE 12 — LINK FAILURE / PARTITION HANDLING  
// \============================================================  
13\. ON detect severed link with neighbour N:  
        find\_leader\_packet \= { requester\_id: self.id, lost\_neighbour\_id: N, time, hmac }  
        broadcast find\_leader\_packet along ring (both directions)

        if find\_leader\_packet (matching request) received from BOTH ring directions:  
            // same segment — loop closed, no partition  
            terminate search

        else if leader\_ack received on one side but the other times out:  
            // segmentation confirmed  
            self.leader\_id \= null  
            self.mode \= ELECTION or PASSTHROUGH   // per PHASE 2 odds recomputation  
            trigger local re-election within the disconnected segment (goto PHASE 2\)

// \============================================================  
// PHASE 13 — NETWORK MERGING / LEADER RESIGNATION (leader only)  
// \============================================================  
14\. ON receive join\_request (forwarded to active leader per section 3.5):  
        join\_request\_count \+= 1  
        if join\_request\_count \> RESIGNATION\_THRESHOLD:  
            broadcast resignation\_packet { leader\_id: self.id, hmac }  
            self.mode \= PASSTHROUGH  
            self.leader\_id \= null  
            trigger GLOBAL\_RE\_ELECTION across combined topology (goto PHASE 2, all nodes)

// \============================================================  
// PHASE 14 — DYNAMIC CONNECTION TRACKING (background, all nodes, section 3.7)  
// \============================================================  
15\. every AMBIENT\_HEARTBEAT\_PERIOD:  
        presence\_heartbeat \= { node\_id: self.id, leader\_id: self.leader\_id, sequence: seq++ }  
        broadcast presence\_heartbeat (unauthenticated, unaddressed)

    ON RECEIVE presence\_heartbeat from node M:  
        if packet.sequence \<= last\_seen\_sequence\[M\]:  
            drop   // stale/duplicate  
        if packet.leader\_id \!= self.leader\_id:  
            drop   // foreign network, ignore for connection tracking  
        else if self.connection\_table has spare capacity and M not already known:  
            add M to connection\_table  
            // topology update only — NOT a trust decision;  
            // M still cannot derive a valid K\_AB without K\_master \+ shared space

