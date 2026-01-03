## Satellite Life Extension

### MEV Docking via Capability Tokens

```mermaid
flowchart TB
    subgraph predock["Pre-Dock"]
        A["MEV-3<br/>Servicer"]
        B["Intelsat 10-02<br/>Client"]
    end

    subgraph dock["Docking Sequence"]
        W1["50m waypoint<br/>Ground approval"]
        W2["20m waypoint<br/>Autonomous"]
        W3["5m waypoint<br/>Ground approval"]
        CAP["Capture"]
    end

    subgraph ops["Combined Operations"]
        STACK["MEV + Intelsat<br/>Combined Stack"]
    end

    A --> W1 --> W2 --> W3 --> CAP
    B --- W3
    CAP --> STACK

    style STACK fill:#3fb950
```

**Docking Authorization Token:**
- Contact velocity: < 0.05 m/s
- Interface: LAE nozzle capture ring
- Abort conditions: attitude, velocity, anomaly

**Life Extension:**
| Metric | Value |
|--------|-------|
| Original EOL | 2025-06 |
| Extended EOL | 2030-01 |
| Revenue preserved | $180M |
