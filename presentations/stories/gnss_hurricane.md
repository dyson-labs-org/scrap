## Hurricane Forecasting

### GNSS Radio Occultation Coordination

```mermaid
flowchart TB
    subgraph storm["Hurricane Maria"]
        EYE(("Storm<br/>Center"))
    end

    subgraph lemurs["Spire Constellation"]
        L1["LEMUR PETERG"]
        L2["LEMUR ZACHARY"]
        L3["LEMUR BROWNCOW"]
    end

    subgraph gnss["GNSS Signals"]
        GPS["GPS"]
        GLO["GLONASS"]
        GAL["Galileo"]
    end

    gnss -->|Signal bending| lemurs
    lemurs -->|67 profiles| AWS["AWS Ground<br/>Stations"]
    AWS --> GFS["NOAA GFS<br/>Assimilation"]
    GFS --> FCST["Improved<br/>Track Forecast"]

    style FCST fill:#3fb950
```

**Atmospheric Profiling:**
- 67 occultation profiles in 6-hour window
- Surface to 40km altitude
- All-weather (works through clouds)

**Forecast Impact:**
| Horizon | Track Improvement |
|---------|-------------------|
| 24 hr | 18 km |
| 48 hr | 35 km |
| 72 hr | 52 km |
