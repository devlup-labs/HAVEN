/**
 * HAVEN Co-Simulation Visualizer - Application Controller
 * Handles WebSocket communication, UI telemetry updates, node inspector,
 * packet chronicle, chaos controls, and preset topology management.
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const statusPill = document.getElementById('statusPill');
  const statusText = document.getElementById('statusText');
  const btnStart = document.getElementById('btnStart');
  const btnPause = document.getElementById('btnPause');
  const btnStep = document.getElementById('btnStep');
  const btnStop = document.getElementById('btnStop');
  const btnReset = document.getElementById('btnReset');
  const speedSlider = document.getElementById('speedSlider');
  const speedVal = document.getElementById('speedVal');
  const presetSelect = document.getElementById('presetSelect');

  // Metrics
  const metricLeader = document.getElementById('metricLeader');
  const metricHop = document.getElementById('metricHop');
  const metricTime = document.getElementById('metricTime');
  const metricFrames = document.getElementById('metricFrames');

  // Counters
  const countDiscovery = document.getElementById('countDiscovery');
  const countElection = document.getElementById('countElection');
  const countPassthrough = document.getElementById('countPassthrough');
  const countClaiming = document.getElementById('countClaiming');
  const countLeader = document.getElementById('countLeader');

  const statBoxDiscovery = document.getElementById('statBoxDiscovery');
  const statBoxElection = document.getElementById('statBoxElection');
  const statBoxClaim = document.getElementById('statBoxClaim');
  const statBoxHeartbeat = document.getElementById('statBoxHeartbeat');
  const statBoxDropped = document.getElementById('statBoxDropped');

  // Node Inspector Elements
  const inspectorEmpty = document.getElementById('inspectorEmpty');
  const inspectorContent = document.getElementById('inspectorContent');
  const inspNodeId = document.getElementById('inspNodeId');
  const inspModeBadge = document.getElementById('inspModeBadge');
  const inspBatteryPct = document.getElementById('inspBatteryPct');
  const inspBatteryFill = document.getElementById('inspBatteryFill');
  const inspSpacesList = document.getElementById('inspSpacesList');
  const inspScore = document.getElementById('inspScore');
  const inspBestOrigin = document.getElementById('inspBestOrigin');
  const inspBestScore = document.getElementById('inspBestScore');
  const inspEchoes = document.getElementById('inspEchoes');
  const inspNeighbours = document.getElementById('inspNeighbours');

  // Packets & Logs
  const packetList = document.getElementById('packetList');
  const filterPills = document.querySelectorAll('.filter-pill');
  const consoleBody = document.getElementById('consoleBody');
  const consoleTabs = document.querySelectorAll('.tab-btn');
  const convergenceBanner = document.getElementById('convergenceBanner');
  const bannerLeaderId = document.getElementById('bannerLeaderId');
  const bannerHop = document.getElementById('bannerHop');

  // Modal
  const modalGenerator = document.getElementById('modalGenerator');
  const btnOpenGenerator = document.getElementById('btnOpenGenerator');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const formGenerator = document.getElementById('formGenerator');

  // Mode buttons
  const btnModeFast = document.getElementById('btnModeFast');
  const btnModeCosim = document.getElementById('btnModeCosim');

  // Application State
  let activeMode = 'fast';
  let simulationStatus = 'IDLE';
  let activeFilter = 'ALL';
  let activeTab = 'events';
  let selectedNode = null;
  let topologyData = null;
  let socket = null;
  let packetHistory = [];

  // Initialize Network Canvas Graph
  const graph = new NetworkGraph('networkCanvas', node => {
    selectedNode = node;
    renderNodeInspector(node);
  });

  // Attach canvas buttons
  document.getElementById('btnZoomIn')?.addEventListener('click', () => graph.zoom(1.2));
  document.getElementById('btnZoomOut')?.addEventListener('click', () => graph.zoom(0.8));
  document.getElementById('btnFit')?.addEventListener('click', () => graph.fitToScreen());

  // ----------------------------------------------------------- WebSocket Setup
  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      addConsoleLine('system', 'Connected to HAVEN Co-Simulation server via WebSocket.', 'success');
    };

    socket.onmessage = e => {
      try {
        const msg = JSON.parse(e.data);
        handleServerMessage(msg);
      } catch (err) {
        console.error('WS parse error:', err);
      }
    };

    socket.onclose = () => {
      addConsoleLine('system', 'WebSocket disconnected. Retrying in 2 seconds...', 'warn');
      setTimeout(connectWebSocket, 2000);
    };

    socket.onerror = err => {
      console.error('WebSocket error:', err);
    };
  }

  function sendCommand(cmd) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(cmd));
    }
  }

  function handleServerMessage(msg) {
    const { type, data } = msg;

    if (type === 'init') {
      activeMode = data.active_mode || 'fast';
      updateModeButtons();
      updateStatus(data.status);
      if (data.topology) {
        topologyData = data.topology;
        graph.setTopology(data.topology);
        updateCountersFromGraph();
      }
      if (data.presets) populatePresets(data.presets);
      if (data.logs) {
        data.logs.forEach(l => addConsoleLine(l.source, l.message, l.level));
      }
    } else if (type === 'status') {
      updateStatus(data);
    } else if (type === 'topology') {
      topologyData = data;
      graph.setTopology(data);
      updateCountersFromGraph();
      if (selectedNode) {
        const refreshed = graph.nodes.get(selectedNode.id);
        if (refreshed) renderNodeInspector(refreshed);
      }
    } else if (type === 'event') {
      handleProtocolEvent(data);
    } else if (type === 'log') {
      addConsoleLine(data.source, data.message, data.level);
    } else if (type === 'speed') {
      if (data.speed !== undefined) {
        speedSlider.value = data.speed;
        speedVal.textContent = `${parseFloat(data.speed).toFixed(1)}x`;
      }
    }
  }

  function handleProtocolEvent(ev) {
    const evType = ev.event;

    if (evType === 'frame_tx') {
      graph.addPacket(ev.src, ev.dst, ev.type, ev.delay_ms);
      addPacketCard(ev.src, ev.dst, ev.type, ev.payload);
      incrementStatCounter(ev.type);
    } else if (evType === 'frame_drop') {
      graph.addDropBurst(ev.src, ev.dst, ev.type);
      addPacketCard(ev.src, ev.dst, 'DROP', { reason: ev.reason });
      incrementStatCounter('DROPPED');
    } else if (evType === 'mode_change') {
      graph.updateNodeState(ev.node_id, { mode: ev.mode });
      updateCountersFromGraph();
      if (selectedNode && selectedNode.id === ev.node_id) {
        renderNodeInspector(graph.nodes.get(ev.node_id));
      }
    } else if (evType === 'echo_received') {
      graph.updateNodeState(ev.node_id, { echo_count: ev.echo_count });
      if (selectedNode && selectedNode.id === ev.node_id) {
        renderNodeInspector(graph.nodes.get(ev.node_id));
      }
    } else if (evType === 'leader_elected') {
      metricLeader.textContent = `Node ${ev.leader_id}`;
      metricLeader.classList.add('highlight-emerald');
      showConvergenceBanner(ev.leader_id, ev.hop || 0);
      graph.updateNodeState(ev.leader_id, { mode: 'LEADER' });
      updateCountersFromGraph();
    } else if (evType === 'step_complete') {
      metricHop.textContent = ev.hop;
      metricTime.textContent = `${ev.time_ms} ms`;
      if (ev.stats) {
        updateStatsDisplays(ev.stats);
      }
      if (ev.leader) {
        metricLeader.textContent = `Node ${ev.leader}`;
      }
    } else if (evType === 'link_state') {
      graph.setLinkState(ev.u, ev.v, ev.disabled);
    } else if (evType === 'node_alive') {
      graph.updateNodeState(ev.node_id, { alive: ev.alive });
    } else if (evType === 'node_battery') {
      graph.updateNodeState(ev.node_id, { battery: ev.battery });
      if (selectedNode && selectedNode.id === ev.node_id) {
        renderNodeInspector(graph.nodes.get(ev.node_id));
      }
    }
  }

  // ----------------------------------------------------------- UI Updates
  function updateStatus(status) {
    if (!status) return;
    simulationStatus = status.status || 'IDLE';

    statusPill.className = `status-pill ${simulationStatus.toLowerCase()}`;
    statusText.textContent = simulationStatus;

    if (status.leader) {
      metricLeader.textContent = `Node ${status.leader}`;
    } else if (simulationStatus === 'RUNNING') {
      metricLeader.textContent = 'Electing...';
    } else {
      metricLeader.textContent = 'None';
    }

    if (status.hop !== undefined) metricHop.textContent = status.hop;
    if (status.sim_time_ms !== undefined) metricTime.textContent = `${status.sim_time_ms} ms`;
    if (status.stats) updateStatsDisplays(status.stats);

    btnStart.style.display = simulationStatus === 'RUNNING' ? 'none' : 'inline-flex';
    btnPause.style.display = simulationStatus === 'RUNNING' ? 'inline-flex' : 'none';
  }

  function updateStatsDisplays(stats) {
    if (statBoxDiscovery) statBoxDiscovery.textContent = stats.DISCOVERY || 0;
    if (statBoxElection) statBoxElection.textContent = stats.ELECTION || 0;
    if (statBoxClaim) statBoxClaim.textContent = stats.CLAIM || 0;
    if (statBoxHeartbeat) statBoxHeartbeat.textContent = stats.HEARTBEAT || 0;
    if (statBoxDropped) statBoxDropped.textContent = stats.DROPPED || 0;
    if (metricFrames) metricFrames.textContent = stats.TOTAL || 0;
  }

  function incrementStatCounter(type) {
    const elMap = {
      'DISCOVERY': statBoxDiscovery,
      'ELECTION': statBoxElection,
      'CLAIM': statBoxClaim,
      'HEARTBEAT': statBoxHeartbeat,
      'DROPPED': statBoxDropped
    };
    const el = elMap[type];
    if (el) {
      el.textContent = (parseInt(el.textContent, 10) || 0) + 1;
    }
    if (metricFrames) {
      metricFrames.textContent = (parseInt(metricFrames.textContent, 10) || 0) + 1;
    }
  }

  function updateCountersFromGraph() {
    const counts = {
      DISCOVERY: 0,
      ELECTION: 0,
      PASSTHROUGH: 0,
      CLAIMING: 0,
      LEADER: 0
    };

    graph.nodes.forEach(nd => {
      if (counts[nd.mode] !== undefined) {
        counts[nd.mode]++;
      }
    });

    countDiscovery.textContent = counts.DISCOVERY;
    countElection.textContent = counts.ELECTION;
    countPassthrough.textContent = counts.PASSTHROUGH;
    countClaiming.textContent = counts.CLAIMING;
    countLeader.textContent = counts.LEADER;
  }

  function showConvergenceBanner(leaderId, hop) {
    bannerLeaderId.textContent = `Node ${leaderId}`;
    bannerHop.textContent = `${hop} hops`;
    convergenceBanner.classList.add('show');
  }

  function hideConvergenceBanner() {
    convergenceBanner.classList.remove('show');
  }

  // ----------------------------------------------------------- Node Inspector
  function renderNodeInspector(node) {
    if (!node) {
      inspectorEmpty.style.display = 'block';
      inspectorContent.style.display = 'none';
      return;
    }

    inspectorEmpty.style.display = 'none';
    inspectorContent.style.display = 'flex';

    inspNodeId.textContent = `Node #${node.id}`;
    inspModeBadge.textContent = node.alive ? node.mode : 'OFFLINE';
    inspModeBadge.className = `node-mode-badge ${node.mode.toLowerCase()}`;

    // Battery
    inspBatteryPct.textContent = `${node.battery}%`;
    inspBatteryFill.style.width = `${node.battery}%`;
    inspBatteryFill.style.background =
      node.battery > 50 ? '#10b981' : node.battery > 20 ? '#f59e0b' : '#f43f5e';

    // TurboBlom spaces
    inspSpacesList.innerHTML = '';
    (node.spaces || []).forEach(s => {
      const chip = document.createElement('span');
      chip.className = 'space-chip';
      chip.textContent = `S${s}`;
      inspSpacesList.appendChild(chip);
    });

    inspScore.textContent = node.score || (node.battery + (node.neighbours ? node.neighbours.length : 0));
    inspBestOrigin.textContent = node.best_origin ? `Node ${node.best_origin}` : '-';
    inspBestScore.textContent = node.best_score || '-';
    inspEchoes.textContent = `${node.echo_count || 0} / 2`;
    inspNeighbours.textContent = (node.neighbours && node.neighbours.length > 0)
      ? node.neighbours.join(', ')
      : 'None';
  }

  // ----------------------------------------------------------- Packet Stream
  function addPacketCard(src, dst, type, payload) {
    const card = document.createElement('div');
    const typeClass = type.toLowerCase();
    card.className = `packet-card ${typeClass}`;
    card.dataset.type = type;

    const timeStr = new Date().toLocaleTimeString().split(' ')[0];
    const dstLabel = (dst === 'all' || dst === 255) ? 'ALL (Broadcast)' : `Node ${dst}`;

    card.innerHTML = `
      <div class="packet-top">
        <span class="packet-type-tag" style="color: ${graph.colors[typeClass] || '#fff'}">${type}</span>
        <span class="packet-time">${timeStr}</span>
      </div>
      <div class="packet-route">
        <span>Node ${src}</span> → <span>${dstLabel}</span>
      </div>
    `;

    packetList.insertBefore(card, packetList.firstChild);
    packetHistory.unshift({ src, dst, type, payload, time: timeStr });

    // Limit cards in DOM
    if (packetList.children.length > 80) {
      packetList.removeChild(packetList.lastChild);
    }

    applyPacketFilter();
  }

  function applyPacketFilter() {
    Array.from(packetList.children).forEach(card => {
      if (activeFilter === 'ALL' || card.dataset.type === activeFilter) {
        card.style.display = 'flex';
      } else {
        card.style.display = 'none';
      }
    });
  }

  filterPills.forEach(pill => {
    pill.addEventListener('click', () => {
      filterPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      activeFilter = pill.dataset.filter;
      applyPacketFilter();
    });
  });

  // ----------------------------------------------------------- Console / Terminal
  function addConsoleLine(source, message, level = 'normal') {
    const line = document.createElement('div');
    line.className = 'log-line';

    const timeStr = new Date().toLocaleTimeString().split(' ')[0];
    line.innerHTML = `
      <span class="log-time">${timeStr}</span>
      <span class="log-src ${source}">${source.toUpperCase()}</span>
      <span class="log-msg ${level}">${escapeHtml(message)}</span>
    `;

    consoleBody.appendChild(line);
    consoleBody.scrollTop = consoleBody.scrollHeight;
  }

  function escapeHtml(str) {
    return str.replace(/[&<>'"]/g, tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      "'": '&#39;',
      '"': '&quot;'
    }[tag] || tag));
  }

  consoleTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      consoleTabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      activeTab = tab.dataset.tab;
      // Tab switcher handling
    });
  });

  // ----------------------------------------------------------- Controls
  btnStart.addEventListener('click', () => {
    hideConvergenceBanner();
    sendCommand({ action: 'start', mode: activeMode });
  });

  btnPause.addEventListener('click', () => {
    sendCommand({ action: 'pause' });
  });

  btnStep.addEventListener('click', () => {
    sendCommand({ action: 'step' });
  });

  btnStop.addEventListener('click', () => {
    sendCommand({ action: 'stop' });
  });

  btnReset.addEventListener('click', () => {
    hideConvergenceBanner();
    sendCommand({ action: 'stop' });
    if (topologyData) {
      graph.setTopology(topologyData);
      updateCountersFromGraph();
    }
  });

  speedSlider.addEventListener('input', e => {
    const val = parseFloat(e.target.value);
    speedVal.textContent = `${val.toFixed(1)}x`;
    sendCommand({ action: 'set_speed', speed: val });
  });

  // Mode switcher
  function updateModeButtons() {
    if (activeMode === 'fast') {
      btnModeFast.classList.add('active');
      btnModeCosim.classList.remove('active');
    } else {
      btnModeFast.classList.remove('active');
      btnModeCosim.classList.add('active');
    }
  }

  btnModeFast.addEventListener('click', () => {
    activeMode = 'fast';
    updateModeButtons();
    addConsoleLine('system', 'Switched mode to: Fast Interactive Simulation', 'info');
  });

  btnModeCosim.addEventListener('click', () => {
    activeMode = 'cosim';
    updateModeButtons();
    addConsoleLine('system', 'Switched mode to: Renode + ns-3 Hardware Co-Simulation', 'info');
  });

  // Presets
  function populatePresets(presets) {
    presetSelect.innerHTML = '';
    presets.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      presetSelect.appendChild(opt);
    });
  }

  presetSelect.addEventListener('change', e => {
    const pid = e.target.value;
    hideConvergenceBanner();
    sendCommand({ action: 'load_preset', preset: pid });
  });

  // ----------------------------------------------------------- Chaos / Fault Injection
  document.getElementById('btnToggleLink')?.addEventListener('click', () => {
    const u = parseInt(document.getElementById('linkNodeA').value, 10);
    const v = parseInt(document.getElementById('linkNodeB').value, 10);
    if (!isNaN(u) && !isNaN(v)) {
      sendCommand({ action: 'toggle_link', u, v });
    }
  });

  document.getElementById('btnToggleNode')?.addEventListener('click', () => {
    const nid = parseInt(document.getElementById('crashNodeId').value, 10);
    if (!isNaN(nid)) {
      sendCommand({ action: 'toggle_node', node_id: nid });
    }
  });

  document.getElementById('btnSetBattery')?.addEventListener('click', () => {
    const nid = parseInt(document.getElementById('battNodeId').value, 10);
    const batt = parseInt(document.getElementById('battLevel').value, 10);
    if (!isNaN(nid) && !isNaN(batt)) {
      sendCommand({ action: 'set_battery', node_id: nid, battery: batt });
    }
  });

  // ----------------------------------------------------------- Topology Generator Modal
  btnOpenGenerator?.addEventListener('click', () => {
    modalGenerator.classList.add('show');
  });

  btnCloseModal?.addEventListener('click', () => {
    modalGenerator.classList.remove('show');
  });

  modalGenerator?.addEventListener('click', e => {
    if (e.target === modalGenerator) {
      modalGenerator.classList.remove('show');
    }
  });

  formGenerator?.addEventListener('submit', e => {
    e.preventDefault();
    const params = {
      num_nodes: parseInt(document.getElementById('genNumNodes').value, 10),
      graph_type: document.getElementById('genGraphType').value,
      loss_pct: parseFloat(document.getElementById('genLossPct').value),
      delay_ms: parseInt(document.getElementById('genDelayMs').value, 10),
      avg_degree: parseFloat(document.getElementById('genAvgDegree').value)
    };

    hideConvergenceBanner();
    sendCommand({ action: 'generate_topology', params });
    modalGenerator.classList.remove('show');
  });

  // Start WebSocket
  connectWebSocket();
});
