## Earthquake Response

### GEO Relay for Rapid Imagery

```mermaid
sequenceDiagram
    participant OCHA as UN OCHA
    participant PN as Pleiades Neo 3
    participant EDRS as EDRS-C (GEO)
    participant GS as Weilheim GS

    Note over OCHA: M7.2 Pakistan<br/>Charter activated
    OCHA->>PN: Emergency tasking
    PN->>PN: 30cm imagery acquired
    PN->>EDRS: 1.8 Gbps laser ISL
    Note over EDRS: 12 GB in 54 seconds
    EDRS->>GS: Ka-band 600 Mbps
    GS->>OCHA: Damage assessment

    Note over OCHA: 32 min acquisition to delivery
```

**Without GEO Relay:** 95 minutes (next ground pass)

**With EDRS:** 32 minutes

**Time Saved:** 63 minutes in the "golden hour"

**Damage Assessment:**
- 45,230 buildings analyzed
- 1,823 destroyed
- Critical infrastructure status
