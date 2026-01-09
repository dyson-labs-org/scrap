# User Story 11: Multi-Constellation Disaster Response via Distributed Auction

> **Note**: This user story illustrates a potential SCRAP application. The distributed auction mechanism (CBBA) shown is **illustrative** and not part of the core SCRAP specification. Initial deployments use pre-negotiated capability tokens. See [AUCTION.md](../future/AUCTION.md) for auction mechanism details.

## Summary

A major tsunami triggers simultaneous tasking requests across multiple satellite constellations. A distributed CBBA auction coordinates SAR, optical, and communications satellites from different operators to maximize coverage and minimize response time.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | UN-SPIDER / International Charter | - |
| **Auction Coordinators** | Starlink mesh (distributed) | Various |
| **SAR Provider 1** | Sentinel-1C | 62261 |
| **SAR Provider 2** | ICEYE X14 | 51070 |
| **Optical Provider 1** | Pleiades Neo 4 | 50258 |
| **Optical Provider 2** | WorldView-3 | 40115 |
| **Comms Relay** | Starlink constellation | Various |
| **Processing** | AWS Ground Station + Cloud | - |

## Scenario

### Context

A magnitude 8.9 earthquake off the coast of Japan generates a major tsunami. The International Charter on Space and Major Disasters is activated, requiring:

1. **SAR imaging** for flood extent mapping (works through clouds)
2. **Optical imaging** for damage assessment (higher resolution)
3. **Communications relay** for first responder coordination
4. **Rapid data delivery** to disaster response agencies

### Multi-Constellation Auction Architecture

```
+-------------------------------------------------------------------------+
|                     DISASTER: Tsunami Impact Zone                        |
|                     AOI: 35-42degN, 139-145degE                             |
|                     Area: ~150,000 km^2                                  |
+----------------------------------+--------------------------------------+
                                   |
                    International Charter Activation
                                   |
                                   v
+-------------------------------------------------------------------------+
|                    Distributed Auction Coordinators                      |
|              (Starlink mesh - regional nodes)                           |
+-----------+--------------+--------------+--------------+----------------+
            |              |              |              |
     +------v------+ +-----v------+ +-----v------+ +-----v------+
     |  SAR Task   | | Optical    | | Comms Task | | Processing |
     |  Auction    | | Task Auct  | | Auction    | | Task Auct  |
     +------+------+ +-----+------+ +-----+------+ +-----+------+
            |              |              |              |
    +-------+-------+      |      +-------+-------+      |
    |               |      |      |               |      |
    v               v      v      v               v      v
+--------+    +--------+ +--------+ +--------+ +--------+ +--------+
|Sent-1C |    |ICEYE   | |Pleiades| |World   | |Starlink| |AWS     |
|SAR     |    |X14 SAR | |Neo 4   | |View-3  | |Mesh    | |Cloud   |
|(bid:12)|    |(bid:8) | |(bid:15)| |(bid:11)| |(bid:6) | |(bid:9) |
|        |    |WINNER  | |        | |WINNER  | |WINNER  | |WINNER  |
+--------+    +--------+ +--------+ +--------+ +--------+ +--------+
```

### Charter Activation Task

```json
{
  "activation_id": "CHARTER-2025-JAP-TSUNAMI",
  "activation_time": "2025-01-15T06:15:00Z",
  "disaster_type": "tsunami",
  "trigger_event": {
    "type": "earthquake",
    "magnitude": 8.9,
    "location": {"lat": 38.5, "lon": 142.8},
    "depth_km": 25,
    "time": "2025-01-15T06:00:00Z"
  },
  "impact_area": {
    "type": "Polygon",
    "coordinates": [[
      [139, 35], [145, 35],
      [145, 42], [139, 42],
      [139, 35]
    ]]
  },
  "priority_zones": [
    {"name": "Sendai Coast", "priority": 1, "population": 1500000},
    {"name": "Fukushima Coast", "priority": 1, "population": 800000},
    {"name": "Iwate Coast", "priority": 2, "population": 400000}
  ],
  "requirements": {
    "sar_coverage_km2": 50000,
    "optical_coverage_km2": 10000,
    "revisit_hours": 12,
    "data_latency_hours": 4
  }
}
```

### SAR Task Auction

```json
{
  "auction_id": "CHARTER-2025-JAP-SAR-001",
  "task_type": "disaster_sar_coverage",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[
      [140, 36], [143, 36],
      [143, 40], [140, 40],
      [140, 36]
    ]]
  },
  "requirements": {
    "imaging_mode": "wide_swath",
    "resolution_m_max": 20,
    "polarization": ["VV", "VH"],
    "coverage_km2_min": 25000,
    "incidence_angle_range_deg": [20, 45]
  },
  "time_constraint": {
    "earliest": "2025-01-15T07:00:00Z",
    "latest": "2025-01-15T12:00:00Z"
  }
}
```

**SAR Bids:**

```json
{
  "sentinel_1c_bid": {
    "bidder": "SENTINEL-1C",
    "bid_value": 12.5,
    "earliest_acquisition": "2025-01-15T09:45:00Z",
    "coverage_km2": 62500,
    "imaging_mode": "Interferometric Wide Swath",
    "resolution_m": 5,
    "swath_km": 250,
    "data_latency_hours": 3
  },
  "iceye_x14_bid": {
    "bidder": "ICEYE-X14",
    "bid_value": 8.2,
    "earliest_acquisition": "2025-01-15T07:30:00Z",
    "coverage_km2": 30000,
    "imaging_mode": "Wide Swath",
    "resolution_m": 15,
    "swath_km": 100,
    "data_latency_hours": 1.5
  }
}
```

**Winner: ICEYE X14** (earlier acquisition, faster delivery)

### Optical Task Auction

```json
{
  "auction_id": "CHARTER-2025-JAP-OPT-001",
  "task_type": "damage_assessment_optical",
  "priority_targets": [
    {"name": "Sendai Port", "coords": [38.26, 141.02]},
    {"name": "Sendai Airport", "coords": [38.14, 140.92]},
    {"name": "Fukushima Daiichi", "coords": [37.42, 141.03]}
  ],
  "requirements": {
    "resolution_m_max": 0.5,
    "cloud_cover_max_pct": 40,
    "sun_elevation_min_deg": 25
  }
}
```

**Optical Bids:**

```json
{
  "pleiades_neo_4_bid": {
    "bidder": "PLEIADES-NEO-4",
    "bid_value": 15.3,
    "earliest_acquisition": "2025-01-15T10:20:00Z",
    "resolution_m": 0.30,
    "coverage_targets": 3,
    "cloud_forecast_pct": 35
  },
  "worldview_3_bid": {
    "bidder": "WORLDVIEW-3",
    "bid_value": 11.8,
    "earliest_acquisition": "2025-01-15T09:15:00Z",
    "resolution_m": 0.31,
    "coverage_targets": 3,
    "cloud_forecast_pct": 25
  }
}
```

**Winner: WorldView-3** (earlier pass, better cloud conditions)

### Coordinated Collection Plan

```json
{
  "collection_plan": {
    "activation_id": "CHARTER-2025-JAP-TSUNAMI",
    "timeline": [
      {
        "time": "2025-01-15T07:30:00Z",
        "satellite": "ICEYE-X14",
        "task": "SAR wide swath",
        "coverage_km2": 30000,
        "product": "flood_extent_map"
      },
      {
        "time": "2025-01-15T08:00:00Z",
        "satellite": "Starlink mesh",
        "task": "Emergency comms relay",
        "coverage": "Sendai region",
        "product": "first_responder_connectivity"
      },
      {
        "time": "2025-01-15T09:00:00Z",
        "satellite": "ICEYE-X14",
        "task": "Data downlink via Starlink",
        "destination": "AWS Ground Station Oregon"
      },
      {
        "time": "2025-01-15T09:15:00Z",
        "satellite": "WorldView-3",
        "task": "High-res optical - Sendai",
        "coverage_km2": 500,
        "product": "damage_assessment"
      },
      {
        "time": "2025-01-15T09:45:00Z",
        "satellite": "Sentinel-1C",
        "task": "SAR IW mode",
        "coverage_km2": 62500,
        "product": "insar_ready_data"
      },
      {
        "time": "2025-01-15T10:30:00Z",
        "satellite": "AWS Cloud",
        "task": "Flood detection processing",
        "input": "ICEYE SAR",
        "product": "flood_mask_geojson"
      }
    ]
  }
}
```

### Flood Detection Products

```json
{
  "flood_detection_output": {
    "product_id": "CHARTER-2025-JAP-FLOOD-001",
    "source_satellite": "ICEYE-X14",
    "acquisition_time": "2025-01-15T07:35:00Z",
    "processing_time": "2025-01-15T10:30:00Z",
    "coverage_km2": 28500,
    "flood_statistics": {
      "total_flooded_km2": 1250,
      "urban_flooded_km2": 85,
      "agricultural_flooded_km2": 620,
      "coastal_inundation_km2": 545
    },
    "flood_extent": {
      "type": "MultiPolygon",
      "coordinates": "...",
      "crs": "EPSG:4326"
    },
    "affected_infrastructure": {
      "roads_flooded_km": 340,
      "buildings_flooded": 45000,
      "hospitals_affected": 12,
      "schools_affected": 89
    },
    "products": {
      "flood_mask": "s3://charter/JAP-2025/flood_mask.tif",
      "flood_vector": "s3://charter/JAP-2025/flood_extent.geojson",
      "water_depth_estimate": "s3://charter/JAP-2025/water_depth.tif"
    }
  }
}
```

### Damage Assessment Products

```json
{
  "damage_assessment_output": {
    "product_id": "CHARTER-2025-JAP-DAMAGE-001",
    "source_satellite": "WorldView-3",
    "acquisition_time": "2025-01-15T09:18:00Z",
    "processing_time": "2025-01-15T11:45:00Z",
    "targets_assessed": 3,
    "damage_by_target": {
      "sendai_port": {
        "buildings_analyzed": 450,
        "destroyed": 45,
        "major_damage": 120,
        "moderate_damage": 85,
        "minor_damage": 65,
        "no_damage": 135,
        "port_operational_pct": 35
      },
      "sendai_airport": {
        "runway_status": "flooded",
        "terminal_status": "major_damage",
        "operational": false
      },
      "fukushima_daiichi": {
        "perimeter_intact": true,
        "cooling_ponds_status": "monitoring_required",
        "access_roads": "partially_blocked"
      }
    }
  }
}
```

### Communications Relay Status

```json
{
  "comms_relay_status": {
    "activation_id": "CHARTER-2025-JAP-COMMS",
    "network": "Starlink",
    "coverage_area_km2": 45000,
    "terminals_deployed": 150,
    "active_sessions": 89,
    "bandwidth_allocated_gbps": 12,
    "services": {
      "voice_circuits": 500,
      "video_conferencing": 50,
      "data_backhaul_mbps": 2400
    },
    "agencies_connected": [
      "Japan Coast Guard",
      "JSDF",
      "Miyagi Prefecture EOC",
      "UN OCHA"
    ]
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | Earthquake M8.9 (06:00 UTC) |
| T+0:15 | International Charter activated |
| T+0:20 | Distributed auction initiated |
| T+0:30 | Auction converged; tasks assigned |
| T+1:30 | ICEYE X14 SAR acquisition |
| T+2:00 | Starlink emergency comms active |
| T+3:00 | ICEYE data at AWS via Starlink |
| T+3:15 | WorldView-3 optical acquisition |
| T+3:45 | Sentinel-1C SAR acquisition |
| T+4:30 | Flood detection products ready |
| T+5:45 | Damage assessment products ready |
| T+6:00 | Full situational awareness delivered |

**Charter products delivered: 6 hours post-event**

## Acceptance Criteria

- [ ] Auction converges within 30 minutes
- [ ] First SAR imagery acquired within 2 hours
- [ ] Flood extent map delivered within 4 hours
- [ ] High-res damage assessment within 6 hours
- [ ] Emergency comms operational within 2 hours
- [ ] All Charter-required products delivered within 24 hours

## Technical Notes

### International Charter Requirements
- **Activation response**: < 24 hours for first products
- **Coverage**: Priority impact zones
- **Data sharing**: Open access for disaster response
- **Coordination**: UN-SPIDER acts as authorized user

### CBBA Auction Convergence
- **Participants**: Up to 50 satellites
- **Communication rounds**: 3-5 for convergence
- **Decision time**: < 30 minutes
- **Conflict resolution**: Bid value comparison

### Multi-Sensor Fusion Benefits
- SAR: All-weather flood mapping
- Optical: Detailed damage assessment
- Combined: Comprehensive situational awareness

## Value Proposition

Distributed auction across multiple constellations enables optimal resource allocation during disasters. Instead of sequential operator coordination (taking 12+ hours), the auction converges in 30 minutes and delivers comprehensive products in 6 hours, potentially saving thousands of lives through faster response coordination.
