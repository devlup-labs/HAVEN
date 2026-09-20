#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/applications-module.h"
#include "ns3/netanim-module.h"

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <iostream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("HavenTcpBridge");

class BridgeApp : public Application {
public:
    BridgeApp() : m_listenFd(-1), m_clientFd(-1), m_port(0), m_running(false) {}

    virtual ~BridgeApp() {
        if (m_listenFd >= 0) close(m_listenFd);
        if (m_clientFd >= 0) close(m_clientFd);
    }

    void Setup(uint32_t port, Ptr<Socket> wifiSocket) {
        m_port = port;
        m_wifiSocket = wifiSocket;
        m_wifiSocket->SetRecvCallback(MakeCallback(&BridgeApp::HandleWifiReceive, this));
    }

private:
    virtual void StartApplication() {
        m_running = true;

        m_listenFd = socket(AF_INET, SOCK_STREAM, 0);
        if (m_listenFd < 0) {
            NS_FATAL_ERROR("Cannot create socket");
        }

        int opt = 1;
        setsockopt(m_listenFd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        struct sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(m_port);

        if (bind(m_listenFd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
            NS_FATAL_ERROR("Bind failed on port " << m_port);
        }

        if (listen(m_listenFd, 1) < 0) {
            NS_FATAL_ERROR("Listen failed");
        }

        // Set non-blocking
        fcntl(m_listenFd, F_SETFL, O_NONBLOCK);
        
        NS_LOG_UNCOND("Node " << GetNode()->GetId() << " waiting for TCP bridge on port " << m_port);

        Simulator::Schedule(MilliSeconds(10), &BridgeApp::PollSockets, this);
    }

    virtual void StopApplication() {
        m_running = false;
        if (m_clientFd >= 0) {
            close(m_clientFd);
            m_clientFd = -1;
        }
    }

    void PollSockets() {
        if (!m_running) return;

        // Check for new connection
        if (m_clientFd < 0) {
            struct sockaddr_in client_addr;
            socklen_t client_len = sizeof(client_addr);
            int newFd = accept(m_listenFd, (struct sockaddr *)&client_addr, &client_len);
            if (newFd >= 0) {
                m_clientFd = newFd;
                fcntl(m_clientFd, F_SETFL, O_NONBLOCK);
                NS_LOG_UNCOND("Node " << GetNode()->GetId() << " TCP bridge connected!");
            }
        }

        // Check for data from TCP bridge
        if (m_clientFd >= 0) {
            uint8_t buffer[2048];
            ssize_t bytes = recv(m_clientFd, buffer, sizeof(buffer), 0);
            if (bytes > 0) {
                // Send over WiFi
                Ptr<Packet> packet = Create<Packet>(buffer, bytes);
                Ipv4Address broadcast("255.255.255.255");
                InetSocketAddress dest(broadcast, 9999);
                m_wifiSocket->SendTo(packet, 0, dest);
            } else if (bytes == 0) {
                // Client disconnected
                close(m_clientFd);
                m_clientFd = -1;
                NS_LOG_UNCOND("Node " << GetNode()->GetId() << " TCP bridge disconnected.");
            }
        }

        Simulator::Schedule(MilliSeconds(10), &BridgeApp::PollSockets, this);
    }

    void HandleWifiReceive(Ptr<Socket> socket) {
        Address from;
        Ptr<Packet> packet;
        while ((packet = socket->RecvFrom(from))) {
            if (m_clientFd >= 0) {
                uint8_t buffer[2048];
                packet->CopyData(buffer, packet->GetSize());
                send(m_clientFd, buffer, packet->GetSize(), 0);
            }
        }
    }

    int m_listenFd;
    int m_clientFd;
    uint32_t m_port;
    Ptr<Socket> m_wifiSocket;
    bool m_running;
};


int main(int argc, char *argv[]) {
    uint32_t numNodes = 3;

    CommandLine cmd;
    cmd.AddValue("numNodes", "Number of nodes", numNodes);
    cmd.Parse(argc, argv);

    // Setup Realtime Simulator
    GlobalValue::Bind("SimulatorImplementationType", StringValue("ns3::RealtimeSimulatorImpl"));

    NodeContainer nodes;
    nodes.Create(numNodes);

    MobilityHelper mobility;
    mobility.SetPositionAllocator("ns3::GridPositionAllocator",
                                  "MinX", DoubleValue(0.0),
                                  "MinY", DoubleValue(0.0),
                                  "DeltaX", DoubleValue(5.0),
                                  "DeltaY", DoubleValue(5.0),
                                  "GridWidth", UintegerValue(3),
                                  "LayoutType", StringValue("RowFirst"));
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211b);
    
    YansWifiPhyHelper wifiPhy;
    YansWifiChannelHelper wifiChannel = YansWifiChannelHelper::Default();
    wifiChannel.AddPropagationLoss("ns3::RangePropagationLossModel", "MaxRange", DoubleValue(20.0));
    wifiPhy.SetChannel(wifiChannel.Create());

    WifiMacHelper wifiMac;
    wifiMac.SetType("ns3::AdhocWifiMac");

    NetDeviceContainer devices = wifi.Install(wifiPhy, wifiMac, nodes);

    InternetStackHelper internet;
    internet.Install(nodes);

    Ipv4AddressHelper ipv4;
    ipv4.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = ipv4.Assign(devices);

    // Setup Bridge App per node
    for (uint32_t i = 0; i < numNodes; ++i) {
        Ptr<Socket> wifiSocket = Socket::CreateSocket(nodes.Get(i), UdpSocketFactory::GetTypeId());
        InetSocketAddress local(Ipv4Address::GetAny(), 9999);
        wifiSocket->Bind(local);
        wifiSocket->SetAllowBroadcast(true);

        Ptr<BridgeApp> app = CreateObject<BridgeApp>();
        app->Setup(5000 + i, wifiSocket);
        nodes.Get(i)->AddApplication(app);
        app->SetStartTime(Seconds(0.0));
    }

    AnimationInterface anim("haven-topology.xml");
    for (uint32_t i = 0; i < numNodes; ++i) {
        anim.UpdateNodeDescription(nodes.Get(i), "Node " + std::to_string(i+1));
        anim.UpdateNodeColor(nodes.Get(i), 0, 255, 0); 
    }

    Simulator::Stop(Seconds(3600.0)); // Run for 1 hour or until killed
    Simulator::Run();
    Simulator::Destroy();

    return 0;
}
