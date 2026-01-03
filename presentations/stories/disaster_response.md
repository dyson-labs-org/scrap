## Multi-Constellation Disaster Response

### Distributed Auction for Tsunami Response

```mermaid
flowchart TB
    subgraph disaster["Tsunami Impact Zone"]
        QUAKE["M8.9 Earthquake<br/>Japan Coast"]
    end

    subgraph auction["Parallel Auctions"]
        SAR["SAR Auction"]
        OPT["Optical Auction"]
        COM["Comms Auction"]
    end

    subgraph winners["Winners"]
        ICEYE["ICEYE X14<br/>SAR"]
        WV3["WorldView-3<br/>Optical"]
        SL["Starlink<br/>Comms"]
    end

    QUAKE --> auction
    SAR --> ICEYE
    OPT --> WV3
    COM --> SL

    subgraph products["6-Hour Delivery"]
        FLOOD["Flood Map<br/>1,250 km2"]
        DAMAGE["Damage Assessment<br/>45,000 buildings"]
        RELAY["Emergency Comms<br/>150 terminals"]
    end

    ICEYE --> FLOOD
    WV3 --> DAMAGE
    SL --> RELAY

    style winners fill:#3fb950
```

**Auction Convergence:** 30 minutes

**vs Traditional:** 12+ hours coordination

**Products delivered:** 6 hours post-event
