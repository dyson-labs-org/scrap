## Orbital Data Processing

### 95% Downlink Reduction via Edge Computing

```mermaid
flowchart TB
    subgraph sources["Data Sources"]
        S3A["Sentinel-3A<br/>OLCI"]
        S3B["Sentinel-3B<br/>OLCI"]
        JPSS["JPSS-2<br/>VIIRS"]
    end

    subgraph odc["Orbital Data Center"]
        PROC["Loft Orbital YAM-6<br/>NVIDIA Jetson AGX"]
    end

    S3A -->|180 GB/day| PROC
    S3B -->|180 GB/day| PROC
    JPSS -->|450 GB/day| PROC

    PROC -->|35 GB/day| GS["Ground Station"]
    GS --> CRW["NOAA Coral Reef Watch"]

    style PROC fill:#58a6ff
```

**Processing Pipeline (in orbit):**
1. Atmospheric correction
2. Ocean color derivation
3. SST calculation
4. Multi-sensor fusion
5. Anomaly detection

**Data Reduction:**
| Stage | Traditional | Orbital |
|-------|-------------|---------|
| Downlink | 810 GB | 35 GB |
| Latency | 24+ hours | 6.5 hours |

**Output:** Coral bleaching alerts 4x faster
