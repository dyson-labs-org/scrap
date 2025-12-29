# User Story 04: Cross-Operator LIDAR Tasking for Volcanic Ash Detection

## Summary

An airline operations center needs urgent aerosol profiling to assess volcanic ash hazards along transatlantic flight corridors. A CALIPSO LIDAR observation is requested through a cross-operator agreement, with the task delivered via a close approach from an Iridium satellite.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | EUROCONTROL Network Manager | - |
| **Task Originator** | Iridium 155 | 56715 |
| **Target Satellite** | CALIPSO | 29108 |
| **Instrument** | CALIOP (Cloud-Aerosol Lidar) | - |
| **Secondary Instrument** | WFC (Wide Field Camera) | - |
| **Data Relay** | TDRS-13 | 42915 |
| **Ground Station** | NASA GSFC, Greenbelt MD | - |

## Scenario

### Context

The Grimsvotn volcano in Iceland has begun erupting, ejecting ash into the stratosphere. EUROCONTROL needs vertical aerosol profiles along the North Atlantic Organized Track System (NAT OTS) to determine safe flight levels.

CALIPSO's orbit will cross the ash plume in 45 minutes, but the next ground contact is 2 hours away. An Iridium satellite will pass within 8 km of CALIPSO in 20 minutes.

### Cross-Operator Authorization

NASA (CALIPSO operator) has pre-issued capability tokens to Iridium for emergency atmospheric hazard observations:

```
+--------------+     +-------------+     +-----------------------------+
| EUROCONTROL  |---->|  Iridium    |---->|         CALIPSO             |
| Network Mgr  |     |    155      |     |   CALIOP + WFC instruments  |
+--------------+     +-------------+     +---------------+-------------+
                                                         |
                                                    TDRSS Relay
                                                         |
                                                         v
                                         +-----------------------------+
                                         |        TDRS-13              |
                                         |   (GEO relay satellite)     |
                                         +---------------+-------------+
                                                         |
                                                    Ku-band Downlink
                                                         |
                                                         v
                                         +-----------------------------+
                                         |   NASA GSFC Ground Station  |
                                         |   --> EUROCONTROL           |
                                         +-----------------------------+
```

### Capability Token

Pre-issued by NASA for atmospheric emergency observations:

```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "NASA-LARC",
    "sub": "IRIDIUM-EMERGENCY-RELAY",
    "aud": "CALIPSO-29108",
    "iat": 1704067200,
    "exp": 1706745600,
    "jti": "nasa-iridium-atm-hazard-2025",
    "cap": [
      "cmd:instrument:caliop:profile",
      "cmd:instrument:wfc:context",
      "cmd:downlink:tdrss"
    ],
    "cns": {
      "max_range_km": 20,
      "hazard_types": ["volcanic_ash", "dust_storm", "smoke"],
      "authorized_requestors": [
        "EUROCONTROL",
        "FAA",
        "ICAO",
        "VAAC-*"
      ],
      "max_profiles_per_day": 10,
      "geographic_bounds": {
        "lat_min": 20,
        "lat_max": 80,
        "lon_min": -80,
        "lon_max": 40
      }
    },
    "cmd_pub": "04e8f9a1b2c3d4e5..."
  }
}
```

### Tasking Command

```json
{
  "timestamp": "2025-01-15T09:22:45Z",
  "command_type": "cmd:instrument:caliop:profile",
  "parameters": {
    "observation_mode": "volcanic_ash_profiling",
    "target_track": {
      "type": "LineString",
      "coordinates": [
        [-25.0, 55.0],
        [-20.0, 58.0],
        [-15.0, 61.0],
        [-10.0, 63.0]
      ]
    },
    "altitude_range_km": {
      "min": 5,
      "max": 20
    },
    "vertical_resolution_m": 30,
    "horizontal_resolution_km": 0.333,
    "lidar_config": {
      "wavelengths_nm": [532, 1064],
      "polarization": true,
      "pulse_rate_hz": 20.16
    },
    "wfc_context": {
      "enabled": true,
      "swath_km": 61
    },
    "priority": "AVIATION_SAFETY",
    "data_routing": {
      "method": "tdrss",
      "relay_satellite": "TDRS-13",
      "ground_station": "GSFC"
    }
  }
}
```

### CALIOP Data Products

| Product | Description | Vertical Res | Horizontal Res |
|---------|-------------|--------------|----------------|
| L1B Profile | Attenuated backscatter (532/1064nm) | 30m | 333m |
| L2 Aerosol | Layer detection and classification | 60m | 5km |
| L2 Volcanic | Ash concentration estimate | 60m | 5km |
| Depolarization | Ash vs. sulfate discrimination | 30m | 333m |
| Extinction | Aerosol optical depth by layer | 60m | 5km |

### Volcanic Ash Detection Algorithm

CALIOP discriminates volcanic ash using:

1. **Depolarization ratio**: Ash particles are non-spherical ($\delta > 0.3$)
2. **Color ratio**: 1064/532 backscatter ratio indicates particle size
3. **Attenuated backscatter**: Signal strength indicates concentration
4. **Layer geometry**: Volcanic plumes have distinct altitude structure

**Depolarization Ratio vs. Aerosol Type:**

| $\delta$ Range | Aerosol Type |
|----------------|--------------|
| $\delta < 0.1$ | Sulfate, water droplets |
| $0.1 \leq \delta \leq 0.3$ | Mixed aerosol, dust |
| $\delta > 0.3$ | Volcanic ash, ice |

**Color Ratio for Particle Size:**

| $\chi$ Range | Particle Size |
|--------------|---------------|
| $\chi < 0.5$ | Small particles ($< 1 \mu m$) |
| $0.5 \leq \chi \leq 1.0$ | Medium ($1$-$5 \mu m$) |
| $\chi > 1.0$ | Large particles ($> 5 \mu m$) |

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | Eruption detected; EUROCONTROL requests LIDAR profiling |
| T+0:05 | Task submitted via Iridium uplink |
| T+0:20 | Iridium 155 passes 8km from CALIPSO |
| T+0:21 | Capability token verified; command accepted |
| T+0:45 | CALIPSO crosses ash plume trajectory |
| T+0:52 | 400km profile acquired |
| T+0:55 | TDRSS link established |
| T+1:05 | L1B data received at GSFC |
| T+1:35 | L2 aerosol products generated |
| T+1:45 | Volcanic ash advisory issued to EUROCONTROL |

**Total latency: 1 hour 45 minutes** (vs. 3+ hours via scheduled ground pass)

### Data Delivery

Final delivery to EUROCONTROL includes:

```json
{
  "observation_id": "CALIPSO-2025-015-0945",
  "instrument": "CALIOP",
  "acquisition_time": "2025-01-15T09:45:00Z",
  "track": {
    "start": {"lat": 55.0, "lon": -25.0, "alt_km": 705},
    "end": {"lat": 63.0, "lon": -10.0, "alt_km": 705},
    "length_km": 1200
  },
  "volcanic_ash_detected": true,
  "ash_layers": [
    {
      "top_km": 12.5,
      "base_km": 9.2,
      "thickness_km": 3.3,
      "peak_concentration_ug_m3": 850,
      "optical_depth": 0.42,
      "particle_size_um": 3.5,
      "lat_extent": [57.2, 62.1],
      "lon_extent": [-22.5, -12.3]
    },
    {
      "top_km": 8.1,
      "base_km": 6.4,
      "thickness_km": 1.7,
      "peak_concentration_ug_m3": 420,
      "optical_depth": 0.18,
      "particle_size_um": 2.1,
      "lat_extent": [55.8, 59.3],
      "lon_extent": [-24.0, -18.5]
    }
  ],
  "safe_flight_levels": {
    "FL300_plus": "AVOID - ash concentration >200 ug/m^3",
    "FL250_300": "CAUTION - marginal conditions",
    "FL250_below": "CLEAR - no detected ash"
  },
  "products": {
    "L1B_profile": "s3://nasa-calipso/2025/015/CAL_LID_L1B_Valc.hdf",
    "L2_aerosol": "s3://nasa-calipso/2025/015/CAL_LID_L2_Aerosol.hdf",
    "quicklook_png": "s3://nasa-calipso/2025/015/quicklook_ash.png"
  }
}
```

## Acceptance Criteria

- [ ] Iridium-CALIPSO proximity pass within 20km
- [ ] Capability token validates on CALIPSO OBC
- [ ] CALIOP acquires profile within 1 hour of request
- [ ] TDRSS relay completes within 15 minutes of acquisition
- [ ] Volcanic ash products delivered within 2 hours

## Technical Notes

### CALIOP Specifications
- **Orbit**: 705 km, sun-synchronous (A-Train), 98.2deg inclination
- **Laser wavelengths**: 532 nm (polarized), 1064 nm
- **Pulse energy**: 110 mJ
- **Pulse rate**: 20.16 Hz
- **Footprint**: 70m diameter
- **Vertical resolution**: 30-60 m
- **Horizontal resolution**: 333 m (single shot), 5 km (averaged)

### TDRSS Capabilities
- **Coverage**: Near-continuous (85%+ orbital coverage)
- **Data rate**: Up to 300 Mbps (S-band), 800 Mbps (Ku-band)
- **Latency**: < 1 second relay delay

## Value Proposition

Cross-operator capability tokens enable emergency atmospheric observations without waiting for ground station passes. Aviation safety decisions are made 2 hours faster, potentially preventing ash encounters that could disable aircraft engines.
