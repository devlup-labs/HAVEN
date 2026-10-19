// \============================================================  
// HAVEN — Basic Election Pseudocode (core path only)  
// \============================================================

// \---------------- CONSTANTS \----------------  
ECHO\_THRESHOLD   \= \<tuned via simulation\>  
T\_claim          \= \<safety timeout before claimant broadcast\>  
T\_window         \= \<claim window for objections\>  
REPLAY\_WINDOW    \= 10   // seconds, \+/- tolerance on packet timestamps

// \---------------- STATE (per node) \----------------  
self.id  
self.mode              \= DISCOVERY   // DISCOVERY | ELECTION | PASSTHROUGH | CLAIMING | LEADER  
self.internal\_score  
self.neighbour\_list     \= \[\]  
self.best\_known\_score  
self.best\_known\_origin  
self.echo\_count         \= 0  
self.timeout\_started    \= false  
self.epoch\_counter      \= 0

// \============================================================  
// PHASE 1 — NEIGHBOUR DISCOVERY / KEY DERIVATION  
// \============================================================  
1\. BROADCAST discovery\_packet to all adjacent nodes:  
       { node\_id: self.id, turboblom\_spaces: self.space\_list, time: now(), hash }

2\. LISTEN for x seconds, x randomised per node (5 \< x \< 6\)  
   for every received discovery\_packet:  
       if |packet.time \- now()| \> REPLAY\_WINDOW:  
           drop packet  
       else:  
           verify hash; drop if invalid

           shared\_spaces \= self.space\_list ∩ packet.turboblom\_spaces  
           if shared\_spaces is empty:  
               drop  
           else:  
               K\_AB \= derive\_turboblom\_key(self.id, packet.node\_id, shared\_spaces, K\_master)  
               add packet.node\_id to self.neighbour\_list  
               store K\_AB for this neighbour

// \============================================================  
// PHASE 2 — SCORE COMPUTATION AND MODE DECISION  
// \============================================================  
3\. self.internal\_score \= battery\_pct \+ len(self.neighbour\_list)

   odds \= max(1, ( l\*(battery\_pct/100) \+ m\*(len(neighbour\_list)/MAX\_ADJ\_NODES) ) / 2\)

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
           hmac\_score: hmac(...),  
           replayer\_id: self.id,  
           time: now(),  
           hmac\_replay: hmac(...)  
       }  
       broadcast election\_packet to ring neighbours (left \+ right)

       self.best\_known\_score  \= self.internal\_score  
       self.best\_known\_origin \= self.id  
       self.echo\_count        \= 0  
       self.timeout\_started   \= false

// \============================================================  
// PHASE 4 — PACKET RECEPTION  
// \============================================================  
5\. ON RECEIVE election\_packet:  
       if |packet.time \- now()| \> REPLAY\_WINDOW:  
           drop  
       if not verify\_hmac(packet):  
           drop

       if packet.origin\_id \== self.id:  
           self.echo\_count \+= 1  
           if self.echo\_count \>= ECHO\_THRESHOLD and not self.timeout\_started:  
               start\_timer(T\_claim)  
               self.timeout\_started \= true  
           drop packet

       else if packet.score \> self.best\_known\_score  
             or (packet.score \== self.best\_known\_score and packet.origin\_id \> self.best\_known\_origin):  
           self.best\_known\_score  \= packet.score  
           self.best\_known\_origin \= packet.origin\_id  
           self.echo\_count        \= 0  
           self.timeout\_started   \= false

           forward\_packet \= { ...packet, replayer\_id: self.id, time: now(), hmac\_replay: recompute }  
           broadcast forward\_packet to ring neighbours, excluding sender

           if self.mode \== ELECTION:  
               self.mode \= PASSTHROUGH

       else:  
           drop packet

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
// PHASE 7 — CLAIMANT RECEPTION (no objections — just propagate \+ lock)  
// \============================================================  
8\. ON RECEIVE claimant\_packet:  
       verify hmac's and claim\_time freshness; drop if invalid  
       forward claimant\_packet onward (ring propagation, excluding sender)  
       lock local vote for origin\_id \= packet.origin\_id until T\_window expires

// \============================================================  
// PHASE 8 — CONSENSUS FINALIZATION  
// \============================================================  
9\. ON TIMER T\_window EXPIRY (claimant node):  
       self.mode \= LEADER  
       self.epoch\_counter \= 0  
       start LEADER\_HEARTBEAT loop (PHASE 9\)

// \============================================================  
// PHASE 9 — LEADER\_ACTIVE / HEARTBEAT  
// \============================================================  
10\. LEADER loop (self.mode \== LEADER):  
        every epoch tick:  
            self.epoch\_counter \+= 1  
            leader\_heartbeat \= {  
                counter: self.epoch\_counter,  
                leader\_id: self.id,  
                hmac\_counter: hmac(...),  
                hmac\_leader\_id: hmac(...)  
            }  
            broadcast leader\_heartbeat to ring neighbours

    ALL OTHER NODES, on valid leader\_heartbeat:  
        verify hmac \+ counter freshness  
        self.leader\_id \= leader\_id  
        self.mode \= PASSTHROUGH  
