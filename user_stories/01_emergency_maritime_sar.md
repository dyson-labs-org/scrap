# User Story 01: Emergency Maritime SAR Imaging via Starlink Relay

## Summary

A maritime distress signal triggers an urgent request for SAR (Synthetic Aperture Radar) imagery of the search area. The task is relayed via Starlink's ISL mesh network to reach a Sentinel-1C satellite that cannot wait for its next ground station pass.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | USCG Maritime Rescue Coordination Center | - |
| **Task Originator** | Iridium 180 (nearest Iridium satellite) | 56730 |
| **Relay Network** | Starlink constellation (9,257 satellites) | Various |
| **Target Satellite** | Sentinel-1C | 62261 |
| **Instrument** | SAR-C (Sentinel-1) | - |
| **Data Relay** | EDRS-C (European Data Relay Satellite) | 44475 |
| **Ground Station** | ESA Redu Ground Station, Belgium | - |

## Scenario

### Context

A cargo vessel transmits a MAYDAY signal in the North Atlantic (52.3°N, 35.7°W). Weather conditions include heavy cloud cover and 40-knot winds, making optical imaging useless. The nearest ground station to Sentinel-1C is 47 minutes away. The Coast Guard needs imagery within 15 minutes.

### Task Flow

```
┌──────────────┐     ┌─────────────┐     ┌─────────────────────────────────┐
│    USCG      │────►│  Iridium    │────►│      Starlink ISL Mesh          │
│   MRCC       │     │    180      │     │   (laser crosslinks, 200 Gbps)  │
└──────────────┘     └─────────────┘     └───────────────┬─────────────────┘
                                                         │
                                                    Close Approach
                                                         │
                                                         ▼
                                         ┌─────────────────────────────┐
                                         │      Sentinel-1C            │
                                         │   SAR-C Imaging Radar       │
                                         │   (NORAD 62261)             │
                                         └───────────────┬─────────────┘
                                                         │
                                                    Laser ISL
                                                         │
                                                         ▼
                                         ┌─────────────────────────────┐
                                         │        EDRS-C               │
                                         │   GEO Data Relay            │
                                         │   (NORAD 44475)             │
                                         └───────────────┬─────────────┘
                                                         │
                                                    Ka-band Downlink
                                                         │
                                                         ▼
                                         ┌─────────────────────────────┐
                                         │   ESA Redu Ground Station   │
                                         │   ──► USCG MRCC             │
                                         └─────────────────────────────┘
```

### Capability Token

The token authorizes Starlink satellites to relay tasking commands to Sentinel-1C for emergency maritime imaging.

```json
{
  "header": {
    "alg": "ES256",
    "typ": "SAT-CAP"
  },
  "payload": {
    "iss": "ESA-EUMETSAT",
    "sub": "STARLINK-RELAY-AUTH",
    "aud": "SENTINEL-1C-62261",
    "iat": 1705312800,
    "exp": 1705316400,
    "jti": "a7f3c2e1-maritime-emergency-001",
    "cap": [
      "cmd:imaging:sar:stripmap",
      "cmd:imaging:sar:iw",
      "cmd:attitude:point",
      "cmd:downlink:edrs"
    ],
    "cns": {
      "max_range_km": 50,
      "emergency_priority": true,
      "aoi_type": "maritime",
      "max_image_area_km2": 10000
    },
    "cmd_pub": "04a1b2c3d4e5f6789..."
  },
  "signature": "ECDSA_SIG_BY_ESA_OPERATOR_KEY"
}
```

### Command Payload

```json
{
  "timestamp": "2025-01-15T14:32:17Z",
  "command_type": "cmd:imaging:sar:iw",
  "parameters": {
    "target_coords": {
      "type": "Polygon",
      "coordinates": [[
        [-36.2, 51.8], [-35.2, 51.8],
        [-35.2, 52.8], [-36.2, 52.8],
        [-36.2, 51.8]
      ]]
    },
    "imaging_mode": "Interferometric Wide Swath",
    "polarization": "VV+VH",
    "resolution_m": 5,
    "swath_width_km": 250,
    "incidence_angle_deg": 39.5,
    "priority": "EMERGENCY",
    "data_routing": {
      "method": "edrs_laser",
      "relay_satellite": "EDRS-C",
      "final_destination": "ESA-REDU"
    }
  }
}
```

### Data Return Path

1. **Sentinel-1C** acquires 250km x 100km SAR strip in IW mode (25GB raw data)
2. **On-board processing** reduces to 2GB Level-1 SLC product
3. **EDRS-C laser link** at 1.8 Gbps transfers data in ~9 seconds
4. **Ka-band downlink** from EDRS-C to Redu at 600 Mbps
5. **Ground processing** generates ship-detection layer
6. **Delivery** to USCG via secure network

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | MAYDAY received at USCG MRCC |
| T+0:30 | Tasking request transmitted to Iridium 180 |
| T+0:45 | Starlink mesh routes command to Sentinel-1C approach zone |
| T+2:15 | Starlink-7823 achieves 12km proximity to Sentinel-1C |
| T+2:20 | Capability token verified, command executed |
| T+5:00 | SAR acquisition begins |
| T+7:30 | Acquisition complete, EDRS link established |
| T+7:45 | Data transfer to EDRS-C complete |
| T+9:00 | Data received at Redu |
| T+12:00 | Ship-detection products delivered to USCG |

**Total latency: 12 minutes** (vs. 47 minutes waiting for ground station)

## Acceptance Criteria

- [ ] Capability token validates within 100ms on Sentinel-1C OBC
- [ ] SAR acquisition begins within 3 minutes of command receipt
- [ ] EDRS link established within 30 seconds of acquisition completion
- [ ] Data delivered to customer within 15 minutes of initial request
- [ ] All command/telemetry logs available for audit

## Technical Notes

### Sentinel-1C Specifications
- **Orbit**: 693 km, sun-synchronous, 98.2° inclination
- **SAR-C band**: 5.405 GHz (C-band)
- **Swath modes**: Strip Map (80km), IW (250km), EW (400km)
- **Resolution**: 5m (IW mode)
- **On-board storage**: 1.4 Tb

### EDRS-C Specifications
- **Orbit**: GEO, 31°E
- **Laser ISL**: 1.8 Gbps bidirectional
- **Coverage**: Europe, Atlantic, Africa
- **Latency**: Near-real-time (< 2 second propagation)

## Value Proposition

Without inter-satellite tasking, the Coast Guard would wait 47 minutes for Sentinel-1C's next ground station pass, then additional time for scheduling and acquisition. The Starlink relay reduces this to 12 minutes total, potentially saving lives in maritime emergencies.
