## Space Debris Inspection

### Rendezvous and Proximity Operations

```mermaid
flowchart LR
    subgraph approach["Phase 1: Approach"]
        A1["100 km"]
        A2["1 km"]
    end

    subgraph inspect["Phase 2: Inspection"]
        I1["Station-keep<br/>100m"]
        I2["Multi-angle<br/>imaging"]
    end

    subgraph circum["Phase 3: Circumnavigation"]
        C1["LIDAR scan"]
        C2["Debris<br/>detection"]
    end

    ADRAS["ADRAS-J<br/>Inspector"] --> A1 --> A2 --> I1 --> I2 --> C1 --> C2
    ENV["Envisat<br/>(defunct)"] --- I1

    style ENV fill:#f85149
```

**Capability Token Constraints:**
- Min approach: 30m
- Max relative velocity: 0.1 m/s
- Abort triggers: velocity, attitude, debris impact

**Results:**
- 23 debris objects detected within 500m
- 3D LIDAR model at 5cm resolution
- Recent fragmentation event identified

**Value:** Prevent Kessler syndrome cascade
