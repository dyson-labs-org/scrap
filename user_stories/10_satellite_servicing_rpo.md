# User Story 10: GEO Satellite Life Extension via MEV Servicing

## Summary

A commercial satellite operator extends the operational life of a fuel-depleted GEO communications satellite by docking with Northrop Grumman's Mission Extension Vehicle (MEV). The servicing mission uses inter-satellite capability tokens for autonomous docking authorization.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | Intelsat | - |
| **Client Satellite** | Intelsat 10-02 | 28358 |
| **Servicer Vehicle** | MEV-3 | 57320 |
| **Ground Control** | NGC Mission Operations (Dulles, VA) | - |
| **Relay** | TDRS-11 | 39070 |
| **Coordination** | Space Data Association | - |

## Scenario

### Context

Intelsat 10-02, a 4,500 kg C/Ku-band communications satellite at 1degW, is running low on station-keeping fuel. Rather than decommission the satellite (which has functional transponders worth $400M), Intelsat contracts with Northrop Grumman for a Mission Extension Vehicle docking.

MEV-3 will dock with Intelsat 10-02 and take over attitude control and station-keeping for 5+ years.

### Servicing Mission Architecture

```
Phase 1: Approach (500 km -> 1 km)
+---------------------------------------------------------------------+
|                                                                     |
|    GEO Belt (35,786 km altitude)                                   |
|                                                                     |
|    MEV-3 o---------------------------------->* Intelsat 10-02      |
|    (servicer)                                 (client)              |
|                                                                     |
|    Phasing maneuvers over 2 weeks                                  |
|    Ground-commanded with SDA coordination                          |
+---------------------------------------------------------------------+

Phase 2: Proximity Operations (1 km -> 10 m)
+---------------------------------------------------------------------+
|                                                                     |
|                    Inspection Arc                                   |
|                  +-----------------+                                |
|    MEV-3 ------->(       *         )  Intelsat 10-02               |
|                  +-----------------+                                |
|                                                                     |
|    Client characterization and docking readiness                   |
|    Autonomous with ground oversight                                |
+---------------------------------------------------------------------+

Phase 3: Docking
+---------------------------------------------------------------------+
|                                                                     |
|                         Liquid Apogee Engine                        |
|                              Nozzle                                 |
|                                |                                    |
|    MEV-3 Capture +-------------+-------------+                      |
|    System -------->          *               |  Intelsat 10-02     |
|    (LAE dock)    |    (capture interface)    |                      |
|                  +---------------------------+                      |
|                                                                     |
|    Final approach: 0.01 m/s contact velocity                       |
+---------------------------------------------------------------------+

Phase 4: Servicing Operations
+---------------------------------------------------------------------+
|                                                                     |
|              +---------------------------------+                    |
|              |   Combined Stack                |                    |
|              |   MEV-3 + Intelsat 10-02        |                    |
|              |                                 |                    |
|              |   * MEV provides:               |                    |
|              |     - Station-keeping           |                    |
|              |     - Attitude control          |                    |
|              |     - Orbit adjustments         |                    |
|              |                                 |                    |
|              |   * Intelsat provides:          |                    |
|              |     - Transponder payload       |                    |
|              |     - Power generation          |                    |
|              |     - Thermal control           |                    |
|              +---------------------------------+                    |
|                                                                     |
|    Mission life extended 5+ years                                  |
+---------------------------------------------------------------------+
```

### Capability Token for Docking Authorization

Intelsat pre-authorizes MEV-3 docking:

```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "INTELSAT-OPS",
    "sub": "NGC-MEV-3",
    "aud": "INTELSAT-10-02-28358",
    "iat": 1705320000,
    "exp": 1707998400,
    "jti": "mev3-dock-auth-001",
    "cap": [
      "cmd:rpo:approach",
      "cmd:rpo:inspect",
      "cmd:rpo:dock",
      "cmd:attitude:safe_mode",
      "cmd:attitude:handover",
      "cmd:transponder:safing"
    ],
    "cns": {
      "min_approach_distance_m": 0,
      "docking_interface": "LAE_nozzle",
      "client_attitude_mode": "sun_point_hold",
      "max_contact_velocity_m_s": 0.05,
      "abort_conditions": [
        "attitude_excursion_deg": 5,
        "relative_velocity_exceeded",
        "ground_abort_command",
        "client_anomaly"
      ],
      "fuel_budget_mev_kg": 50,
      "mission_duration_years": 5
    },
    "client_configuration": {
      "norad_id": 28358,
      "name": "INTELSAT 10-02",
      "mass_kg": 4527,
      "fuel_remaining_kg": 12,
      "station": "1.0W",
      "docking_interface": {
        "type": "LAE_nozzle",
        "diameter_mm": 450,
        "offset_from_cg_m": {"x": 0, "y": 0, "z": -2.1}
      },
      "keep_out_zones": [
        {"type": "solar_array", "clearance_m": 5},
        {"type": "antenna_dish", "clearance_m": 3}
      ]
    },
    "cmd_pub": "04f1e2d3c4b5a697..."
  }
}
```

### Pre-Docking Inspection Command

```json
{
  "timestamp": "2025-01-28T12:00:00Z",
  "command_type": "cmd:rpo:inspect",
  "parameters": {
    "inspection_phase": "pre_dock",
    "station_distance_m": 50,
    "inspection_objectives": [
      "lae_nozzle_condition",
      "solar_array_position",
      "antenna_orientation",
      "thermal_blanket_status",
      "client_attitude_stability"
    ],
    "sensor_config": {
      "optical": {
        "mode": "high_resolution",
        "filters": ["visible", "NIR"],
        "target_gsd_mm": 5
      },
      "lidar": {
        "mode": "precision_ranging",
        "rate_hz": 10,
        "accuracy_mm": 5
      },
      "thermal": {
        "bands": ["MWIR"],
        "objective": "hot_spot_detection"
      }
    },
    "client_request": {
      "command_type": "cmd:attitude:safe_mode",
      "parameters": {
        "mode": "sun_point_hold",
        "thruster_inhibit": true,
        "antenna_stow": false
      }
    }
  }
}
```

### Docking Sequence Command

```json
{
  "timestamp": "2025-01-29T08:00:00Z",
  "command_type": "cmd:rpo:dock",
  "parameters": {
    "docking_sequence": "standard_lae",
    "approach_corridor": {
      "type": "cone",
      "half_angle_deg": 10,
      "axis": "client_thrust_vector"
    },
    "waypoints": [
      {"range_m": 50, "hold_sec": 300, "go_nogo": "ground_approval"},
      {"range_m": 20, "hold_sec": 120, "go_nogo": "autonomous"},
      {"range_m": 5, "hold_sec": 60, "go_nogo": "ground_approval"},
      {"range_m": 0, "action": "capture"}
    ],
    "capture_parameters": {
      "contact_velocity_m_s": 0.02,
      "misalignment_tolerance_deg": 2,
      "capture_mechanism": "expandable_ring",
      "capture_confirmation": ["force_sensor", "visual", "telemetry"]
    },
    "abort_modes": {
      "manual_abort": "collision_avoidance_maneuver",
      "auto_abort": "radial_retreat_10m"
    }
  }
}
```

### Post-Dock Handover

```json
{
  "timestamp": "2025-01-29T09:15:00Z",
  "command_type": "cmd:attitude:handover",
  "parameters": {
    "handover_type": "attitude_control",
    "sequence": [
      {
        "step": 1,
        "action": "client_thruster_inhibit",
        "timeout_sec": 30
      },
      {
        "step": 2,
        "action": "mev_attitude_capture",
        "mode": "rate_damping",
        "timeout_sec": 300
      },
      {
        "step": 3,
        "action": "combined_attitude_control",
        "mode": "three_axis_stabilized",
        "reference": "client_nominal"
      },
      {
        "step": 4,
        "action": "station_keeping_transfer",
        "orbit_slot": "1.0W",
        "box_longitude_deg": 0.05,
        "box_latitude_deg": 0.05
      }
    ],
    "client_post_dock_config": {
      "transponders": "operational",
      "solar_arrays": "tracking",
      "thermal": "autonomous",
      "telemetry": "via_mev_relay"
    }
  }
}
```

### Mission Extension Status

```json
{
  "servicing_mission": {
    "mission_id": "MEV3-IS1002-2025",
    "servicer": "MEV-3",
    "client": "INTELSAT 10-02",
    "dock_time": "2025-01-29T09:00:00Z",
    "undock_planned": "2030-01-29T09:00:00Z",
    "status": "operational",
    "combined_mass_kg": 6527,
    "station": "1.0W"
  },
  "performance_metrics": {
    "station_keeping": {
      "longitude_error_deg": 0.012,
      "latitude_error_deg": 0.008,
      "fuel_consumption_kg_year": 4.2
    },
    "attitude_control": {
      "pointing_accuracy_deg": 0.05,
      "stability_deg_s": 0.001
    },
    "client_payload": {
      "c_band_transponders": 24,
      "ku_band_transponders": 14,
      "transponder_utilization_pct": 92
    }
  },
  "life_extension": {
    "original_eol": "2025-06-01",
    "extended_eol": "2030-01-29",
    "life_extension_years": 4.7,
    "revenue_preserved_usd": 180000000
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T-30 days | MEV-3 begins phasing to client longitude |
| T-14 days | MEV-3 co-located with Intelsat 10-02 (1 km) |
| T-7 days | Pre-docking inspection complete |
| T-3 days | Docking rehearsal and final go/no-go |
| T+0:00 | Final approach initiated |
| T+2:00 | 50m waypoint - ground approval |
| T+2:30 | 20m waypoint - autonomous |
| T+3:00 | 5m waypoint - ground approval |
| T+3:15 | Contact and capture |
| T+3:30 | Capture confirmed |
| T+4:00 | Attitude handover complete |
| T+6:00 | Station-keeping resumed |
| T+24:00 | Combined operations nominal |

**Mission Duration: 30 days approach + 5 years servicing**

## Acceptance Criteria

- [ ] Safe approach within regulatory guidelines
- [ ] Docking achieved with <0.05 m/s contact velocity
- [ ] Attitude handover within 1 hour of dock
- [ ] Station-keeping accuracy maintained at +/-0.05deg
- [ ] Client transponders operational post-dock
- [ ] 5-year mission extension achieved

## Technical Notes

### MEV-3 Specifications
- **Mass**: 2,000 kg
- **Propulsion**: Electric (Hall thrusters) + chemical
- **Capture mechanism**: Expandable capture ring (LAE interface)
- **Design life**: 15+ years
- **Serviceable clients**: GEO satellites with LAE nozzle

### Intelsat 10-02 Specifications
- **Launch**: 2004
- **Mass**: 4,527 kg
- **Transponders**: 24 C-band, 14 Ku-band
- **Coverage**: Europe, Middle East, Africa
- **Original design life**: 15 years
- **Station**: 1.0degW

### Docking Interface (LAE Nozzle)
- Most GEO satellites use Liquid Apogee Engine for orbit raising
- LAE nozzle provides standardized mechanical interface
- MEV capture ring expands inside nozzle throat
- No modification to client satellite required

### Regulatory Requirements
- FCC and ITU coordination required
- Collision avoidance during approach
- Space Data Association notification
- Insurance adjustments for combined stack

## Value Proposition

Satellite life extension via MEV servicing preserves $180M in transponder revenue at a fraction of replacement cost. The capability token framework enables autonomous docking while maintaining operator oversight, paving the way for scalable on-orbit servicing operations.
