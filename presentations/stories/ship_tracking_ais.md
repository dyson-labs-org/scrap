## Maritime Domain Awareness

### Multi-Satellite AIS + SAR Fusion

```mermaid
flowchart TB
    subgraph collection["Coordinated Collection"]
        N1["NORSAT-1<br/>AIS"]
        N2["NORSAT-2<br/>AIS"]
        RCM["RCM-1<br/>AIS + SAR"]
    end

    AOI["Barents Sea<br/>68-75N"] --> N1 & N2 & RCM

    subgraph fusion["Orbital Fusion"]
        PROC["Starlink<br/>Fusion Node"]
    end

    N1 & N2 & RCM --> PROC

    subgraph output["Detection Output"]
        AIS["127 AIS vessels"]
        DARK["23 dark targets"]
        S1["Sentinel-1C<br/>high-res followup"]
    end

    PROC --> AIS & DARK
    DARK --> S1

    style DARK fill:#f85149
```

**Dark Shipping Detection:**
- AIS-only: 127 vessels transmitting
- SAR-only: 23 vessels (AIS disabled)
- Automatic high-res tasking for identification

**Coverage:** 94% AOI in 6-hour window
