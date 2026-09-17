#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/applications-module.h"
#include "ns3/netanim-module.h"
#include <iostream>
#include <vector>
#include <set>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE ("HavenPipeline");

// --- Constants ---
const uint16_t HAVEN_PORT = 9999;
const double MAX_ADJ_NODES = 10.0;
const double l_param = 1.0;
const double m_param = 1.0;

// LCG PRNG parameters
const uint64_t PRNG_A = 1103515245;
const uint64_t PRNG_B = 12345;
const uint64_t PRNG_M = 2147483648; // 2^31

// Packet Types
enum PacketType {
    DISCOVERY = 1,
    ELECTION = 2
};

// --- Custom Application ---
class HavenApp : public Application {
public:
    static TypeId GetTypeId(void) {
        static TypeId tid = TypeId("HavenApp")
            .SetParent<Application>()
            .SetGroupName("Applications")
            .AddConstructor<HavenApp>();
        return tid;
    }

    HavenApp() : m_nodeId(0), m_battery(100.0), m_port(HAVEN_PORT), m_electionMode(false) {}

    virtual ~HavenApp() {}

    void Setup(uint32_t id, double battery) {
        m_nodeId = id;
        m_battery = battery;
        m_seed = 12345 + m_nodeId; // initial random seed
    }

protected:
    virtual void StartApplication() {
        if (!m_socket) {
            TypeId tid = TypeId::LookupByName("ns3::UdpSocketFactory");
            m_socket = Socket::CreateSocket(GetNode(), tid);
            InetSocketAddress local = InetSocketAddress(Ipv4Address::GetAny(), m_port);
            m_socket->Bind(local);
            m_socket->SetAllowBroadcast(true);
            m_socket->SetRecvCallback(MakeCallback(&HavenApp::ReceivePacket, this));
        }

        // 1. Broadcast discovery packet with a slight jitter to prevent collisions
        Simulator::Schedule(Seconds(0.1 + (m_nodeId * 0.05)), &HavenApp::SendDiscovery, this);

        // 2. Wait for 5 seconds to listen, then evaluate election
        Simulator::Schedule(Seconds(5.0), &HavenApp::EvaluateElection, this);
    }

    virtual void StopApplication() {
        if (m_socket) {
            m_socket->Close();
            m_socket = 0;
        }
    }

private:
    uint32_t m_nodeId;
    double m_battery;
    uint16_t m_port;
    Ptr<Socket> m_socket;
    std::set<uint32_t> m_neighbors;
    bool m_electionMode;
    uint32_t m_internalScore;
    uint64_t m_seed;

    uint64_t GetNextRandom() {
        m_seed = (PRNG_A * m_seed + PRNG_B) % PRNG_M;
        return m_seed;
    }

    void SendDiscovery() {
        // Pseudocode step 1: broadcast message to all adjacent nodes
        // Packet: node id, Turboblom public identifier, Time, hash
        
        uint32_t timeSec = Simulator::Now().GetSeconds();
        uint32_t dummyHash = 0xABCD1234;
        uint32_t turboId = m_nodeId + 1000; 
        
        uint8_t buffer[20];
        buffer[0] = DISCOVERY;
        buffer[1] = 0; buffer[2] = 0; buffer[3] = 0;
        
        uint32_t* p32 = (uint32_t*)&buffer[4];
        p32[0] = m_nodeId;
        p32[1] = turboId;
        p32[2] = timeSec;
        p32[3] = dummyHash;
        
        Ptr<Packet> packet = Create<Packet>(buffer, 20);
        Ipv4Address broadcastAddr("255.255.255.255");
        InetSocketAddress dest(broadcastAddr, m_port);
        m_socket->SendTo(packet, 0, dest);
        
        NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " sent DISCOVERY (Time: " << timeSec << ", Hash: " << dummyHash << ")");
    }

    void ReceivePacket(Ptr<Socket> socket) {
        Address from;
        Ptr<Packet> packet = socket->RecvFrom(from);
        
        uint8_t buffer[64];
        packet->CopyData(buffer, packet->GetSize());
        
        uint8_t type = buffer[0];
        
        if (type == DISCOVERY && packet->GetSize() >= 20) {
            uint32_t* p32 = (uint32_t*)&buffer[4];
            uint32_t senderId = p32[0];
            uint32_t turboId = p32[1];
            uint32_t sendTime = p32[2];
            uint32_t hash = p32[3];
            
            uint32_t currTime = Simulator::Now().GetSeconds();
            
            // Pseudocode step 2: check if time is between +- 10s of its own time
            if (abs((int)currTime - (int)sendTime) <= 10) {
                // Check hash
                if (hash == 0xABCD1234) {
                    m_neighbors.insert(senderId);
                    
                    // Calculate turboblom key (Placeholder for actual cryptographic operation)
                    NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " added Node " << senderId << " to neighbors (Total: " << m_neighbors.size() << ")");
                }
            }
        } 
        else if (type == ELECTION && packet->GetSize() >= 24) {
            uint32_t* p32 = (uint32_t*)&buffer[4];
            uint32_t score = p32[0];
            uint32_t originId = p32[1];
            uint32_t replayerId = p32[2];
            uint32_t sendTime = p32[3];
            uint32_t hmac = p32[4];
            
            NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " received ELECTION packet from origin " << originId << " (Score: " << score << ")");
        }
    }

    void EvaluateElection() {
        // Pseudocode step 3
        uint32_t adj_nodes = m_neighbors.size();
        
        // internal score = battery % + number nodes in neighbour list (keep broadcastable variables in int)
        m_internalScore = (uint32_t)m_battery + adj_nodes;
        
        // odds = max ( 1, {l(bat/100) + m(adj nodes/ max adj nodes)}/2)
        double term1 = l_param * (m_battery / 100.0);
        double term2 = m_param * (adj_nodes / MAX_ADJ_NODES);
        double odds = std::max(1.0, (term1 + term2) / 2.0);
        
        // prng = (a.seed+b) mod m
        uint64_t prng = GetNextRandom();
        double prob = (double)prng / (double)PRNG_M;
        
        NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " evaluating election: Odds=" << odds << ", Prob=" << prob << ", Score=" << m_internalScore);
        
        if (odds > prob) {
            m_electionMode = true;
            NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " --> ELECTION MODE");
            SendElection();
        } else {
            m_electionMode = false;
            NS_LOG_UNCOND(Simulator::Now().GetSeconds() << "s | Node " << m_nodeId << " --> PASSTHROUGH MODE");
        }
    }

    void SendElection() {
        // Pseudocode step 4
        // election packet : internal score + origin node id + hmac + replayer node id + current time + hmac
        
        uint8_t buffer[24];
        buffer[0] = ELECTION;
        buffer[1] = 0; buffer[2] = 0; buffer[3] = 0; 
        
        uint32_t* p32 = (uint32_t*)&buffer[4];
        p32[0] = m_internalScore;
        p32[1] = m_nodeId;       // origin node id
        p32[2] = m_nodeId;       // replayer node id
        p32[3] = Simulator::Now().GetSeconds(); // current time
        p32[4] = 0xDEADBEEF;     // hmac dummy
        
        Ptr<Packet> packet = Create<Packet>(buffer, 24);
        Ipv4Address broadcastAddr("255.255.255.255");
        InetSocketAddress dest(broadcastAddr, m_port);
        m_socket->SendTo(packet, 0, dest);
    }
};

int main(int argc, char *argv[]) {
    uint32_t numNodes = 10;
    
    CommandLine cmd;
    cmd.AddValue("numNodes", "Number of nodes in the simulation", numNodes);
    cmd.Parse(argc, argv);
    
    NodeContainer nodes;
    nodes.Create(numNodes);
    
    // Wi-Fi Ad-hoc network setup
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211b);
    
    YansWifiPhyHelper wifiPhy;
    
    // Custom Channel to limit connection radius
    YansWifiChannelHelper wifiChannel;
    wifiChannel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    // Limit transmission radius to 20 meters
    wifiChannel.AddPropagationLoss("ns3::RangePropagationLossModel", 
                                   "MaxRange", DoubleValue(20.0));
    wifiPhy.SetChannel(wifiChannel.Create());
    
    WifiMacHelper wifiMac;
    wifiMac.SetType("ns3::AdhocWifiMac");
    
    NetDeviceContainer devices = wifi.Install(wifiPhy, wifiMac, nodes);
    
    // Mobility model (random layout)
    MobilityHelper mobility;
    mobility.SetPositionAllocator("ns3::RandomRectanglePositionAllocator",
                                  "X", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=50.0]"),
                                  "Y", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=50.0]"));
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);
    
    // Internet Stack
    InternetStackHelper internet;
    internet.Install(nodes);
    
    Ipv4AddressHelper ipv4;
    ipv4.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer ifaces = ipv4.Assign(devices);
    
    // Install the custom application on all nodes
    for (uint32_t i = 0; i < numNodes; ++i) {
        Ptr<HavenApp> app = CreateObject<HavenApp>();
        
        // Randomize battery between 60% and 100%
        double bat = 60.0 + (rand() % 41);
        app->Setup(i, bat);
        
        nodes.Get(i)->AddApplication(app);
        app->SetStartTime(Seconds(0.0));
        app->SetStopTime(Seconds(10.0));
    }
    
    // Setup NetAnim XML generation
    AnimationInterface anim("haven_animation.xml");
    anim.SetConstantPosition(nodes.Get(0), 10.0, 10.0);
    
    // Optional: Make nodes easily identifiable by assigning colors or descriptions
    for (uint32_t i = 0; i < numNodes; ++i) {
        anim.UpdateNodeDescription(nodes.Get(i), "Node " + std::to_string(i));
        anim.UpdateNodeColor(nodes.Get(i), 0, 255, 0); // Green
    }
    
    Simulator::Stop(Seconds(10.0));
    Simulator::Run();
    Simulator::Destroy();
    
    return 0;
}
