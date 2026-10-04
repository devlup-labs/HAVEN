#!/usr/bin/env python3
"""
HAVEN Co-Simulation Visualizer & Control Server.

Full-stack real-time web application server providing:
- Web-based interactive GUI for topology visualization & control
- Dual execution engines:
  1. Fast interactive discrete-event protocol simulation (with stepping & live chaos)
  2. Full Renode ARM Cortex-M3 + ns-3 hardware co-simulation
- Bidirectional WebSocket streaming of flying packets, leader election, and node logs
- REST API for topology generation and preset loading
"""

import asyncio
import copy
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Any, Optional

from aiohttp import web, WSMsgType

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "sim") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "sim"))

from gui.haven_sim_engine import HavenSimEngine
from sim.gen_topology import generate_topology

logging.basicConfig(level=logging.INFO, format="[HAVEN GUI %(asctime)s] %(message)s")
logger = logging.getLogger("haven_gui")

EVENT_FILE = "/tmp/haven_events.jsonl"
LOG_DIR = "/tmp/haven_logs"


class HavenGuiServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.websockets: Set[web.WebSocketResponse] = set()

        # State
        self.active_mode = "fast"  # "fast" or "cosim"
        self.current_topology: Dict[str, Any] = {}
        self.sim_engine: Optional[HavenSimEngine] = None
        self.cosim_process: Optional[asyncio.subprocess.Process] = None
        self.cosim_event_tailer: Optional[asyncio.Task] = None
        self.cosim_log_tailers: Dict[str, asyncio.Task] = {}
        self.log_buffer: List[Dict[str, Any]] = []

        self._load_initial_topology()
        self._setup_routes()

    def _load_initial_topology(self):
        topo_path = ROOT_DIR / "topology.json"
        if topo_path.is_file():
            try:
                self.current_topology = json.loads(topo_path.read_text())
                logger.info(f"Loaded default topology: {len(self.current_topology.get('nodes', []))} nodes")
            except Exception as e:
                logger.error(f"Failed to load topology.json: {e}")
        if not self.current_topology:
            self.current_topology = generate_topology(
                num_nodes=3,
                graph_type="ring",
                loss_pct=0.0,
                delay_ms=20
            )

        self._init_fast_engine()

    def _init_fast_engine(self):
        prev_drain_enabled = self.sim_engine.battery_drain_enabled if self.sim_engine else True
        prev_drain_rate = self.sim_engine.battery_drain_rate if self.sim_engine else 1.0
        prev_node_tx_cost = self.sim_engine.node_tx_cost if self.sim_engine else 0.5
        prev_leader_tx_cost = self.sim_engine.leader_tx_cost if self.sim_engine else 1.5
        if self.sim_engine:
            self.sim_engine.stop()
        self.sim_engine = HavenSimEngine(
            self.current_topology,
            event_callback=self._on_engine_event
        )
        self.sim_engine.battery_drain_enabled = prev_drain_enabled
        self.sim_engine.battery_drain_rate = prev_drain_rate
        self.sim_engine.node_tx_cost = prev_node_tx_cost
        self.sim_engine.leader_tx_cost = prev_leader_tx_cost
        self.sim_engine.tx_cost = prev_node_tx_cost

    def _setup_routes(self):
        # WebSocket
        self.app.router.add_get("/ws", self.handle_websocket)

        # REST API
        self.app.router.add_get("/api/status", self.api_status)
        self.app.router.add_get("/api/topology", self.api_get_topology)
        self.app.router.add_post("/api/topology/load", self.api_load_topology)
        self.app.router.add_post("/api/topology/generate", self.api_generate_topology)
        self.app.router.add_get("/api/presets", self.api_presets)
        self.app.router.add_post("/api/sim/start", self.api_start_sim)
        self.app.router.add_post("/api/sim/stop", self.api_stop_sim)
        self.app.router.add_post("/api/sim/pause", self.api_pause_sim)
        self.app.router.add_post("/api/sim/resume", self.api_resume_sim)
        self.app.router.add_post("/api/sim/step", self.api_step_sim)
        self.app.router.add_post("/api/sim/speed", self.api_set_speed)
        self.app.router.add_post("/api/sim/fault", self.api_inject_fault)
        self.app.router.add_post("/api/sim/battery_drain", self.api_set_battery_drain)
        self.app.router.add_post("/api/sim/recharge", self.api_recharge_all)
        self.app.router.add_post("/api/sim/split", self.api_split_network)
        self.app.router.add_post("/api/sim/join", self.api_join_networks)
        self.app.router.add_get("/api/logs", self.api_get_logs)

        # Static files
        gui_dir = ROOT_DIR / "gui"
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_static("/css", gui_dir / "css")
        self.app.router.add_static("/js", gui_dir / "js")

    async def handle_index(self, request: web.Request) -> web.Response:
        index_file = ROOT_DIR / "gui" / "index.html"
        if index_file.is_file():
            return web.FileResponse(index_file)
        return web.Response(text="HAVEN Visualizer GUI index.html not found.", status=404)

    # ------------------------------------------------------------- WebSockets
    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=15.0)
        await ws.prepare(request)
        self.websockets.add(ws)
        logger.info(f"WebSocket client connected. Total: {len(self.websockets)}")

        # Send initial full state
        await ws.send_json({
            "type": "init",
            "data": {
                "active_mode": self.active_mode,
                "status": self.get_status(),
                "topology": self.get_topology_data(),
                "presets": self.get_preset_list(),
                "logs": self.log_buffer[-100:]
            }
        })

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_ws_command(ws, data)
                    except json.JSONDecodeError:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    logger.warning(f"WebSocket connection closed with error {ws.exception()}")
        finally:
            self.websockets.discard(ws)
            logger.info(f"WebSocket client disconnected. Total: {len(self.websockets)}")
        return ws

    async def broadcast(self, msg_type: str, data: Any):
        if not self.websockets:
            return
        payload = json.dumps({"type": msg_type, "data": data})
        coros = [ws.send_str(payload) for ws in list(self.websockets) if not ws.closed]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    def _on_engine_event(self, ev: Dict[str, Any]):
        """Callback from HavenSimEngine synchronously dispatched to async loop."""
        asyncio.create_task(self._process_and_broadcast_event(ev))

    async def _process_and_broadcast_event(self, ev: Dict[str, Any]):
        ev_type = ev.get("event")

        # Format log entries for UI
        if ev_type == "frame_tx":
            log_line = f"TX {ev['type']} | Node {ev['src']} -> Node {ev['dst']} ({ev.get('delay_ms', 20)}ms)"
            self._add_log("sim", log_line)
        elif ev_type == "frame_drop":
            log_line = f"DROP {ev['type']} | Node {ev['src']} -> Node {ev['dst']} [{ev.get('reason')}]"
            self._add_log("sim", log_line, level="warn")
        elif ev_type == "mode_change":
            log_line = f"STATE | Node {ev['node_id']} => {ev['mode']}"
            self._add_log("sim", log_line, level="info")
        elif ev_type == "leader_elected":
            log_line = f"CONVERGENCE! Node {ev['leader_id']} elected LEADER (Score {ev.get('score')}) in {ev.get('hop')} hops"
            self._add_log("protocol", log_line, level="success")
        elif ev_type == "leader_lost":
            log_line = f"FAILOVER ALERT: Leader Node {ev.get('former_leader')} is offline! Initiating consensus re-election..."
            self._add_log("protocol", log_line, level="warn")
        elif ev_type == "re_election_started":
            alive_str = ", ".join(f"#{x}" for x in ev.get("alive_nodes", []))
            log_line = f"RE-ELECTION underway across surviving nodes: [{alive_str}]"
            self._add_log("protocol", log_line, level="info")
        elif ev_type == "node_alive":
            status_str = "REVIVED" if ev.get("alive") else "KILLED (OFFLINE)"
            log_line = f"CHAOS INJECTION: Node {ev.get('node_id')} {status_str}"
            self._add_log("chaos", log_line, level="info" if ev.get("alive") else "warn")
        elif ev_type == "node_battery_depleted":
            log_line = f"BATTERY DEPLETED: Node #{ev.get('node_id')} reached 0%! Going OFFLINE."
            self._add_log("chaos", log_line, level="error")
        elif ev_type == "network_split":
            log_line = f"PHASE 12: Network split into {len(ev.get('partitions', []))} partitions! Severed links: {ev.get('severed_links')}"
            self._add_log("protocol", log_line, level="warn")
        elif ev_type == "network_join":
            log_line = f"PHASE 13: Bridge links reconnected: {ev.get('reconnected_links')}! Initiating network merge..."
            self._add_log("protocol", log_line, level="info")
        elif ev_type == "join_request_initiated":
            log_line = f"MERGE: Border node #{ev.get('border_node')} detected foreign leader #{ev.get('foreign_leader')}. Emitting JOIN_REQUEST -> Leader #{ev.get('target_leader')}"
            self._add_log("protocol", log_line, level="info")
        elif ev_type == "join_request_received_at_leader":
            log_line = f"MERGE: Leader #{ev.get('leader_id')} received JOIN_REQUEST (count {ev.get('count')}/{ev.get('threshold')})"
            self._add_log("protocol", log_line, level="warn")
        elif ev_type == "partition_confirmed":
            log_line = f"PARTITION: Segment {ev.get('component_nodes')} isolated from leader! Triggering local re-election..."
            self._add_log("protocol", log_line, level="warn")
        elif ev_type == "leader_resigned":
            reason = ev.get("reason", "low_battery")
            if reason == "network_merge":
                log_line = f"PHASE 13 RESIGNATION: Leader #{ev.get('former_leader')} stepped down to merge with foreign network (Leader #{ev.get('foreign_leader')})!"
            else:
                log_line = f"LEADER HANDOVER: Leader Node #{ev.get('former_leader')} battery critical ({ev.get('battery')}%)! Resigning leadership."
            self._add_log("protocol", log_line, level="warn")
        elif ev_type == "battery_drain_config":
            status_str = "ENABLED" if ev.get("enabled") else "DISABLED"
            log_line = (f"BATTERY DRAIN: {status_str} at rate {ev.get('rate')}x "
                        f"(General: {ev.get('node_tx_cost')}%, Leader: {ev.get('leader_tx_cost')}%)")
            self._add_log("chaos", log_line, level="info")

        await self.broadcast("event", ev)

    def _add_log(self, source: str, message: str, level: str = "normal"):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "source": source,
            "message": message,
            "level": level
        }
        self.log_buffer.append(entry)
        if len(self.log_buffer) > 500:
            self.log_buffer.pop(0)
        asyncio.create_task(self.broadcast("log", entry))

    async def handle_ws_command(self, ws: web.WebSocketResponse, cmd: Dict[str, Any]):
        action = cmd.get("action")
        if action == "start":
            mode = cmd.get("mode", self.active_mode)
            await self.start_simulation(mode)
        elif action == "stop":
            await self.stop_simulation()
        elif action == "pause":
            if self.sim_engine and self.active_mode == "fast":
                self.sim_engine.pause()
        elif action == "resume":
            if self.sim_engine and self.active_mode == "fast":
                self.sim_engine.resume()
        elif action == "step":
            if self.sim_engine and self.active_mode == "fast":
                self.sim_engine.step()
        elif action == "set_speed":
            speed = float(cmd.get("speed", 1.0))
            if self.sim_engine:
                self.sim_engine.speed = max(0.1, min(10.0, speed))
            await self.broadcast("speed", {"speed": self.sim_engine.speed if self.sim_engine else 1.0})
        elif action == "toggle_link":
            u, v = cmd.get("u"), cmd.get("v")
            if u is not None and v is not None and self.sim_engine:
                st = self.sim_engine.toggle_link(u, v)
                self._add_log("chaos", f"Link ({u}, {v}) {'DISABLED' if st else 'ENABLED'}", "warn" if st else "info")
        elif action == "toggle_node":
            nid = cmd.get("node_id")
            if nid is not None and self.sim_engine:
                alive = self.sim_engine.toggle_node(nid)
                await self.broadcast("status", self.get_status())
        elif action == "set_battery":
            nid, b = cmd.get("node_id"), cmd.get("battery")
            if nid is not None and b is not None and self.sim_engine:
                self.sim_engine.set_node_battery(nid, b)
                self._add_log("chaos", f"Node {nid} battery adjusted to {b}%", "info")
                await self.broadcast("status", self.get_status())
        elif action == "set_battery_drain":
            en = cmd.get("enabled")
            rt = cmd.get("rate")
            node_tx = cmd.get("node_tx_cost")
            leader_tx = cmd.get("leader_tx_cost")
            if self.sim_engine:
                self.sim_engine.set_battery_drain(en, rt, node_tx, leader_tx)
                en_str = "ENABLED" if self.sim_engine.battery_drain_enabled else "DISABLED"
                self._add_log("chaos", f"Dynamic Battery Drain set to {en_str} ({self.sim_engine.battery_drain_rate}x, Node TX: {self.sim_engine.node_tx_cost}%, Leader TX: {self.sim_engine.leader_tx_cost}%)", "info")
                await self.broadcast("status", self.get_status())
        elif action == "recharge_all":
            if self.sim_engine:
                self.sim_engine.recharge_all_nodes()
                self._add_log("chaos", "All nodes recharged to 100% capacity", "success")
                await self.broadcast("status", self.get_status())
        elif action == "drain_leader":
            if self.sim_engine:
                if self.sim_engine.leader is not None:
                    b = cmd.get("battery", 15)
                    ldr_id = self.sim_engine.leader
                    self.sim_engine.set_node_battery(ldr_id, b)
                    self._add_log("chaos", f"Leader Node {ldr_id} battery drained to {b}%", "warn")
                    await self.broadcast("status", self.get_status())
                else:
                    self._add_log("chaos", "Cannot drain leader: No leader currently elected yet", "warn")
        elif action == "split_network":
            if self.sim_engine:
                cut_links = cmd.get("cut_links")
                res = self.sim_engine.split_network(cut_links)
                await self.broadcast("topology", self.get_topology_data())
                await self.broadcast("status", self.get_status())
        elif action == "join_networks":
            if self.sim_engine:
                bridge_links = cmd.get("bridge_links")
                res = self.sim_engine.join_networks(bridge_links)
                await self.broadcast("topology", self.get_topology_data())
                await self.broadcast("status", self.get_status())
        elif action == "load_preset":
            preset_id = cmd.get("preset")
            await self.load_preset(preset_id)
        elif action == "generate_topology":
            params = cmd.get("params", {})
            await self.generate_new_topology(params)

    # ------------------------------------------------------------- Simulation controls
    async def start_simulation(self, mode: str):
        self.active_mode = mode
        if mode == "fast":
            await self.stop_cosim()
            self._init_fast_engine()
            self.sim_engine.start_async()
            self._add_log("sim", "Starting Fast Interactive Protocol Simulation", "info")
        elif mode == "cosim":
            if self.sim_engine:
                self.sim_engine.stop()
            await self.start_cosim()
        await self.broadcast("status", self.get_status())

    async def stop_simulation(self):
        if self.active_mode == "fast":
            if self.sim_engine:
                self.sim_engine.stop()
        elif self.active_mode == "cosim":
            await self.stop_cosim()
        self._add_log("sim", "Simulation stopped.", "info")
        await self.broadcast("status", self.get_status())

    # ------------------------------------------------------------- Co-Simulation (Renode + ns-3)
    async def start_cosim(self):
        await self.stop_cosim()
        self._add_log("cosim", "Launching Renode + ns-3 Hardware Co-Simulation...", "info")

        # Save current topology to a temporary file
        active_topo_path = ROOT_DIR / "topology_gui.json"
        active_topo_path.write_text(json.dumps(self.current_topology, indent=2))

        # Clear event file
        if os.path.exists(EVENT_FILE):
            try:
                os.remove(EVENT_FILE)
            except OSError:
                pass
        Path(EVENT_FILE).touch()

        # Run start_haven.sh
        cmd = [
            "/bin/bash",
            str(ROOT_DIR / "start_haven.sh"),
            "--topology", str(active_topo_path),
            "--verbose"
        ]

        env = dict(os.environ)
        env["HAVEN_EVENT_FILE"] = EVENT_FILE
        env["PYTHONPATH"] = f"{ROOT_DIR}:{ROOT_DIR}/sim:{ROOT_DIR}/bridge"

        try:
            self.cosim_process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ROOT_DIR),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid
            )
            logger.info(f"Co-simulation process started with PID {self.cosim_process.pid}")
            self._add_log("cosim", f"Co-simulation launcher started (PID {self.cosim_process.pid})", "info")

            # Start background reader for process stdout
            asyncio.create_task(self._tail_cosim_stdout())

            # Start event file tailer
            self.cosim_event_tailer = asyncio.create_task(self._tail_cosim_events())

        except Exception as e:
            logger.error(f"Failed to launch co-simulation: {e}")
            self._add_log("cosim", f"Failed to launch co-simulation: {e}", "warn")

    async def _tail_cosim_stdout(self):
        if not self.cosim_process or not self.cosim_process.stdout:
            return
        while True:
            line = await self.cosim_process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                # Strip ANSI codes for web display
                clean = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)
                self._add_log("start_haven", clean, "info")

        rc = await self.cosim_process.wait()
        self._add_log("cosim", f"Co-simulation exited with code {rc}", "info" if rc == 0 else "warn")
        await self.broadcast("status", self.get_status())

    async def _tail_cosim_events(self):
        """Tail /tmp/haven_events.jsonl and emit real-time packet animations."""
        file_pos = 0
        try:
            while self.cosim_process and self.cosim_process.returncode is None:
                if os.path.exists(EVENT_FILE):
                    with open(EVENT_FILE, "r") as f:
                        f.seek(file_pos)
                        lines = f.readlines()
                        file_pos = f.tell()

                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                ev = json.loads(line)
                                ev_type = ev.get("event")
                                if ev_type == "tx":
                                    # Convert to canvas packet animation
                                    await self.broadcast("event", {
                                        "event": "frame_tx",
                                        "pkt_id": f"cosim_{int(time.time()*1000)%100000}",
                                        "src": ev["src"],
                                        "dst": ev["dst"] if ev["dst"] != 255 else "all",
                                        "type": ev["type"],
                                        "payload": ev,
                                        "delay_ms": 20
                                    })
                                elif ev_type == "rx":
                                    await self.broadcast("event", {
                                        "event": "frame_rx",
                                        "src": ev["src"],
                                        "dst": ev["dst"],
                                        "type": ev["type"]
                                    })
                                elif ev_type == "leader":
                                    await self.broadcast("event", {
                                        "event": "leader_elected",
                                        "leader_id": ev["leader_id"],
                                        "time_ms": ev.get("time", 0)
                                    })
                            except Exception:
                                pass
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            pass

    async def stop_cosim(self):
        if self.cosim_event_tailer and not self.cosim_event_tailer.done():
            self.cosim_event_tailer.cancel()
        if self.cosim_process and self.cosim_process.returncode is None:
            try:
                os.killpg(os.getpgid(self.cosim_process.pid), signal.SIGTERM)
                await asyncio.sleep(0.5)
                if self.cosim_process.returncode is None:
                    os.killpg(os.getpgid(self.cosim_process.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            self.cosim_process = None

    # ------------------------------------------------------------- State & Presets
    def get_status(self) -> Dict[str, Any]:
        engine_status = self.sim_engine.status if self.sim_engine else "IDLE"
        if self.active_mode == "cosim":
            is_running = self.cosim_process is not None and self.cosim_process.returncode is None
            engine_status = "RUNNING" if is_running else "IDLE"

        partitions = self.sim_engine.get_active_partitions() if self.sim_engine else []
        active_leaders = [p["leader"] for p in partitions if p.get("leader") is not None] if partitions else ([self.sim_engine.leader] if self.sim_engine and self.sim_engine.leader else [])

        return {
            "mode": self.active_mode,
            "status": engine_status,
            "leader": self.sim_engine.leader if self.sim_engine else None,
            "leaders": active_leaders,
            "is_partitioned": len(partitions) > 1,
            "partitions": partitions,
            "hop": self.sim_engine.hop if self.sim_engine else 0,
            "sim_time_ms": self.sim_engine.sim_time_ms if self.sim_engine else 0,
            "speed": self.sim_engine.speed if self.sim_engine else 1.0,
            "battery_drain_enabled": self.sim_engine.battery_drain_enabled if self.sim_engine else True,
            "battery_drain_rate": self.sim_engine.battery_drain_rate if self.sim_engine else 1.0,
            "node_tx_cost": self.sim_engine.node_tx_cost if self.sim_engine else 0.5,
            "leader_tx_cost": self.sim_engine.leader_tx_cost if self.sim_engine else 1.5,
            "stats": self.sim_engine.stats if self.sim_engine else {},
            "num_nodes": len(self.current_topology.get("nodes", [])),
            "num_links": len(self.current_topology.get("links", []))
        }

    def get_topology_data(self) -> Dict[str, Any]:
        if self.sim_engine:
            return self.sim_engine.get_topology_dict()
        return self.current_topology

    def get_preset_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": "mesh_10",
                "name": "Erdos-Renyi Mesh (10 Nodes, 23 Links)",
                "description": "Standard benchmark topology from topology.json with 15% link loss",
                "nodes": 10,
                "type": "erdos-renyi"
            },
            {
                "id": "ring_3",
                "name": "Minimal Ring (3 Nodes)",
                "description": "Fast minimal ring conforming to 3 <= N <= 10 constraint",
                "nodes": 3,
                "type": "ring"
            },
            {
                "id": "ring_5",
                "name": "Chordal Ring (5 Nodes)",
                "description": "5-node circular ring election with echo traversal",
                "nodes": 5,
                "type": "ring"
            },
            {
                "id": "ring_8",
                "name": "8-Node Ring",
                "description": "8-node ring showcasing multi-hop directional flooding",
                "nodes": 8,
                "type": "ring"
            },
            {
                "id": "dense_12",
                "name": "Dense Sensor Mesh (12 Nodes)",
                "description": "High-degree sensor grid with redundant TurboBlom key spaces",
                "nodes": 12,
                "type": "erdos-renyi"
            },
            {
                "id": "dual_ring_split",
                "name": "Dual Partitioned Rings (8 Nodes, 2 Clusters)",
                "description": "Two 4-node rings (Network A & B) with bridge links (2,5) & (3,8) ready for Split/Join",
                "nodes": 8,
                "type": "dual-ring"
            }
        ]

    async def load_preset(self, preset_id: str):
        if preset_id == "mesh_10":
            topo_path = ROOT_DIR / "topology.json"
            if topo_path.is_file():
                self.current_topology = json.loads(topo_path.read_text())
        elif preset_id == "ring_3":
            self.current_topology = generate_topology(num_nodes=3, graph_type="ring", loss_pct=0.0)
        elif preset_id == "ring_5":
            self.current_topology = generate_topology(num_nodes=5, graph_type="ring", loss_pct=0.0)
        elif preset_id == "ring_8":
            self.current_topology = generate_topology(num_nodes=8, graph_type="ring", loss_pct=0.0)
        elif preset_id == "dense_12":
            self.current_topology = generate_topology(num_nodes=12, graph_type="erdos-renyi", target_avg_degree=5.0, loss_pct=10.0)
        elif preset_id == "dual_ring_split":
            from sim.turboblom import assign_spaces
            k_master = bytes(range(32))
            nodes = []
            batt = [100, 80, 60, 40, 70, 90, 50, 30]
            coords = [
                (280, 350), (430, 500), (280, 650), (130, 500),
                (570, 500), (720, 350), (870, 500), (720, 650)
            ]
            for i in range(1, 9):
                nodes.append({
                    "id": i,
                    "battery": batt[i-1],
                    "spaces": assign_spaces(i, 5, 12, k_master),
                    "x": coords[i-1][0],
                    "y": coords[i-1][1]
                })
            links = [
                {"a": 1, "b": 2, "delay_ms": 20, "loss_pct": 0},
                {"a": 2, "b": 3, "delay_ms": 20, "loss_pct": 0},
                {"a": 3, "b": 4, "delay_ms": 20, "loss_pct": 0},
                {"a": 4, "b": 1, "delay_ms": 20, "loss_pct": 0},
                {"a": 5, "b": 6, "delay_ms": 20, "loss_pct": 0},
                {"a": 6, "b": 7, "delay_ms": 20, "loss_pct": 0},
                {"a": 7, "b": 8, "delay_ms": 20, "loss_pct": 0},
                {"a": 8, "b": 5, "delay_ms": 20, "loss_pct": 0},
                {"a": 2, "b": 5, "delay_ms": 20, "loss_pct": 0, "disabled": True},
                {"a": 3, "b": 8, "delay_ms": 20, "loss_pct": 0, "disabled": True},
            ]
            self.current_topology = {
                "meta": {
                    "m_spaces": 12,
                    "k_spaces": 5,
                    "echo_threshold": 2,
                    "default_bridge_links": [[2, 5], [3, 8]],
                    "is_partitioned": True
                },
                "nodes": nodes,
                "links": links
            }

        self._init_fast_engine()
        self._add_log("topology", f"Loaded preset: {preset_id}", "info")
        await self.broadcast("topology", self.get_topology_data())
        await self.broadcast("status", self.get_status())

    async def generate_new_topology(self, params: Dict[str, Any]):
        num_nodes = int(params.get("num_nodes", 5))
        graph_type = params.get("graph_type", "ring")
        loss_pct = float(params.get("loss_pct", 0.0))
        delay_ms = int(params.get("delay_ms", 20))
        avg_degree = float(params.get("avg_degree", 4.0))

        topo = generate_topology(
            num_nodes=num_nodes,
            graph_type=graph_type,
            loss_pct=loss_pct,
            delay_ms=delay_ms,
            target_avg_degree=avg_degree,
            m_spaces=12,
            k_spaces=5
        )
        self.current_topology = topo
        self._init_fast_engine()
        self._add_log("topology", f"Generated new {graph_type} topology with {num_nodes} nodes", "info")
        await self.broadcast("topology", self.get_topology_data())
        await self.broadcast("status", self.get_status())

    # ------------------------------------------------------------- REST Handlers
    async def api_status(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_status())

    async def api_get_topology(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_topology_data())

    async def api_presets(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_preset_list())

    async def api_load_topology(self, request: web.Request) -> web.Response:
        data = await request.json()
        preset_id = data.get("preset")
        if preset_id:
            await self.load_preset(preset_id)
            return web.json_response({"ok": True, "topology": self.get_topology_data()})
        topo_data = data.get("topology")
        if topo_data:
            self.current_topology = topo_data
            self._init_fast_engine()
            await self.broadcast("topology", self.get_topology_data())
            return web.json_response({"ok": True, "topology": self.get_topology_data()})
        return web.json_response({"error": "missing preset or topology"}, status=400)

    async def api_generate_topology(self, request: web.Request) -> web.Response:
        data = await request.json()
        await self.generate_new_topology(data)
        return web.json_response({"ok": True, "topology": self.get_topology_data()})

    async def api_start_sim(self, request: web.Request) -> web.Response:
        data = await request.json() if request.can_read_body else {}
        mode = data.get("mode", self.active_mode)
        await self.start_simulation(mode)
        return web.json_response({"ok": True, "status": self.get_status()})

    async def api_stop_sim(self, request: web.Request) -> web.Response:
        await self.stop_simulation()
        return web.json_response({"ok": True, "status": self.get_status()})

    async def api_pause_sim(self, request: web.Request) -> web.Response:
        if self.sim_engine and self.active_mode == "fast":
            self.sim_engine.pause()
        return web.json_response({"ok": True, "status": self.get_status()})

    async def api_resume_sim(self, request: web.Request) -> web.Response:
        if self.sim_engine and self.active_mode == "fast":
            self.sim_engine.resume()
        return web.json_response({"ok": True, "status": self.get_status()})

    async def api_step_sim(self, request: web.Request) -> web.Response:
        if self.sim_engine and self.active_mode == "fast":
            self.sim_engine.step()
        return web.json_response({"ok": True, "status": self.get_status()})

    async def api_set_speed(self, request: web.Request) -> web.Response:
        data = await request.json()
        speed = float(data.get("speed", 1.0))
        if self.sim_engine:
            self.sim_engine.speed = max(0.1, min(10.0, speed))
        await self.broadcast("speed", {"speed": self.sim_engine.speed if self.sim_engine else 1.0})
        return web.json_response({"ok": True, "speed": self.sim_engine.speed if self.sim_engine else 1.0})

    async def api_inject_fault(self, request: web.Request) -> web.Response:
        data = await request.json()
        fault = data.get("fault")
        if fault == "toggle_link":
            u, v = data.get("u"), data.get("v")
            if u is not None and v is not None and self.sim_engine:
                st = self.sim_engine.toggle_link(u, v)
                return web.json_response({"ok": True, "disabled": st})
        elif fault == "toggle_node":
            nid = data.get("node_id")
            if nid is not None and self.sim_engine:
                alive = self.sim_engine.toggle_node(nid)
                await self.broadcast("status", self.get_status())
                return web.json_response({"ok": True, "alive": alive})
        elif fault == "battery":
            nid, b = data.get("node_id"), data.get("battery")
            if nid is not None and b is not None and self.sim_engine:
                self.sim_engine.set_node_battery(nid, b)
                await self.broadcast("status", self.get_status())
                return web.json_response({"ok": True, "battery": b})
        elif fault == "drain_leader":
            if self.sim_engine:
                if self.sim_engine.leader is not None:
                    b = data.get("battery", 15)
                    ldr_id = self.sim_engine.leader
                    self.sim_engine.set_node_battery(ldr_id, b)
                    await self.broadcast("status", self.get_status())
                    return web.json_response({"ok": True, "leader": ldr_id, "battery": b})
                else:
                    return web.json_response({"ok": False, "error": "No leader currently elected yet"}, status=400)
        elif fault == "recharge":
            if self.sim_engine:
                b = data.get("battery", 100.0)
                self.sim_engine.recharge_all_nodes(b)
                await self.broadcast("status", self.get_status())
                return web.json_response({"ok": True, "battery": b})
        elif fault == "battery_drain":
            if self.sim_engine:
                self.sim_engine.set_battery_drain(
                    data.get("enabled"),
                    data.get("rate"),
                    data.get("node_tx_cost"),
                    data.get("leader_tx_cost")
                )
                await self.broadcast("status", self.get_status())
                return web.json_response({
                    "ok": True,
                    "enabled": self.sim_engine.battery_drain_enabled,
                    "rate": self.sim_engine.battery_drain_rate,
                    "node_tx_cost": self.sim_engine.node_tx_cost,
                    "leader_tx_cost": self.sim_engine.leader_tx_cost
                })
        return web.json_response({"error": "invalid fault"}, status=400)

    async def api_set_battery_drain(self, request: web.Request) -> web.Response:
        data = await request.json()
        en = data.get("enabled")
        rt = data.get("rate")
        node_tx = data.get("node_tx_cost")
        leader_tx = data.get("leader_tx_cost")
        if self.sim_engine:
            self.sim_engine.set_battery_drain(en, rt, node_tx, leader_tx)
            await self.broadcast("status", self.get_status())
            return web.json_response({
                "ok": True,
                "enabled": self.sim_engine.battery_drain_enabled,
                "rate": self.sim_engine.battery_drain_rate,
                "node_tx_cost": self.sim_engine.node_tx_cost,
                "leader_tx_cost": self.sim_engine.leader_tx_cost
            })
        return web.json_response({"error": "sim_engine_offline"}, status=400)

    async def api_recharge_all(self, request: web.Request) -> web.Response:
        data = await request.json() if request.can_read_body else {}
        b = data.get("battery", 100.0)
        if self.sim_engine:
            self.sim_engine.recharge_all_nodes(b)
            await self.broadcast("status", self.get_status())
            return web.json_response({"ok": True, "battery": b})
        return web.json_response({"error": "sim_engine_offline"}, status=400)

    async def api_split_network(self, request: web.Request) -> web.Response:
        data = await request.json() if request.can_read_body else {}
        cut_links = data.get("cut_links")
        if self.sim_engine:
            res = self.sim_engine.split_network(cut_links)
            await self.broadcast("topology", self.get_topology_data())
            await self.broadcast("status", self.get_status())
            return web.json_response({"ok": True, "result": res})
        return web.json_response({"error": "sim_engine_offline"}, status=400)

    async def api_join_networks(self, request: web.Request) -> web.Response:
        data = await request.json() if request.can_read_body else {}
        bridge_links = data.get("bridge_links")
        if self.sim_engine:
            res = self.sim_engine.join_networks(bridge_links)
            await self.broadcast("topology", self.get_topology_data())
            await self.broadcast("status", self.get_status())
            return web.json_response({"ok": True, "result": res})
        return web.json_response({"error": "sim_engine_offline"}, status=400)


    async def api_get_logs(self, request: web.Request) -> web.Response:
        node_id = request.query.get("node")
        if node_id:
            node_log_file = Path(LOG_DIR) / f"node_{node_id}.log"
            if node_log_file.is_file():
                return web.Response(text=node_log_file.read_text(errors="replace")[-50000:])
            return web.Response(text=f"No log file found for node {node_id}")
        return web.json_response(self.log_buffer)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="HAVEN Co-Simulation GUI Server")
    parser.add_argument("--host", default="0.0.0.0", help="host to bind [0.0.0.0]")
    parser.add_argument("--port", type=int, default=8080, help="port to bind [8080]")
    args = parser.parse_args()

    server = HavenGuiServer(host=args.host, port=args.port)
    logger.info(f"Starting HAVEN GUI Server on http://localhost:{args.port}")
    web.run_app(server.app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
