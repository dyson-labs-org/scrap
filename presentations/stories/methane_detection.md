## Methane Super-Emitter Detection

### Two-Phase Auction: Survey + Quantification

```mermaid
flowchart TB
    subgraph phase1["Phase 1: Wide-Area Survey"]
        MSAT["MethaneSAT<br/>bid: 9.2 WINNER"]
        S5P["Sentinel-5P<br/>bid: 18"]
    end

    subgraph phase2["Phase 2: Point-Source"]
        GHG["GHGSat-C2<br/>bid: 8.4 WINNER"]
        MSAT2["MethaneSAT<br/>bid: 15"]
    end

    REQ["CATF Request<br/>Permian Basin"] --> phase1
    MSAT -->|7 plumes detected| phase2
    GHG --> OUT["Facility-level<br/>emission rates"]

    style MSAT fill:#3fb950
    style GHG fill:#3fb950
```

**Complementary Sensors:**
| Phase | Winner | Resolution | Detection |
|-------|--------|------------|-----------|
| Survey | MethaneSAT | 400m | >100 kg/hr |
| Quantify | GHGSat | 25m | >20 kg/hr |

**Output:** 15,200 kg/hr emissions from 7 super-emitters

**Timeline:** 4 hours (vs days of manual coordination)
