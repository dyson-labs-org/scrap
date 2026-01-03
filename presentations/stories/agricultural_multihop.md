## Agricultural Monitoring

### Multi-Hop Relay + Orbital Processing

```mermaid
flowchart LR
    subgraph ground["Ground"]
        AG["AgriTech<br/>Buenos Aires"]
        AWS["AWS GS<br/>Cape Town"]
    end

    subgraph relay["Multi-Hop Relay"]
        IR1["Iridium 168"]
        IR2["Iridium 172"]
    end

    subgraph space["Target + Processing"]
        S2["Sentinel-2C<br/>MSI Imager"]
        ODC["LeoLabs ODC<br/>Edge Processing"]
    end

    AG --> AWS --> IR1 --> IR2 --> S2
    S2 -->|Raw 800MB| ODC
    ODC -->|Products 150MB| AG

    style ODC fill:#58a6ff
```

**Delegation Chain:**
- Each hop validates and extends capability token
- Final token authorizes Sentinel-2C imaging

**Products:** NDVI, NDRE, NDWI crop stress maps

**Latency:** 3h 50m (vs 6+ hours traditional)
