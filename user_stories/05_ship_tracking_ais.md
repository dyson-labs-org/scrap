# User Story 05: Maritime Domain Awareness via AIS Constellation Relay

## Summary

A maritime security agency needs real-time ship tracking in a remote ocean region where surface vessels have disabled their AIS transponders (dark shipping). Multiple AIS-equipped satellites collaborate to provide continuous coverage, with data relayed through Starlink to reduce latency.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | European Maritime Safety Agency (EMSA) | - |
| **AIS Satellite 1** | NORSAT-1 | 42826 |
| **AIS Satellite 2** | NORSAT-2 | 42828 |
| **AIS Satellite 3** | RCM-1 (RADARSAT Constellation) | 44322 |
| **SAR Confirmation** | Sentinel-1C | 62261 |
| **Relay Network** | Starlink constellation | Various |
| **Ground Station** | Svalbard Satellite Station (SvalSat) | - |

## Scenario

### Context

EMSA has intelligence suggesting illegal fishing vessels operating in the Barents Sea are disabling AIS transponders to avoid detection. They need:

1. **AIS sweep**: Detect any vessels still transmitting
2. **SAR confirmation**: Image the area to find dark targets
3. **Correlation**: Match SAR detections to AIS transmitters

### Distributed AIS Collection

```
                         +-------------------------------------+
                         |       Barents Sea AOI              |
                         |    (68-75degN, 15-45degE)              |
                         +---------------+---------------------+
                                         |
              +--------------------------+--------------------------+
              |                          |                          |
              v                          v                          v
       +-------------+            +-------------+            +-------------+
       |  NORSAT-1   |            |  NORSAT-2   |            |   RCM-1     |
       |    AIS      |            |    AIS      |            |  AIS + SAR  |
       | (42826)     |            | (42828)     |            |  (44322)    |
       +------+------+            +------+------+            +------+------+
              |                          |                          |
              |    +---------------------+---------------------+    |
              |    |           Starlink Mesh Relay            |    |
              |    |         (laser ISL backbone)             |    |
              +---->                                          <----+
                   +-------------------+-----------------------+
                                       |
                   +-------------------+-------------------+
                   |                                       |
                   v                                       v
          +-----------------+                    +-----------------+
          | Orbital Fusion  |                    |  SvalSat GS     |
          | Processing Node |                    |  (Backup path)  |
          +--------+--------+                    +-----------------+
                   |
            Fused AIS picture
                   |
                   v
          +-----------------+     +-----------------+
          |   EMSA MDA      |---->|  Sentinel-1C    |
          |   Operations    |     |  SAR tasking    |
          +-----------------+     +-----------------+
```

### Coordinated Collection Task

The auction coordinator assigns AIS collection slots:

```json
{
  "task_id": "MDA-BARENTS-2025-015",
  "task_type": "coordinated_ais_collection",
  "aoi": {
    "type": "Polygon",
    "coordinates": [[
      [15, 68], [45, 68],
      [45, 75], [15, 75],
      [15, 68]
    ]]
  },
  "collection_window": {
    "start": "2025-01-15T06:00:00Z",
    "end": "2025-01-15T12:00:00Z"
  },
  "participants": [
    {
      "satellite": "NORSAT-1",
      "norad_id": 42826,
      "role": "primary_ais",
      "time_slots": [
        {"start": "2025-01-15T06:15:00Z", "duration_min": 12},
        {"start": "2025-01-15T08:45:00Z", "duration_min": 11}
      ]
    },
    {
      "satellite": "NORSAT-2",
      "norad_id": 42828,
      "role": "secondary_ais",
      "time_slots": [
        {"start": "2025-01-15T07:30:00Z", "duration_min": 10},
        {"start": "2025-01-15T10:00:00Z", "duration_min": 12}
      ]
    },
    {
      "satellite": "RCM-1",
      "norad_id": 44322,
      "role": "ais_plus_sar",
      "time_slots": [
        {"start": "2025-01-15T09:20:00Z", "duration_min": 8}
      ],
      "sar_mode": "ship_detection"
    }
  ],
  "data_fusion": {
    "method": "orbital_processing",
    "node": "STARLINK-FUSION-42",
    "correlation_radius_nm": 5
  }
}
```

### AIS Collection Parameters

```json
{
  "command_type": "cmd:ais:collection",
  "parameters": {
    "ais_channels": {
      "ch_a": 161.975,
      "ch_b": 162.025
    },
    "message_types": [1, 2, 3, 5, 18, 19, 24],
    "filtering": {
      "mmsi_whitelist": null,
      "sog_min_knots": 0.5,
      "geographic_filter": true
    },
    "output_format": "NMEA_0183",
    "aggregation_interval_sec": 60
  }
}
```

### SAR Ship Detection Command (RCM-1)

```json
{
  "command_type": "cmd:sar:ship_detection",
  "parameters": {
    "sar_mode": "ScanSAR_Wide",
    "polarization": "HH",
    "resolution_m": 50,
    "swath_km": 500,
    "incidence_angle_deg": 35,
    "ship_detection": {
      "algorithm": "CFAR",
      "threshold_sigma": 10,
      "min_ship_length_m": 15
    },
    "output": {
      "raw_sar": false,
      "ship_detections": true,
      "format": "GeoJSON"
    }
  }
}
```

### Data Fusion at Orbital Node

The Starlink fusion node correlates AIS and SAR:

```json
{
  "fusion_output": {
    "task_id": "MDA-BARENTS-2025-015",
    "collection_time": "2025-01-15T06:00:00Z/2025-01-15T12:00:00Z",
    "aoi_coverage_pct": 94.2,
    "vessels_detected": {
      "ais_only": 127,
      "sar_only": 23,
      "ais_sar_matched": 98,
      "total_unique": 248
    },
    "dark_targets": [
      {
        "sar_id": "SAR-DET-0042",
        "position": {"lat": 71.234, "lon": 28.567},
        "detection_time": "2025-01-15T09:22:15Z",
        "estimated_length_m": 85,
        "estimated_heading_deg": 045,
        "estimated_speed_knots": 8.5,
        "confidence": 0.92,
        "nearest_ais": {
          "mmsi": null,
          "distance_nm": 12.3,
          "correlation": "NO_MATCH"
        }
      },
      {
        "sar_id": "SAR-DET-0043",
        "position": {"lat": 72.891, "lon": 32.456},
        "detection_time": "2025-01-15T09:22:45Z",
        "estimated_length_m": 120,
        "estimated_heading_deg": 270,
        "estimated_speed_knots": 12.1,
        "confidence": 0.88,
        "nearest_ais": {
          "mmsi": null,
          "distance_nm": 8.7,
          "correlation": "NO_MATCH"
        }
      }
    ],
    "ais_contacts": [
      {
        "mmsi": "257123456",
        "name": "NORDIC EXPLORER",
        "type": "Fishing",
        "flag": "NO",
        "positions": [
          {"time": "2025-01-15T06:18:00Z", "lat": 69.123, "lon": 18.456, "sog": 5.2, "cog": 090}
        ]
      }
    ]
  }
}
```

### Follow-Up SAR Tasking

Based on dark target detections, EMSA tasks Sentinel-1C for high-resolution imaging:

```json
{
  "timestamp": "2025-01-15T12:30:00Z",
  "command_type": "cmd:imaging:sar:stripmap",
  "parameters": {
    "target_coords": {"lat": 71.234, "lon": 28.567},
    "imaging_mode": "Strip Map",
    "polarization": "VV+VH",
    "resolution_m": 5,
    "priority": "HIGH",
    "objective": "dark_target_identification"
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | EMSA submits MDA collection request |
| T+0:15 | NORSAT-1 first pass begins |
| T+0:27 | NORSAT-1 data relayed via Starlink |
| T+1:30 | NORSAT-2 pass begins |
| T+3:20 | RCM-1 combined AIS+SAR pass |
| T+3:30 | All data at fusion node |
| T+3:45 | Fusion processing complete |
| T+3:50 | Dark targets identified; Sentinel-1C tasked |
| T+5:15 | Sentinel-1C high-res acquisition |
| T+6:00 | Final MDA picture delivered to EMSA |

## Acceptance Criteria

- [ ] >=90% AOI coverage achieved
- [ ] AIS data latency < 15 minutes from collection
- [ ] SAR ship detections correlated within 5nm radius
- [ ] Dark targets flagged within 4 hours
- [ ] Follow-up SAR imagery acquired same day

## Technical Notes

### NORSAT AIS Specifications
- **Orbit**: 600 km, polar sun-synchronous
- **AIS receiver**: ASR 300
- **Detection range**: 2000+ km swath
- **Message types**: 1-5, 18-19, 24-27
- **Sensitivity**: -116 dBm

### RCM-1 Specifications
- **Orbit**: 593 km, polar sun-synchronous
- **SAR modes**: Spotlight (1m), Strip (5m), ScanSAR (50m)
- **AIS receiver**: Integrated
- **Swath width**: Up to 500km (ScanSAR Wide)

### AIS Message Types
| Type | Content |
|------|---------|
| 1,2,3 | Position report (Class A) |
| 5 | Static/voyage data |
| 18 | Position report (Class B) |
| 19 | Extended position report |
| 24 | Class B static data |

## Value Proposition

Coordinated multi-satellite AIS collection with orbital fusion provides near-continuous maritime domain awareness. Dark shipping detection is reduced from days to hours, enabling timely law enforcement response.
