## Wildfire Monitoring

### Hyperspectral Imaging via Auction

```mermaid
flowchart TB
    subgraph auction["Distributed Auction"]
        COORD(("Starlink<br/>Coordinator"))
        PRISMA["PRISMA<br/>bid: 12.3"]
        ENMAP["EnMAP<br/>bid: 8.1"]
        INTUIT["INTUITION-1<br/>bid: 15.7"]
    end

    CAL["CAL FIRE<br/>Dispatch"] --> COORD
    COORD --> PRISMA
    COORD --> ENMAP
    COORD --> INTUIT
    ENMAP -->|WINNER| FIRE["Fire Products"]
    FIRE --> CAL

    style ENMAP fill:#3fb950
```

**Auction Selects Optimal Satellite:**
- Lowest bid (best position + capability)
- EnMAP: Earlier access, full SWIR coverage
- Products: Fire mask, burn severity, fuel type

**Timeline:** 4 hours from request to delivery
