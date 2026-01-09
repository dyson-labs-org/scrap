# User Story 02: Wildfire Monitoring with Hyperspectral Imaging via Auction

> **Note**: This user story illustrates a potential SCRAP application. The distributed auction mechanism (CBBA) shown is **illustrative** and not part of the core SCRAP specification. Initial deployments use pre-negotiated capability tokens. See [AUCTION.md](../future/AUCTION.md) for auction mechanism details.

## Summary

A wildfire management agency needs hyperspectral imagery to identify active fire fronts, fuel types, and post-burn severity. Multiple hyperspectral satellites bid on the task through a distributed auction protocol, with the winner delivering data via ground station.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | California Department of Forestry (CAL FIRE) | - |
| **Auction Coordinator** | Starlink-8192 (local coordinator) | Various |
| **Bidder 1** | PRISMA | 44072 |
| **Bidder 2** | EnMAP | 52159 |
| **Bidder 3** | INTUITION-1 | 58565 |
| **Winner** | EnMAP | 52159 |
| **Instrument** | HSI (Hyperspectral Imager) | - |
| **Ground Station** | DLR Neustrelitz, Germany | - |

## Scenario

### Context

A major wildfire complex is burning in the Sierra Nevada mountains. CAL FIRE needs hyperspectral data to:
- Map active fire perimeters (thermal bands)
- Classify vegetation/fuel types (SWIR bands)
- Assess burn severity for suppression priority (vegetation indices)

Multiple hyperspectral satellites have capability; an auction determines the optimal assignment.

### Auction Flow

```
+--------------+     +-------------+
|   CAL FIRE   |---->| AWS Ground  |
|   Dispatch   |     |   Station   |
+--------------+     +------+------+
                            |
                    Upload task to
                    orbiting coordinator
                            |
                            v
              +-------------------------+
              |    Starlink-8192        |
              |  (Auction Coordinator)  |
              +-----------+-------------+
                          |
            +-------------+-------------+
            |             |             |
            v             v             v
      +----------+  +----------+  +----------+
      |  PRISMA  |  |  EnMAP   |  |INTUITION |
      |  (bid 12)|  |  (bid 8) |  |  (bid 15)|
      +----------+  +----+-----+  +----------+
                         |
                    Winner: EnMAP
                         |
                         v
              +-------------------------+
              |   DLR Neustrelitz GS    |
              |   --> CAL FIRE          |
              +-------------------------+
```

### Task Broadcast

The auction coordinator broadcasts the task requirements:

```json
{
  "task_id": "FIRE-2025-01-15-0042",
  "task_type": "hyperspectral_imaging",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[
      [-120.5, 38.2], [-119.8, 38.2],
      [-119.8, 38.9], [-120.5, 38.9],
      [-120.5, 38.2]
    ]]
  },
  "requirements": {
    "spectral_range_nm": [400, 2500],
    "spectral_bands_min": 200,
    "spatial_resolution_m_max": 30,
    "swath_width_km_min": 30,
    "required_bands": ["VNIR", "SWIR"],
    "cloud_cover_max_pct": 20
  },
  "time_window": {
    "earliest": "2025-01-15T18:00:00Z",
    "latest": "2025-01-15T22:00:00Z"
  },
  "priority": "HIGH",
  "authorization": {
    "required_capabilities": ["task:bid:hyperspectral", "task:execute:imaging"],
    "payment_escrow": "0x7a3f2c1e..."
  }
}
```

### Bid Responses

**PRISMA Bid:**
```json
{
  "task_id": "FIRE-2025-01-15-0042",
  "bidder_id": "PRISMA-44072",
  "bid_value": 12.3,
  "timestamp": "2025-01-15T17:30:00Z",
  "capability_token": "<PRISMA_CAP_TOKEN>",
  "cost_breakdown": {
    "fuel_kg": 0.015,
    "time_sec": 180,
    "opportunity_cost": 4.2,
    "capability_match": 0.85
  },
  "earliest_execution": "2025-01-15T19:45:00Z",
  "instrument_specs": {
    "name": "HYC",
    "spectral_range_nm": [400, 2505],
    "spectral_bands": 237,
    "spatial_resolution_m": 30,
    "swath_width_km": 30
  }
}
```

**EnMAP Bid (Winner):**
```json
{
  "task_id": "FIRE-2025-01-15-0042",
  "bidder_id": "ENMAP-52159",
  "bid_value": 8.1,
  "timestamp": "2025-01-15T17:30:15Z",
  "capability_token": "<ENMAP_CAP_TOKEN>",
  "cost_breakdown": {
    "fuel_kg": 0.008,
    "time_sec": 120,
    "opportunity_cost": 2.1,
    "capability_match": 0.95
  },
  "earliest_execution": "2025-01-15T18:30:00Z",
  "instrument_specs": {
    "name": "HSI",
    "spectral_range_nm": [420, 2450],
    "spectral_bands": 228,
    "spatial_resolution_m": 30,
    "swath_width_km": 30,
    "radiometric_resolution_bits": 14
  }
}
```

**INTUITION-1 Bid:**
```json
{
  "task_id": "FIRE-2025-01-15-0042",
  "bidder_id": "INTUITION-58565",
  "bid_value": 15.7,
  "timestamp": "2025-01-15T17:30:22Z",
  "capability_token": "<INTUITION_CAP_TOKEN>",
  "cost_breakdown": {
    "fuel_kg": 0.022,
    "time_sec": 300,
    "opportunity_cost": 6.8,
    "capability_match": 0.78
  },
  "earliest_execution": "2025-01-15T21:15:00Z",
  "instrument_specs": {
    "name": "HSI (Intuition-1)",
    "spectral_range_nm": [400, 1000],
    "spectral_bands": 192,
    "spatial_resolution_m": 25,
    "swath_width_km": 20
  }
}
```

### Winner Selection

EnMAP wins with the lowest bid (8.1) due to:
- **Better orbital position**: Earlier access window
- **Lower fuel cost**: Already aligned for imaging
- **Higher capability match**: Full SWIR coverage for fire mapping

### Execution Command

```json
{
  "timestamp": "2025-01-15T17:35:00Z",
  "command_type": "cmd:imaging:hyperspectral",
  "parameters": {
    "task_id": "FIRE-2025-01-15-0042",
    "target_polygon": {
      "type": "Polygon",
      "coordinates": [[[-120.5, 38.2], ...]]
    },
    "acquisition_time": "2025-01-15T18:30:00Z",
    "spectral_config": {
      "vnir_enabled": true,
      "swir_enabled": true,
      "spectral_binning": 1
    },
    "radiometric_mode": "high_dynamic_range",
    "data_routing": {
      "method": "ground_station",
      "station": "DLR-NEUSTRELITZ",
      "downlink_band": "X-band"
    }
  }
}
```

### Data Products

| Product | Description | Size |
|---------|-------------|------|
| L1B Radiance | Calibrated spectral radiance cube | 4.2 GB |
| L2A Reflectance | Atmospherically corrected | 4.2 GB |
| Fire Mask | Active fire pixels (SWIR thermal) | 12 MB |
| Burn Severity | dNBR classification | 45 MB |
| Fuel Type Map | Vegetation classification | 120 MB |

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | CAL FIRE submits tasking request |
| T+0:05 | Task broadcast to constellation |
| T+0:30 | Bidding window closes |
| T+0:32 | EnMAP selected as winner |
| T+1:00 | EnMAP begins imaging pass |
| T+1:08 | Acquisition complete |
| T+2:45 | Next DLR ground station pass |
| T+3:00 | Data downlink complete |
| T+3:30 | L1B/L2A products generated |
| T+4:00 | Fire products delivered to CAL FIRE |

## Acceptance Criteria

- [ ] At least 2 satellites submit valid bids
- [ ] Auction converges within 5 minutes
- [ ] Winner executes imaging within time window
- [ ] Hyperspectral data meets spectral/spatial requirements
- [ ] Fire detection products delivered within 4 hours

## Technical Notes

### EnMAP Specifications
- **Orbit**: 653 km, sun-synchronous, 97.96deg inclination
- **HSI spectral range**: 420-2450 nm
- **Spectral bands**: 228 (VNIR: 88, SWIR: 140)
- **Spatial resolution**: 30 m
- **Swath width**: 30 km
- **Revisit time**: 4 days (27 days for global coverage)

### Fire Detection Algorithm
- **Active fire**: SWIR bands (1600-2500nm) detect thermal anomalies
- **Burn severity**: Normalized Burn Ratio $NBR = \frac{NIR - SWIR}{NIR + SWIR}$
- **Fuel classification**: Spectral unmixing for vegetation types

## Value Proposition

The auction mechanism automatically selects the best-positioned satellite with appropriate sensors, eliminating manual coordination between multiple operators. CAL FIRE receives optimal data 2 hours faster than sequential operator queries would allow.
