## Volcanic Ash Detection

### Cross-Operator LIDAR via Iridium

```mermaid
sequenceDiagram
    participant EC as EUROCONTROL
    participant IR as Iridium 155
    participant CAL as CALIPSO
    participant TDRS as TDRS-13 (GEO)

    Note over EC: Grimsvotn eruption<br/>Aviation hazard
    EC->>IR: LIDAR profiling request
    IR->>CAL: Pre-issued NASA token
    Note over CAL: 8km proximity pass
    CAL->>CAL: CALIOP profile acquisition
    CAL->>TDRS: Data relay
    TDRS->>EC: Ash layer detection

    Note over EC: Safe flight levels:<br/>FL250 and below CLEAR
```

**Cross-Operator Agreement:**
- NASA pre-issues tokens to Iridium
- Emergency atmospheric hazard authorization
- EUROCONTROL, FAA, ICAO authorized requestors

**Latency:** 1h 45m (vs 3+ hours ground pass)
