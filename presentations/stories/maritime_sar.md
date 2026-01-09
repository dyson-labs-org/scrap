## Emergency Maritime SAR

### 12-Minute Response via Starlink Relay

```mermaid
sequenceDiagram
    participant USCG as USCG MRCC
    participant IR as Iridium 180
    participant SL as Starlink Mesh
    participant S1 as Sentinel-1C
    participant EDRS as EDRS-C (GEO)
    participant GS as Ground Station

    USCG->>IR: MAYDAY tasking request
    IR->>SL: Relay via ISL mesh
    SL->>S1: Capability token + command
    Note over S1: Validate token<br/>Execute SAR imaging
    S1->>EDRS: 1.8 Gbps laser ISL
    EDRS->>GS: Ka-band downlink
    GS->>USCG: Ship detection products
```

**Key Metrics:**
| Traditional | With SCRAP |
|-------------|-----------|
| 47 min wait | 12 min total |
| Ground pass required | ISL relay |

> **Value**: Lives saved through faster maritime response
