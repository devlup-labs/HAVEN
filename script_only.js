  <script>
    let ringOrder = [];
    let serverNodesData = [];
    let nodeEnergy = {}; // {id: {battery: float, score_base: int}}
    let nodesData = [];
    let leaders = new Set();
    
    const graph = document.getElementById('graph');
    const svg = document.getElementById('links-svg');
    let startTime = null;
    let timerInterval = null;
    
    function updateNodeDOM(id) {
        const el = document.getElementById('node-' + id);
        if (!el) return;
        const e = nodeEnergy[id];
        if (!e) return;
        const currentBat = e.battery.toFixed(1);
        const currentScore = Math.floor(e.battery) + e.nb_n;
        
        // Only update the info div to avoid overwriting the ID text
        const infoDiv = el.querySelector('.node-info');
        if (infoDiv) {
            infoDiv.innerHTML = `Bat: ${currentBat}%<br>Score: ${currentScore}`;
        }
    }

    function updateClock() {
      if (!startTime) return;
      const now = new Date();
      const diff = now - startTime;
      const m = Math.floor(diff / 60000).toString().padStart(2, '0');
      const s = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
      const ms = Math.floor((diff % 1000) / 100).toString();
      document.getElementById('clock').innerText = `${m}:${s}.${ms}`;
    }
    const source = new EventSource('/events');
    
    source.onmessage = function(event) {
      const data = JSON.parse(event.data);
      
      if (data.type === 'search') {
        const srcId = data.source;
        const tgtId = data.target;
        
        const srcIdx = ringOrder.indexOf(srcId);
        const tgtIdx = ringOrder.indexOf(tgtId);
        const N = ringOrder.length;
        
        let distRight = (tgtIdx - srcIdx + N) % N;
        let distLeft = (srcIdx - tgtIdx + N) % N;
        
        let path = [];
        if (distRight <= distLeft) {
            for(let i=0; i<=distRight; i++) path.push(ringOrder[(srcIdx + i) % N]);
        } else {
            for(let i=0; i<=distLeft; i++) path.push(ringOrder[(srcIdx - i + N) % N]);
        }
        
        const links = document.querySelectorAll('.link-line');
        links.forEach(l => { l.style.stroke = '#1e293b'; l.style.strokeWidth = '1'; l.style.strokeDasharray = 'none'; });
        
        const nodes = document.querySelectorAll('.node');
        nodes.forEach(n => { n.style.opacity = '0.3'; });
        
        path.forEach((nodeId, idx) => {
            const el = document.getElementById('node-' + nodeId);
            if (el) {
                el.style.opacity = '1';
                if (idx === 0) el.style.backgroundColor = '#16a34a'; 
                else if (idx === path.length - 1) el.style.backgroundColor = '#eab308';
                else el.style.backgroundColor = '#2563eb'; 
            }
            if (idx < path.length - 1) {
                const n1 = nodeId;
                const n2 = path[idx+1];
                let lEl = document.getElementById('link-' + n1 + '-' + n2) || document.getElementById('link-' + n2 + '-' + n1);
                if (lEl) {
                    lEl.style.stroke = '#60a5fa';
                    lEl.style.strokeWidth = '4';
                    lEl.style.strokeDasharray = 'none';
                }
            }
        });
        
        let notif = document.getElementById('search-notif');
        if (!notif) {
            notif = document.createElement('div');
            notif.id = 'search-notif';
            notif.style.position = 'absolute';
            notif.style.bottom = '20px';
            notif.style.left = '50%';
            notif.style.transform = 'translateX(-50%)';
            notif.style.padding = '12px 24px';
            notif.style.background = '#1e40af';
            notif.style.color = 'white';
            notif.style.borderRadius = '8px';
            notif.style.fontWeight = 'bold';
            notif.style.fontSize = '16px';
            notif.style.zIndex = '100';
            notif.style.boxShadow = '0 4px 6px -1px rgba(0,0,0,0.5)';
            document.body.appendChild(notif);
        }
        notif.innerText = `Leader Tenure Cycle (20s) - Search Path: Node ${srcId} → Node ${tgtId} (${path.length-1} hops)`;
        
        setTimeout(() => {
            links.forEach(l => { l.style.stroke = '#334155'; l.style.strokeWidth = '2'; l.style.strokeDasharray = '4, 4'; });
            nodes.forEach(n => {
                n.style.opacity = '1';
                n.style.backgroundColor = '#1e293b';
                if (n.classList.contains('leader')) n.style.backgroundColor = '#451a03';
            });
            if (notif) notif.innerText = '';
        }, 10000);
      }
      
      if (data.type === 'init') {
        if (!startTime) {
            startTime = new Date();
            timerInterval = setInterval(updateClock, 100);
            
            // Energy Model interval (fixed small rate every time step: 0.2% per second)
            setInterval(() => {
                for (let id in nodeEnergy) {
                    nodeEnergy[id].battery = Math.max(0, nodeEnergy[id].battery - 0.2);
                    updateNodeDOM(id);
                }
            }, 1000);
        }
        ringOrder = data.order;
        serverNodesData = data.nodesData || [];
        serverNodesData.forEach(n => {
            nodeEnergy[n.id] = { battery: n.battery, nb_n: n.score - n.battery };
        });
        document.getElementById('node-count').innerText = ringOrder.length;
        document.querySelector('#header p').innerText = "Live relay active.";
        initGraph();
      } else if (data.type === 'packet') {
        // T_DISCOVERY = 1, T_ELECTION = 2, T_CLAIM = 3, T_HEARTBEAT = 4
        let cls = '';
        if (data.ftype === 1) cls = 'discovery';
        else if (data.ftype === 2) cls = 'election';
        else if (data.ftype === 3) cls = ''; // claim defaults to blue
        else if (data.ftype === 4) {
          cls = 'heartbeat';
          // if a node sends a heartbeat, it is the leader
          if (!leaders.has(data.src)) {
            leaders.add(data.src);
            const nEl = document.getElementById(`node-${data.src}`);
            if (nEl) nEl.classList.add('leader');
          }
        }
        
        data.targets.forEach(target => {
          spawnPacket(data.src, target, cls);
        });
      }
    };
    
    function initGraph() {
      graph.querySelectorAll('.node').forEach(e => e.remove());
      nodesData = [];
      
      const cx = graph.clientWidth / 2;
      const cy = graph.clientHeight / 2;
      const r = (graph.clientWidth / 2) - 40;
      
      // Seedable PRNG for consistent layout
      let seed = 12345;
      function random() {
        seed = (seed * 9301 + 49297) % 233280;
        return seed / 233280;
      }
      
      for (let i = 0; i < ringOrder.length; i++) {
        const id = ringOrder[i];
        
        // Randomly place nodes within the graph area (with padding)
        const padding = 60;
        const width = graph.clientWidth - 2 * padding;
        const height = graph.clientHeight - 2 * padding;
        
        let valid = false;
        let x, y;
        
        // Simple force-directed approach: try to find a spot far from others
        for(let attempts=0; attempts<100; attempts++) {
            x = padding + random() * width;
            y = padding + random() * height;
            
            let min_dist = 1000;
            for(let j=0; j<nodesData.length; j++) {
                const dx = x - nodesData[j].x;
                const dy = y - nodesData[j].y;
                const dist = Math.sqrt(dx*dx + dy*dy);
                if(dist < min_dist) min_dist = dist;
            }
            if(min_dist > 50) break; // Found a good spot
        }
        
        nodesData.push({ id, x, y });
        
        const el = document.createElement('div');
        el.id = 'node-' + id;
        el.className = 'node';
        el.id = `node-${id}`;
        el.style.left = `${x - 20}px`;
        el.style.top = `${y - 20}px`;
        const serverNode = serverNodesData.find(n => n.id === id) || { battery: 0, score: 0 };
        el.innerHTML = `
          ${id}
          <div class="node-info">Bat: ${serverNode.battery}%<br>Score: ${serverNode.score}</div>
        `;
        graph.appendChild(el);
      }
      
      svg.innerHTML = '';
      for (let i = 0; i < ringOrder.length; i++) {
        const nA = nodesData[i];
        const nB = nodesData[(i + 1) % ringOrder.length];
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.id = "link-" + nA.id + "-" + nB.id;
        line.setAttribute("x1", nA.x);
        line.setAttribute("y1", nA.y);
        line.setAttribute("x2", nB.x);
        line.setAttribute("y2", nB.y);
        line.setAttribute("class", "link-line");
        svg.appendChild(line);
      }
    }
    
    function spawnPacket(fromId, toId, cls) {
      const nA = nodesData.find(n => n.id === fromId);
      const nB = nodesData.find(n => n.id === toId);
      if (!nA || !nB) return;
      
      const packet = document.createElement('div');
      packet.className = `packet ${cls}`;
      graph.appendChild(packet);
      
      // Calculate offset based on size
      const size = cls === 'heartbeat' ? 10 : 8;
      const offset = size / 2;
      
      const animation = packet.animate([
        { transform: `translate(${nA.x - offset}px, ${nA.y - offset}px)` },
        { transform: `translate(${nB.x - offset}px, ${nB.y - offset}px)` }
      ], { duration: 150, easing: 'linear' });
      
      animation.onfinish = () => packet.remove();
    }
  </script>
</body>
</html>
