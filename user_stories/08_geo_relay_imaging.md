# User Story 08: GEO Relay for Rapid LEO Imaging Response

## Summary

An emergency response agency needs rapid delivery of high-resolution imagery from a LEO satellite that won't have a ground station pass for 45 minutes. The imagery is relayed through EDRS-C (GEO) via optical ISL, providing near-real-time data delivery.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | UN Office for the Coordination of Humanitarian Affairs (OCHA) | - |
| **Tasking Source** | ESA Coordinated Emergency Response | - |
| **Target Satellite** | Pleiades Neo 3 | 48904 |
| **Instrument** | Panchromatic + Multispectral Imager | - |
| **GEO Relay** | EDRS-C | 44475 |
| **Ground Station** | DLR Weilheim, Germany | - |

## Scenario

### Context

A 7.2 magnitude earthquake has struck northern Pakistan. OCHA needs pre/post imagery to assess infrastructure damage within 2 hours for emergency resource allocation. Pleiades Neo 3 will overfly the area in 20 minutes but won't have a ground station contact for 45 minutes after acquisition.

EDRS-C provides near-real-time relay capability via 1.8 Gbps laser ISL.

### Relay Architecture

```
+------------------+     +---------------------------------------------+
|      OCHA        |     |                                             |
|  Geneva HQ       |     |           +---------------------+           |
+--------+---------+     |           |    Pleiades Neo 3   |           |
         |               |           |    30cm resolution  |           |
    Emergency            |           |    (NORAD 48904)    |           |
    Request              |           +----------+----------+           |
         |               |                      |                      |
         v               |                  705 km                     |
+-----------------+      |               Laser ISL                     |
|  ESA Emergency  |      |                1.8 Gbps                     |
|  Response       |      |                      |                      |
+--------+--------+      |                      v                      |
         |               |           +---------------------+           |
    Tasking              |           |      EDRS-C         |           |
    Command              |           |   GEO Relay (31degE)  |           |
         |               |           |   (NORAD 44475)     |           |
         v               |           +----------+----------+           |
+-----------------+      |                      |                      |
|  DLR Weilheim   |      |               35,786 km                     |
|  Ground Station |<-----+----------------------+                      |
+--------+--------+      |              Ka-band                        |
         |               |              Downlink                       |
    Imagery              |                                             |
    Products             |                                             |
         |               +---------------------------------------------+
         v
+-----------------+
|      OCHA       |
|  Damage Map     |
+-----------------+
```

### Tasking Command (via ground station to Pleiades Neo)

```json
{
  "timestamp": "2025-01-15T08:15:00Z",
  "command_type": "cmd:imaging:optical:emergency",
  "parameters": {
    "task_id": "EMERG-PAK-EQ-2025-001",
    "target_coords": {
      "type": "Polygon",
      "coordinates": [[
        [73.0, 34.0], [73.5, 34.0],
        [73.5, 34.5], [73.0, 34.5],
        [73.0, 34.0]
      ]]
    },
    "collection_mode": {
      "panchromatic": {
        "enabled": true,
        "resolution_m": 0.30
      },
      "multispectral": {
        "enabled": true,
        "resolution_m": 1.2,
        "bands": ["Blue", "Green", "Red", "NIR"]
      }
    },
    "acquisition_params": {
      "off_nadir_angle_deg": 15,
      "sun_elevation_min_deg": 25,
      "cloud_cover_max_pct": 30
    },
    "priority": "CHARTER_ACTIVATION",
    "data_routing": {
      "method": "edrs_optical_relay",
      "relay_satellite": "EDRS-C",
      "laser_terminal": "LCT-135",
      "ground_station": "DLR-WEILHEIM",
      "max_relay_latency_sec": 120
    }
  }
}
```

### EDRS Relay Sequence

```
T+0:00   Earthquake occurs (2025-01-15T07:45:00Z)
T+0:30   OCHA activates International Charter
T+0:35   ESA coordinates Pleiades Neo tasking
T+0:55   Tasking command uploaded to Pleiades Neo 3

T+1:10   Pleiades Neo 3 begins imaging pass
T+1:18   50km x 50km strip acquired (2500 km^2)
T+1:20   On-board compression (JPEG2000 lossless)
T+1:22   Laser terminal acquisition initiated
T+1:23   Bidirectional laser link established with EDRS-C
         +-- Distance: 38,500 km
         +-- Link budget: +3 dB margin
         +-- Data rate: 1.8 Gbps

T+1:25   Image data transfer begins
         +-- Raw data: 12 GB
         +-- Transfer time: 54 seconds

T+1:26   EDRS-C stores data, begins Ka-band downlink
         +-- Ka-band rate: 600 Mbps
         +-- Ground station: Weilheim
         +-- Downlink time: 160 seconds

T+1:30   Data received at ground station
T+1:35   Orthorectification and georeferencing
T+1:45   Damage assessment products generated
T+1:50   Imagery delivered to OCHA

Total latency: 32 minutes from acquisition to delivery
(vs. 95 minutes via traditional ground station pass)
```

### Laser Inter-Satellite Link Parameters

```json
{
  "isl_parameters": {
    "wavelength_nm": 1064,
    "data_rate_gbps": 1.8,
    "link_distance_km": 38500,
    "beam_divergence_urad": 10,
    "transmit_power_w": 1.0,
    "receiver_aperture_cm": 13.5,
    "acquisition_time_sec": 45,
    "tracking_accuracy_urad": 0.5,
    "bit_error_rate": 1e-9,
    "encryption": "AES-256-GCM"
  }
}
```

### Image Products

| Product | Resolution | Size | Description |
|---------|------------|------|-------------|
| PAN L1B | 0.30 m | 4.2 GB | Panchromatic TOA radiance |
| MS L1B | 1.2 m | 2.1 GB | 4-band multispectral TOA |
| PAN L1C | 0.30 m | 4.2 GB | Orthorectified panchromatic |
| Pansharpened | 0.30 m | 4.5 GB | Fused PAN + MS (4-band) |
| Damage Map | 2.0 m | 85 MB | Building damage classification |
| Change Detection | 2.0 m | 120 MB | Pre/post comparison |

### Damage Assessment Output

```json
{
  "assessment_id": "EMERG-PAK-EQ-2025-001-DAMAGE",
  "acquisition_time": "2025-01-15T08:25:00Z",
  "delivery_time": "2025-01-15T08:57:00Z",
  "latency_minutes": 32,
  "coverage": {
    "area_km2": 2500,
    "cloud_cover_pct": 8,
    "usable_area_pct": 92
  },
  "damage_statistics": {
    "buildings_analyzed": 45230,
    "destroyed": 1823,
    "heavily_damaged": 4156,
    "moderately_damaged": 8234,
    "lightly_damaged": 12045,
    "no_visible_damage": 18972
  },
  "critical_infrastructure": {
    "hospitals": {
      "total": 12,
      "operational": 8,
      "damaged": 3,
      "destroyed": 1
    },
    "roads": {
      "total_km": 485,
      "blocked_km": 23,
      "damaged_km": 67
    },
    "bridges": {
      "total": 34,
      "collapsed": 2,
      "damaged": 8
    }
  },
  "priority_areas": [
    {
      "name": "Sector A - Downtown",
      "coords": {"lat": 34.25, "lon": 73.18},
      "damage_level": "severe",
      "population_estimate": 45000,
      "recommended_action": "immediate_sar"
    }
  ],
  "products": {
    "damage_map_geotiff": "s3://charter/PAK-EQ-2025/damage_map.tif",
    "quicklook_jpg": "s3://charter/PAK-EQ-2025/quicklook.jpg",
    "vector_damage": "s3://charter/PAK-EQ-2025/damage.geojson"
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | Earthquake M7.2 strikes (07:45 UTC) |
| T+0:30 | OCHA activates International Charter |
| T+0:35 | ESA coordinates Pleiades Neo tasking |
| T+0:55 | Command uploaded to satellite |
| T+1:10 | Imaging begins |
| T+1:18 | Acquisition complete |
| T+1:23 | EDRS laser link established |
| T+1:26 | Image transfer complete to EDRS-C |
| T+1:30 | Data received at Weilheim |
| T+1:35 | Processing begins |
| T+1:50 | Products delivered to OCHA |

**Total: 65 minutes from earthquake to actionable intelligence**

## Acceptance Criteria

- [ ] EDRS laser link established within 3 minutes of acquisition
- [ ] Data transfer at >=1.5 Gbps sustained
- [ ] End-to-end latency < 45 minutes
- [ ] Damage classification accuracy >=85%
- [ ] Products in OCHA hands within 2 hours of event

## Technical Notes

### Pleiades Neo Specifications
- **Orbit**: 620 km, sun-synchronous
- **Resolution**: 0.30 m (PAN), 1.2 m (MS)
- **Swath width**: 14 km
- **Agility**: 32deg/s slew rate
- **On-board storage**: 1 Tb
- **EDRS compatibility**: LCT-135 laser terminal

### EDRS-C Specifications
- **Orbit**: GEO, 31degE
- **Laser ISL**: 1.8 Gbps bidirectional
- **Ka-band downlink**: 600 Mbps
- **Coverage**: Europe, Atlantic, Africa
- **Operational since**: 2019

### Laser Link Budget

| Parameter | Value | Notes |
|-----------|-------|-------|
| Transmit power | $+0$ dBW | 1 W |
| Antenna gain | $+108$ dB | |
| Path loss | $-289$ dB | 38,500 km |
| Receive gain | $+106$ dB | |
| Pointing loss | $-2$ dB | |
| System margin | $+3$ dB | |
| Receiver sensitivity | $-31$ dBW | |
| **Link margin** | $+3$ dB | positive |

## Value Proposition

GEO relay reduces imagery delivery time from 95 minutes (next ground pass) to 32 minutes, enabling emergency responders to deploy resources 63 minutes faster. In earthquake response, this time savings directly translates to lives saved during the critical "golden hour."
