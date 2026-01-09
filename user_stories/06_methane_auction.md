# User Story 06: Methane Super-Emitter Detection via Constellation Auction

> **Note**: This user story illustrates a potential SCRAP application. The distributed auction mechanism (CBBA) shown is **illustrative** and not part of the core SCRAP specification. Initial deployments use pre-negotiated capability tokens. See [AUCTION.md](../future/AUCTION.md) for auction mechanism details.

## Summary

An environmental NGO needs rapid detection and quantification of methane super-emitters at suspected oil and gas facilities. Multiple satellites with methane detection capability bid on the task through a CBBA auction, with the winner providing point-source emission rates.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | Clean Air Task Force (CATF) | - |
| **Auction Coordinator** | OneWeb-0142 | 48934 |
| **Bidder 1** | Sentinel-5P (TROPOMI) | 42969 |
| **Bidder 2** | GHGSat-C2 | 46495 |
| **Bidder 3** | MethaneSAT | 59063 |
| **Winner (Low Res)** | MethaneSAT | 59063 |
| **Winner (High Res)** | GHGSat-C2 | 46495 |
| **Data Relay** | Starlink mesh | Various |
| **Ground Station** | AWS Ground Station, Oregon | - |

## Scenario

### Context

CATF has identified 15 suspected methane super-emitter sites in the Permian Basin. They need:
1. **Wide-area survey**: Identify which facilities are actively emitting
2. **Point-source quantification**: Measure emission rates at detected plumes
3. **Time-series**: Multiple observations for temporal variability

### Two-Phase Auction

Phase 1: Wide-area screening (MethaneSAT wins)
Phase 2: Point-source quantification (GHGSat wins)

```
+--------------+     +-------------+
|    CATF      |---->| AWS Ground  |
|  Request     |     |   Station   |
+--------------+     +------+------+
                            |
                    Upload auction task
                            |
                            v
              +-------------------------+
              |    OneWeb-0142          |
              |  (Auction Coordinator)  |
              +-----------+-------------+
                          |
            +===========================+
            |    PHASE 1: Wide-Area     |
            +===========================+
                          |
            +-------------+-------------+
            |             |             |
            v             v             v
      +----------+  +----------+  +----------+
      |Sentinel-5P|  |MethaneSAT|  | GHGSat  |
      | (bid: 18) |  | (bid: 9) |  |(bid: 25)|
      |   N/A     |  |  WINNER  |  |   N/A   |
      +----------+  +----+-----+  +----------+
                         |
                    Wide-area scan
                         |
                         v
              +-------------------------+
              |  7 Active Emitters      |
              |  Detected               |
              +-----------+-------------+
                          |
            +===========================+
            |  PHASE 2: Point-Source    |
            +===========================+
                          |
            +-------------+-------------+
            |             |             |
            v             v             v
      +----------+  +----------+  +----------+
      |MethaneSAT|  | GHGSat-C2|  |Sentinel-5P|
      | (bid: 15)|  | (bid: 8) |  |(unsuitable)|
      |  N/A     |  |  WINNER  |  |           |
      +----------+  +----+-----+  +----------+
                         |
                    Point measurements
                         |
                         v
              +-------------------------+
              |  Emission Rates for     |
              |  7 Super-Emitters       |
              +-------------------------+
```

### Phase 1 Task Broadcast

```json
{
  "task_id": "METHANE-PERMIAN-2025-001",
  "phase": 1,
  "task_type": "methane_survey",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[
      [-104.5, 31.0], [-102.0, 31.0],
      [-102.0, 33.5], [-104.5, 33.5],
      [-104.5, 31.0]
    ]]
  },
  "requirements": {
    "target_gas": "CH4",
    "detection_sensitivity_ppb": 50,
    "spatial_coverage": "area",
    "spatial_resolution_km_max": 2.0,
    "cloud_cover_max_pct": 30,
    "solar_zenith_angle_max_deg": 70
  },
  "time_window": {
    "earliest": "2025-01-15T16:00:00Z",
    "latest": "2025-01-15T20:00:00Z"
  },
  "objective": "detect_and_localize_plumes"
}
```

### Phase 1 Bids

**MethaneSAT Bid (Winner):**
```json
{
  "task_id": "METHANE-PERMIAN-2025-001",
  "phase": 1,
  "bidder_id": "METHANESAT-59063",
  "bid_value": 9.2,
  "capability_token": "<METHANESAT_CAP_TOKEN>",
  "cost_breakdown": {
    "fuel_kg": 0.005,
    "time_sec": 180,
    "opportunity_cost": 2.8,
    "capability_match": 0.98
  },
  "earliest_execution": "2025-01-15T17:15:00Z",
  "instrument_specs": {
    "name": "MethaneSAT Spectrometer",
    "spectral_range_nm": [1630, 1680],
    "spatial_resolution_km": 0.4,
    "swath_km": 200,
    "precision_ppb": 3,
    "detection_limit_kg_hr": 100
  }
}
```

### Phase 1 Results

MethaneSAT delivers wide-area methane map:

```json
{
  "observation_id": "MSAT-2025-015-1718",
  "acquisition_time": "2025-01-15T17:18:00Z",
  "coverage_km2": 42500,
  "background_ch4_ppb": 1920,
  "plume_detections": [
    {
      "plume_id": "P001",
      "center": {"lat": 32.156, "lon": -103.234},
      "enhancement_ppb": 185,
      "estimated_flux_kg_hr": 2400,
      "confidence": 0.94,
      "source_type": "probable_compressor_station"
    },
    {
      "plume_id": "P002",
      "center": {"lat": 31.892, "lon": -102.567},
      "enhancement_ppb": 420,
      "estimated_flux_kg_hr": 5800,
      "confidence": 0.97,
      "source_type": "probable_flare_stack"
    },
    {
      "plume_id": "P003",
      "center": {"lat": 32.789, "lon": -103.891},
      "enhancement_ppb": 95,
      "estimated_flux_kg_hr": 1100,
      "confidence": 0.85,
      "source_type": "probable_tank_battery"
    }
  ],
  "total_plumes_detected": 7
}
```

### Phase 2 Task Broadcast

Based on Phase 1 results, Phase 2 targets specific facilities:

```json
{
  "task_id": "METHANE-PERMIAN-2025-001",
  "phase": 2,
  "task_type": "methane_point_source",
  "targets": [
    {"plume_id": "P001", "coords": {"lat": 32.156, "lon": -103.234}},
    {"plume_id": "P002", "coords": {"lat": 31.892, "lon": -102.567}},
    {"plume_id": "P003", "coords": {"lat": 32.789, "lon": -103.891}}
  ],
  "requirements": {
    "target_gas": "CH4",
    "spatial_resolution_m_max": 50,
    "quantification_accuracy_pct": 20,
    "individual_source_attribution": true
  },
  "time_window": {
    "earliest": "2025-01-15T18:30:00Z",
    "latest": "2025-01-15T22:00:00Z"
  }
}
```

### Phase 2 GHGSat Bid (Winner)

```json
{
  "task_id": "METHANE-PERMIAN-2025-001",
  "phase": 2,
  "bidder_id": "GHGSAT-C2-46495",
  "bid_value": 8.4,
  "capability_token": "<GHGSAT_CAP_TOKEN>",
  "cost_breakdown": {
    "fuel_kg": 0.012,
    "time_sec": 240,
    "opportunity_cost": 3.1,
    "capability_match": 0.99
  },
  "earliest_execution": "2025-01-15T19:05:00Z",
  "instrument_specs": {
    "name": "WAF-P",
    "spectral_range_nm": [1630, 1675],
    "spatial_resolution_m": 25,
    "swath_km": 12,
    "precision_ppb": 1,
    "detection_limit_kg_hr": 20,
    "attribution_capable": true
  }
}
```

### Phase 2 Results

GHGSat provides facility-level quantification:

```json
{
  "observation_id": "GHGSAT-2025-015-1908",
  "acquisition_time": "2025-01-15T19:08:00Z",
  "targets_measured": 7,
  "point_source_measurements": [
    {
      "plume_id": "P001",
      "facility_name": "Permian Compressor Station 42",
      "operator": "XYZ Energy",
      "source_location": {"lat": 32.1562, "lon": -103.2338},
      "emission_rate_kg_hr": 2380,
      "uncertainty_pct": 18,
      "source_type": "reciprocating_compressor",
      "likely_cause": "rod_packing_leak",
      "context_image": "s3://ghgsat/2025/015/P001_context.png"
    },
    {
      "plume_id": "P002",
      "facility_name": "Basin Processing Plant",
      "operator": "ABC Midstream",
      "source_location": {"lat": 31.8923, "lon": -102.5672},
      "emission_rate_kg_hr": 5650,
      "uncertainty_pct": 15,
      "source_type": "flare_incomplete_combustion",
      "likely_cause": "flare_efficiency_85pct",
      "context_image": "s3://ghgsat/2025/015/P002_context.png"
    }
  ],
  "total_measured_emissions_kg_hr": 15200,
  "total_measured_emissions_tonnes_yr": 133152,
  "co2_equivalent_tonnes_yr": 3728256
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | CATF submits methane survey request |
| T+0:10 | Phase 1 auction broadcast |
| T+0:25 | Phase 1 bidding closes; MethaneSAT wins |
| T+1:15 | MethaneSAT acquisition begins |
| T+1:25 | MethaneSAT acquisition complete |
| T+1:45 | Phase 1 results delivered; 7 plumes detected |
| T+1:50 | Phase 2 auction broadcast with targets |
| T+2:05 | Phase 2 bidding closes; GHGSat wins |
| T+3:05 | GHGSat acquisition begins |
| T+3:25 | GHGSat acquisition complete |
| T+4:00 | Final quantified emissions report delivered |

**Total latency: 4 hours** (vs. days for sequential operator coordination)

## Acceptance Criteria

- [ ] Phase 1 survey detects plumes > 100 kg/hr
- [ ] Phase 2 quantifies emissions within +/-25% uncertainty
- [ ] Auction converges within 15 minutes per phase
- [ ] Attribution identifies specific emission sources
- [ ] Data delivered within 4 hours of initial request

## Technical Notes

### MethaneSAT Specifications
- **Orbit**: 525 km, sun-synchronous
- **Spectrometer**: SWIR (1630-1680 nm)
- **Spatial resolution**: 400 m x 100 m (along x across track)
- **Swath width**: 200 km
- **Precision**: 3 ppb CH4
- **Detection limit**: ~100 kg/hr

### GHGSat Specifications
- **Orbit**: 500 km, sun-synchronous
- **Instrument**: Wide-Angle Fabry-Perot (WAF-P)
- **Spatial resolution**: 25 m
- **Swath width**: 12 km
- **Detection limit**: ~20 kg/hr
- **Quantification accuracy**: 10-20%

### Methane Global Warming Potential
- **GWP-20**: 84x CO2 (20-year horizon)
- **GWP-100**: 28x CO2 (100-year horizon)
- **Super-emitter threshold**: >100 kg/hr (~876 tonnes/year)

## Value Proposition

Two-phase auction combines wide-area screening (MethaneSAT) with high-resolution quantification (GHGSat), automatically selecting optimal sensors for each task. Super-emitters are identified and quantified in hours rather than weeks of manual coordination.
