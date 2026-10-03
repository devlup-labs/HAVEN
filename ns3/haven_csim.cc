/*
 * HAVEN -> ns-3 Co-Simulation Scenario
 *
 * Implements the discrete-event network model for HAVEN.
 * Connects to bridge/uart_bridge.py via ZeroMQ ROUTER socket.
 * Reads topology.json to construct nodes, point-to-point links,
 * propagation delays, data rates, and packet loss models.
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <map>
#include <memory>
#include <cstring>
#include <csignal>
#include <zmq.h>
#include <nlohmann/json.hpp>

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/error-model.h"

using namespace ns3;
using json = nlohmann::json;

static void* g_zmq_ctx = nullptr;
static void* g_zmq_sock = nullptr;
static std::string g_bridge_identity = "haven_bridge";
static bool g_verbose = false;

static uint64_t g_rx_frames = 0;
static uint64_t g_tx_frames = 0;

static std::vector<uint8_t> PackEnvelope(uint32_t src, uint32_t dst, const uint8_t* raw, size_t len)
{
    std::vector<uint8_t> env(10 + len);
    env[0] = (src >> 24) & 0xFF;
    env[1] = (src >> 16) & 0xFF;
    env[2] = (src >> 8) & 0xFF;
    env[3] = src & 0xFF;

    env[4] = (dst >> 24) & 0xFF;
    env[5] = (dst >> 16) & 0xFF;
    env[6] = (dst >> 8) & 0xFF;
    env[7] = dst & 0xFF;

    env[8] = (len >> 8) & 0xFF;
    env[9] = len & 0xFF;

    if (len > 0 && raw != nullptr) {
        std::memcpy(&env[10], raw, len);
    }
    return env;
}

class HavenNodeContext {
public:
    uint32_t m_nodeId;
    std::vector<std::pair<uint32_t, Ptr<PointToPointNetDevice>>> m_devices;

    HavenNodeContext(uint32_t id) : m_nodeId(id) {}

    bool OnReceive(Ptr<NetDevice> dev, Ptr<const Packet> packet, uint16_t protocol, const Address& from)
    {
        uint32_t pkt_size = packet->GetSize();
        if (pkt_size < 5) {
            return false;
        }

        std::vector<uint8_t> buf(pkt_size);
        packet->CopyData(buf.data(), pkt_size);

        uint8_t src = buf[3];
        uint8_t ftype = buf[1];
        uint8_t flen = buf[2];

        g_tx_frames++;

        if (g_verbose) {
            std::cout << "[ns-3 " << Simulator::Now().GetSeconds() << "s] packet delivered to node "
                      << m_nodeId << " from " << (int)src << " (type " << (int)ftype
                      << ", " << (int)flen << "B payload)" << std::endl;
        }

        if (g_zmq_sock != nullptr) {
            std::vector<uint8_t> env = PackEnvelope(src, m_nodeId, buf.data(), buf.size());

            zmq_msg_t id_msg;
            zmq_msg_init_size(&id_msg, g_bridge_identity.size());
            std::memcpy(zmq_msg_data(&id_msg), g_bridge_identity.data(), g_bridge_identity.size());
            zmq_msg_send(&id_msg, g_zmq_sock, ZMQ_SNDMORE);

            zmq_msg_t data_msg;
            zmq_msg_init_size(&data_msg, env.size());
            std::memcpy(zmq_msg_data(&data_msg), env.data(), env.size());
            zmq_msg_send(&data_msg, g_zmq_sock, ZMQ_DONTWAIT);
        }

        return true;
    }

    void SendFrame(uint32_t dst, const std::vector<uint8_t>& raw_fr)
    {
        if (dst == 0xFF || dst == 255) {
            // Broadcast
            if (g_verbose) {
                std::cout << "[ns-3 " << Simulator::Now().GetSeconds() << "s] broadcast from node "
                          << m_nodeId << " across " << m_devices.size() << " links" << std::endl;
            }
            for (auto& neighbor : m_devices) {
                Ptr<Packet> pkt = Create<Packet>(raw_fr.data(), raw_fr.size());
                neighbor.second->Send(pkt, neighbor.second->GetBroadcast(), 0x0800);
            }
        } else {
            // Unicast to adjacent peer
            bool sent = false;
            for (auto& neighbor : m_devices) {
                if (neighbor.first == dst) {
                    if (g_verbose) {
                        std::cout << "[ns-3 " << Simulator::Now().GetSeconds() << "s] unicast from "
                                  << m_nodeId << " -> " << dst << std::endl;
                    }
                    Ptr<Packet> pkt = Create<Packet>(raw_fr.data(), raw_fr.size());
                    neighbor.second->Send(pkt, neighbor.second->GetBroadcast(), 0x0800);
                    sent = true;
                    break;
                }
            }
            if (!sent && g_verbose) {
                std::cout << "[ns-3] dropped non-adjacent packet from " << m_nodeId
                          << " to " << dst << std::endl;
            }
        }
    }
};

static std::map<uint32_t, std::shared_ptr<HavenNodeContext>> g_contexts;

static void PollZmq()
{
    if (g_zmq_sock == nullptr) {
        return;
    }

    while (true) {
        zmq_msg_t id_msg;
        zmq_msg_init(&id_msg);
        int rc = zmq_msg_recv(&id_msg, g_zmq_sock, ZMQ_DONTWAIT);
        if (rc == -1) {
            zmq_msg_close(&id_msg);
            break;
        }

        g_bridge_identity.assign((char*)zmq_msg_data(&id_msg), zmq_msg_size(&id_msg));

        zmq_msg_t payload_msg;
        zmq_msg_init(&payload_msg);
        int r2 = zmq_msg_recv(&payload_msg, g_zmq_sock, 0);

        if (r2 >= 10) {
            const uint8_t* p = static_cast<const uint8_t*>(zmq_msg_data(&payload_msg));
            size_t sz = zmq_msg_size(&payload_msg);

            uint32_t src = (p[0] << 24) | (p[1] << 16) | (p[2] << 8) | p[3];
            uint32_t dst = (p[4] << 24) | (p[5] << 16) | (p[6] << 8) | p[7];
            uint16_t ln  = (p[8] << 8) | p[9];

            if (sz >= 10 + ln) {
                std::vector<uint8_t> raw_fr(p + 10, p + 10 + ln);
                g_rx_frames++;
                auto it = g_contexts.find(src);
                if (it != g_contexts.end()) {
                    it->second->SendFrame(dst, raw_fr);
                }
            }
        }

        zmq_msg_close(&id_msg);
        zmq_msg_close(&payload_msg);
    }

    Simulator::Schedule(MilliSeconds(1), &PollZmq);
}

int main(int argc, char* argv[])
{
    std::string topo_file = "topology.json";
    std::string zmq_endpoint = "ipc:///tmp/haven_zmq.sock";
    double duration_s = 90.0;
    bool verbose = false;

    CommandLine cmd(__FILE__);
    cmd.AddValue("topology", "Path to topology.json", topo_file);
    cmd.AddValue("zmq", "ZMQ ROUTER endpoint to bind", zmq_endpoint);
    cmd.AddValue("duration", "Simulation duration in seconds", duration_s);
    cmd.AddValue("verbose", "Verbose logging", verbose);
    cmd.Parse(argc, argv);

    g_verbose = verbose;

    std::ifstream in(topo_file);
    if (!in.is_open()) {
        std::cerr << "error: unable to open topology file: " << topo_file << std::endl;
        return 1;
    }

    json topo;
    try {
        in >> topo;
    } catch (const std::exception& e) {
        std::cerr << "error parsing JSON: " << e.what() << std::endl;
        return 1;
    }

    GlobalValue::Bind("SimulatorImplementationType", StringValue("ns3::RealtimeSimulatorImpl"));

    std::cout << "[ns-3] initializing co-simulation from " << topo_file << std::endl;

    uint32_t max_id = 0;
    std::vector<uint32_t> node_ids;
    for (const auto& nd : topo["nodes"]) {
        uint32_t id = nd["id"];
        node_ids.push_back(id);
        if (id > max_id) max_id = id;
    }

    NodeContainer nodes;
    nodes.Create(max_id + 1);

    std::map<uint32_t, Ptr<Node>> node_map;
    for (uint32_t id : node_ids) {
        node_map[id] = nodes.Get(id);
        g_contexts[id] = std::make_shared<HavenNodeContext>(id);
    }

    int link_count = 0;
    for (const auto& lk : topo["links"]) {
        uint32_t a = lk["a"];
        uint32_t b = lk["b"];
        double loss_pct = lk.value("loss_pct", 0.0);
        int delay_ms = lk.value("delay_ms", 20);
        int bw_bps = lk.value("bw_bps", 9600);

        PointToPointHelper p2p;
        p2p.SetDeviceAttribute("DataRate", StringValue(std::to_string(bw_bps) + "bps"));
        p2p.SetChannelAttribute("Delay", StringValue(std::to_string(delay_ms) + "ms"));

        NetDeviceContainer dev_container = p2p.Install(node_map[a], node_map[b]);
        Ptr<PointToPointNetDevice> dev_a = DynamicCast<PointToPointNetDevice>(dev_container.Get(0));
        Ptr<PointToPointNetDevice> dev_b = DynamicCast<PointToPointNetDevice>(dev_container.Get(1));

        if (loss_pct > 0.0001) {
            Ptr<RateErrorModel> em_a = CreateObject<RateErrorModel>();
            em_a->SetAttribute("ErrorRate", DoubleValue(loss_pct / 100.0));
            em_a->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
            dev_a->SetReceiveErrorModel(em_a);

            Ptr<RateErrorModel> em_b = CreateObject<RateErrorModel>();
            em_b->SetAttribute("ErrorRate", DoubleValue(loss_pct / 100.0));
            em_b->SetAttribute("ErrorUnit", StringValue("ERROR_UNIT_PACKET"));
            dev_b->SetReceiveErrorModel(em_b);
        }

        auto ctx_a = g_contexts[a];
        auto ctx_b = g_contexts[b];

        dev_a->SetReceiveCallback(MakeCallback(&HavenNodeContext::OnReceive, ctx_a.get()));
        dev_b->SetReceiveCallback(MakeCallback(&HavenNodeContext::OnReceive, ctx_b.get()));

        ctx_a->m_devices.push_back({b, dev_a});
        ctx_b->m_devices.push_back({a, dev_b});
        link_count++;
    }

    std::cout << "[ns-3] created " << node_ids.size() << " nodes, " << link_count << " point-to-point links" << std::endl;

    g_zmq_ctx = zmq_ctx_new();
    g_zmq_sock = zmq_socket(g_zmq_ctx, ZMQ_ROUTER);

    int hwm = 10000;
    zmq_setsockopt(g_zmq_sock, ZMQ_SNDHWM, &hwm, sizeof(hwm));
    zmq_setsockopt(g_zmq_sock, ZMQ_RCVHWM, &hwm, sizeof(hwm));

    // Ensure stale socket file is removed before binding
    if (zmq_endpoint.rfind("ipc://", 0) == 0) {
        std::string sock_path = zmq_endpoint.substr(6);
        unlink(sock_path.c_str());
    }

    if (zmq_bind(g_zmq_sock, zmq_endpoint.c_str()) != 0) {
        std::cerr << "error: failed to bind ZMQ socket to " << zmq_endpoint
                  << " (" << strerror(errno) << ")" << std::endl;
        return 1;
    }
    std::cout << "[ns-3] bound ZMQ ROUTER to " << zmq_endpoint << std::endl;

    Simulator::Schedule(MilliSeconds(1), &PollZmq);
    Simulator::Stop(Seconds(duration_s));

    std::cout << "[ns-3] running simulation for " << duration_s << "s..." << std::endl;
    Simulator::Run();

    std::cout << "[ns-3] simulation completed. Rx from ZMQ: " << g_rx_frames
              << ", Tx to ZMQ: " << g_tx_frames << std::endl;

    Simulator::Destroy();

    if (g_zmq_sock != nullptr) {
        zmq_close(g_zmq_sock);
        g_zmq_sock = nullptr;
    }
    if (g_zmq_ctx != nullptr) {
        zmq_ctx_term(g_zmq_ctx);
        g_zmq_ctx = nullptr;
    }

    return 0;
}
