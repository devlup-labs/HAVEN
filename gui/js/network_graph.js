/**
 * HAVEN Network Canvas Graph & Packet Animation Engine
 * High-performance 2D Canvas renderer with dynamic packet pulse trails,
 * node drag & drop, zooming, and protocol state visualization.
 */

class NetworkGraph {
  constructor(canvasId, onNodeSelected = null) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.onNodeSelected = onNodeSelected;

    this.nodes = new Map(); // id -> node object
    this.links = []; // list of {a, b, loss_pct, delay_ms, disabled}
    this.packets = []; // list of active flying packets
    this.ripples = []; // list of impact ripples {x, y, radius, color, alpha}

    // Viewport transform
    this.scale = 1.0;
    this.panX = 0;
    this.panY = 0;

    // Interaction state
    this.isDragging = false;
    this.isPanning = false;
    this.draggedNode = null;
    this.hoveredNode = null;
    this.selectedNodeId = null;
    this.lastMousePos = { x: 0, y: 0 };

    // Colors matching theme
    this.colors = {
      discovery: '#00f2fe',
      election: '#f59e0b',
      passthrough: '#64748b',
      claiming: '#a855f7',
      leader: '#10b981',
      drop: '#f43f5e',
      joinRequest: '#ec4899',
      join_request: '#ec4899',
      resignation: '#f97316',
      findLeader: '#818cf8',
      find_leader: '#818cf8',
      leaderAck: '#38bdf8',
      leader_ack: '#38bdf8',
      linkActive: 'rgba(148, 163, 184, 0.22)',
      linkDisabled: 'rgba(244, 63, 94, 0.65)'
    };

    this._setupCanvas();
    this._attachEvents();
    this._startRenderLoop();
  }

  _setupCanvas() {
    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.scale(dpr, dpr);
    this.width = rect.width;
    this.height = rect.height;
  }

  setTopology(topologyData) {
    if (!topologyData) return;

    const rawNodes = topologyData.nodes || [];
    const rawLinks = topologyData.links || [];

    // Keep existing node positions if present
    const existing = new Map(this.nodes);
    this.nodes.clear();

    rawNodes.forEach(nd => {
      const prev = existing.get(nd.id);
      this.nodes.set(nd.id, {
        id: nd.id,
        x: prev ? prev.x : (nd.x || 500),
        y: prev ? prev.y : (nd.y || 500),
        battery: nd.battery !== undefined ? nd.battery : 100,
        spaces: nd.spaces || [],
        mode: nd.mode || 'DISCOVERY',
        score: nd.score || 0,
        best_score: nd.best_score || 0,
        best_origin: nd.best_origin || 0,
        echo_count: nd.echo_count || 0,
        leader_id: nd.leader_id || null,
        alive: nd.alive !== undefined ? nd.alive : true,
        radius: 28,
        neighbours: nd.neighbours || [],
        partition: nd.partition || null
      });
    });

    this.links = rawLinks.map(lk => ({
      a: lk.a,
      b: lk.b,
      loss_pct: lk.loss_pct || 0,
      delay_ms: lk.delay_ms || 20,
      bw_bps: lk.bw_bps || 9600,
      disabled: lk.disabled || false
    }));

    // Auto-fit if newly loaded
    if (!this.fittedOnce && this.nodes.size > 0) {
      this.fitToScreen();
      this.fittedOnce = true;
    }
  }

  updateNodeState(nodeId, updates) {
    const nd = this.nodes.get(nodeId);
    if (nd) {
      Object.assign(nd, updates);
      if (updates.mode === 'LEADER') {
        this.addRipple(nd.x, nd.y, this.colors.leader);
      }
    }
  }

  setLinkState(u, v, disabled) {
    const lk = this.links.find(
      l => (l.a === u && l.b === v) || (l.a === v && l.b === u)
    );
    if (lk) {
      lk.disabled = disabled;
    }
  }

  addPacket(srcId, dstId, type, delayMs = 20) {
    const srcNode = this.nodes.get(srcId);
    if (!srcNode) return;

    let targetNodes = [];
    if (dstId === 'all' || dstId === 255) {
      // Broadcast to all neighbors
      this.links.forEach(lk => {
        if (lk.a === srcId) targetNodes.push(this.nodes.get(lk.b));
        else if (lk.b === srcId) targetNodes.push(this.nodes.get(lk.a));
      });
    } else {
      const target = this.nodes.get(dstId);
      if (target) targetNodes.push(target);
    }

    targetNodes = targetNodes.filter(n => !!n);

    targetNodes.forEach(target => {
      let color = this.colors.discovery;
      if (type === 'ELECTION') color = this.colors.election;
      else if (type === 'CLAIM') color = this.colors.claiming;
      else if (type === 'HEARTBEAT') color = this.colors.leader;
      else if (type === 'JOIN_REQUEST') color = this.colors.joinRequest;
      else if (type === 'RESIGNATION') color = this.colors.resignation;
      else if (type === 'FIND_LEADER') color = this.colors.findLeader;
      else if (type === 'LEADER_ACK') color = this.colors.leaderAck;

      this.packets.push({
        id: Math.random(),
        src: srcNode,
        dst: target,
        type: type,
        color: color,
        progress: 0.0,
        // Calculate speed based on distance and delay
        speed: 0.025 + Math.random() * 0.015,
        tail: []
      });
    });
  }

  addDropBurst(srcId, dstId, type) {
    const src = this.nodes.get(srcId);
    const dst = this.nodes.get(dstId);
    if (!src || !dst) return;

    // Red burst at midpoint
    const midX = (src.x + dst.x) / 2;
    const midY = (src.y + dst.y) / 2;
    this.addRipple(midX, midY, this.colors.drop);
  }

  addRipple(x, y, color) {
    this.ripples.push({
      x,
      y,
      radius: 10,
      maxRadius: 65,
      color,
      alpha: 0.9
    });
  }

  fitToScreen() {
    if (this.nodes.size === 0) return;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    this.nodes.forEach(nd => {
      if (nd.x < minX) minX = nd.x;
      if (nd.x > maxX) maxX = nd.x;
      if (nd.y < minY) minY = nd.y;
      if (nd.y > maxY) maxY = nd.y;
    });

    const graphWidth = Math.max(100, maxX - minX);
    const graphHeight = Math.max(100, maxY - minY);
    const padding = 120;

    const scaleX = (this.width - padding * 2) / graphWidth;
    const scaleY = (this.height - padding * 2) / graphHeight;
    this.scale = Math.min(1.2, Math.min(scaleX, scaleY));

    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    this.panX = this.width / 2 - centerX * this.scale;
    this.panY = this.height / 2 - centerY * this.scale;
  }

  zoom(factor) {
    this.scale = Math.max(0.3, Math.min(3.0, this.scale * factor));
  }

  _attachEvents() {
    this.canvas.addEventListener('mousedown', e => this._onMouseDown(e));
    this.canvas.addEventListener('mousemove', e => this._onMouseMove(e));
    window.addEventListener('mouseup', () => this._onMouseUp());
    this.canvas.addEventListener('wheel', e => this._onWheel(e), { passive: false });

    // Touch support for mobile/trackpads
    this.canvas.addEventListener('touchstart', e => {
      if (e.touches.length === 1) {
        const touch = e.touches[0];
        this._onMouseDown({ clientX: touch.clientX, clientY: touch.clientY, button: 0 });
      }
    });
    this.canvas.addEventListener('touchmove', e => {
      if (e.touches.length === 1) {
        const touch = e.touches[0];
        this._onMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
      }
    });
    this.canvas.addEventListener('touchend', () => this._onMouseUp());
  }

  _screenToWorld(screenX, screenY) {
    const rect = this.canvas.getBoundingClientRect();
    const x = (screenX - rect.left - this.panX) / this.scale;
    const y = (screenY - rect.top - this.panY) / this.scale;
    return { x, y };
  }

  _getNodeAt(worldX, worldY) {
    for (const nd of this.nodes.values()) {
      const dx = nd.x - worldX;
      const dy = nd.y - worldY;
      if (dx * dx + dy * dy <= nd.radius * nd.radius) {
        return nd;
      }
    }
    return null;
  }

  _onMouseDown(e) {
    const world = this._screenToWorld(e.clientX, e.clientY);
    const clickedNode = this._getNodeAt(world.x, world.y);

    if (clickedNode && e.button === 0) {
      this.isDragging = true;
      this.draggedNode = clickedNode;
      this.selectedNodeId = clickedNode.id;
      if (this.onNodeSelected) {
        this.onNodeSelected(clickedNode);
      }
    } else {
      this.isPanning = true;
      this.lastMousePos = { x: e.clientX, y: e.clientY };
    }
  }

  _onMouseMove(e) {
    const world = this._screenToWorld(e.clientX, e.clientY);

    if (this.isDragging && this.draggedNode) {
      this.draggedNode.x = world.x;
      this.draggedNode.y = world.y;
    } else if (this.isPanning) {
      const dx = e.clientX - this.lastMousePos.x;
      const dy = e.clientY - this.lastMousePos.y;
      this.panX += dx;
      this.panY += dy;
      this.lastMousePos = { x: e.clientX, y: e.clientY };
    } else {
      const prevHovered = this.hoveredNode;
      this.hoveredNode = this._getNodeAt(world.x, world.y);
      this.canvas.style.cursor = this.hoveredNode ? 'pointer' : 'grab';
    }
  }

  _onMouseUp() {
    this.isDragging = false;
    this.isPanning = false;
    this.draggedNode = null;
  }

  _onWheel(e) {
    e.preventDefault();
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
    const rect = this.canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const prevScale = this.scale;
    this.zoom(zoomFactor);

    // Zoom towards mouse pointer
    this.panX = mouseX - (mouseX - this.panX) * (this.scale / prevScale);
    this.panY = mouseY - (mouseY - this.panY) * (this.scale / prevScale);
  }

  // ------------------------------------------------------------- Render loop
  _startRenderLoop() {
    const render = () => {
      this._draw();
      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
  }

  _draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.panX, this.panY);
    ctx.scale(this.scale, this.scale);

    // 1. Draw Links
    this._drawLinks(ctx);

    // 2. Draw Ripples
    this._drawRipples(ctx);

    // 3. Draw Flying Packets
    this._drawPackets(ctx);

    // 4. Draw Nodes
    this._drawNodes(ctx);

    ctx.restore();
  }

  _drawLinks(ctx) {
    this.links.forEach(lk => {
      const na = this.nodes.get(lk.a);
      const nb = this.nodes.get(lk.b);
      if (!na || !nb) return;

      ctx.beginPath();
      ctx.moveTo(na.x, na.y);
      ctx.lineTo(nb.x, nb.y);

      const isDeadLink = !na.alive || !nb.alive;
      if (lk.disabled || isDeadLink) {
        ctx.strokeStyle = isDeadLink ? 'rgba(239, 68, 68, 0.35)' : this.colors.linkDisabled;
        ctx.lineWidth = isDeadLink ? 1.5 : 2.5;
        ctx.setLineDash([5, 5]);
      } else {
        ctx.strokeStyle = this.colors.linkActive;
        ctx.lineWidth = 1.8;
        ctx.setLineDash([]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      // Distinct severed / cut indicator badge at midpoint
      if (lk.disabled && !isDeadLink) {
        const mx = (na.x + nb.x) / 2;
        const my = (na.y + nb.y) / 2;
        ctx.save();
        ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
        ctx.beginPath();
        ctx.arc(mx, my, 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#f43f5e';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = '#f43f5e';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('✂', mx, my);
        ctx.restore();
      }

      // Subtle latency badge at link center if hovered
      if (this.hoveredNode && (this.hoveredNode.id === lk.a || this.hoveredNode.id === lk.b)) {
        const mx = (na.x + nb.x) / 2;
        const my = (na.y + nb.y) / 2;
        ctx.fillStyle = 'rgba(11, 15, 25, 0.85)';
        ctx.fillRect(mx - 18, my - 9, 36, 18);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.15)';
        ctx.strokeRect(mx - 18, my - 9, 36, 18);

        ctx.fillStyle = lk.disabled ? '#fda4af' : '#94a3b8';
        ctx.font = '10px JetBrains Mono';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(lk.disabled ? 'DOWN' : `${lk.delay_ms}ms`, mx, my);
      }
    });
  }

  _drawRipples(ctx) {
    for (let i = this.ripples.length - 1; i >= 0; i--) {
      const rip = this.ripples[i];
      rip.radius += 1.8;
      rip.alpha -= 0.025;

      if (rip.alpha <= 0 || rip.radius >= rip.maxRadius) {
        this.ripples.splice(i, 1);
        continue;
      }

      ctx.save();
      ctx.beginPath();
      ctx.arc(rip.x, rip.y, rip.radius, 0, Math.PI * 2);
      ctx.strokeStyle = rip.color;
      ctx.globalAlpha = rip.alpha;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    }
  }

  _drawPackets(ctx) {
    for (let i = this.packets.length - 1; i >= 0; i--) {
      const pkt = this.packets[i];
      pkt.progress += pkt.speed;

      if (pkt.progress >= 1.0) {
        this.addRipple(pkt.dst.x, pkt.dst.y, pkt.color);
        this.packets.splice(i, 1);
        continue;
      }

      // Current position along vector
      const curX = pkt.src.x + (pkt.dst.x - pkt.src.x) * pkt.progress;
      const curY = pkt.src.y + (pkt.dst.y - pkt.src.y) * pkt.progress;

      // Keep tail history
      pkt.tail.push({ x: curX, y: curY });
      if (pkt.tail.length > 8) pkt.tail.shift();

      // Draw packet tail/trail
      ctx.beginPath();
      for (let j = 0; j < pkt.tail.length; j++) {
        const pt = pkt.tail[j];
        if (j === 0) ctx.moveTo(pt.x, pt.y);
        else ctx.lineTo(pt.x, pt.y);
      }
      ctx.strokeStyle = pkt.color;
      ctx.lineWidth = 3;
      ctx.globalAlpha = 0.4;
      ctx.stroke();
      ctx.globalAlpha = 1.0;

      // Draw packet head pulse
      ctx.save();
      ctx.beginPath();
      ctx.arc(curX, curY, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = pkt.color;
      ctx.shadowColor = pkt.color;
      ctx.shadowBlur = 10;
      ctx.fill();
      ctx.restore();
    }
  }

  _drawNodes(ctx) {
    const time = performance.now() * 0.003;

    this.nodes.forEach(nd => {
      const isSelected = this.selectedNodeId === nd.id;
      const isHovered = this.hoveredNode && this.hoveredNode.id === nd.id;

      let modeColor = this.colors.discovery;
      if (nd.mode === 'ELECTION') modeColor = this.colors.election;
      else if (nd.mode === 'PASSTHROUGH') modeColor = this.colors.passthrough;
      else if (nd.mode === 'CLAIMING') modeColor = this.colors.claiming;
      else if (nd.mode === 'LEADER') modeColor = this.colors.leader;

      if (!nd.alive) modeColor = this.colors.drop;

      // 1. Leader Radiant Aura
      if (nd.mode === 'LEADER' && nd.alive) {
        ctx.save();
        const pulse = 1 + 0.15 * Math.sin(time * 3);
        const grad = ctx.createRadialGradient(
          nd.x, nd.y, nd.radius * 0.8,
          nd.x, nd.y, nd.radius * 2.2 * pulse
        );
        grad.addColorStop(0, 'rgba(16, 185, 129, 0.4)');
        grad.addColorStop(1, 'rgba(16, 185, 129, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, nd.radius * 2.2 * pulse, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // 2. Claiming radar beacon
      if (nd.mode === 'CLAIMING' && nd.alive) {
        ctx.save();
        const beaconRadius = nd.radius + ((time * 15) % 30);
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, beaconRadius, 0, Math.PI * 2);
        ctx.strokeStyle = this.colors.claiming;
        ctx.globalAlpha = Math.max(0, 1 - (beaconRadius - nd.radius) / 30);
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
      }

      // 3. Selection Indicator Ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, nd.radius + 7, 0, Math.PI * 2);
        ctx.strokeStyle = '#00f2fe';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // 4. Node Base Circle
      ctx.save();
      ctx.beginPath();
      ctx.arc(nd.x, nd.y, nd.radius, 0, Math.PI * 2);
      ctx.fillStyle = nd.alive ? '#0b1120' : '#1e1b2e';
      ctx.fill();

      // Outer Mode Border
      ctx.strokeStyle = modeColor;
      ctx.lineWidth = isHovered ? 3.5 : 2.5;
      if (nd.mode === 'LEADER') {
        ctx.shadowColor = this.colors.leader;
        ctx.shadowBlur = 15;
      }
      ctx.stroke();
      ctx.restore();

      // 5. Battery Gauge Arc around Node
      if (nd.alive && nd.battery !== undefined) {
        const pct = Math.max(0, Math.min(100, nd.battery)) / 100;
        const startAngle = -Math.PI / 2;
        const endAngle = startAngle + pct * Math.PI * 2;

        ctx.save();
        ctx.beginPath();
        ctx.arc(nd.x, nd.y, nd.radius - 4, startAngle, endAngle);
        ctx.strokeStyle = nd.battery > 50 ? '#34d399' : nd.battery > 20 ? '#fbbf24' : '#f87171';
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.restore();
      }

      // 6. Node ID & Crown / Death Icon
      ctx.save();
      ctx.font = 'bold 13px Outfit, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      if (!nd.alive) {
        ctx.fillStyle = '#f43f5e';
        ctx.fillText(`✕ ${nd.id}`, nd.x, nd.y - 2);
      } else if (nd.mode === 'LEADER') {
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(`👑 ${nd.id}`, nd.x, nd.y - 2);
      } else {
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(`${nd.id}`, nd.x, nd.y - 2);
      }

      // Small battery text under ID
      if (nd.alive) {
        ctx.font = 'bold 9px JetBrains Mono';
        ctx.fillStyle = nd.battery > 50 ? '#34d399' : nd.battery > 20 ? '#fbbf24' : '#f87171';
        ctx.fillText(`${nd.battery}%`, nd.x, nd.y + 11);
      } else {
        ctx.font = 'bold 8px JetBrains Mono';
        ctx.fillStyle = '#f43f5e';
        ctx.fillText('DEAD', nd.x, nd.y + 11);
      }
      ctx.restore();

      // 7. Node Mode Label underneath node
      ctx.save();
      ctx.font = '10px JetBrains Mono';
      ctx.textAlign = 'center';
      ctx.fillStyle = nd.alive ? modeColor : '#f43f5e';
      ctx.fillText(nd.alive ? nd.mode : 'OFFLINE', nd.x, nd.y + nd.radius + 15);
      ctx.restore();

      // 8. Partition Tag if partitioned
      if (nd.alive && nd.partition) {
        ctx.save();
        ctx.font = 'bold 9px JetBrains Mono';
        ctx.textAlign = 'center';
        ctx.fillStyle = nd.partition === 'A' ? '#38bdf8' : '#fb923c';
        ctx.fillText(`Net ${nd.partition}`, nd.x, nd.y - nd.radius - 8);
        ctx.restore();
      }
    });
  }
}
