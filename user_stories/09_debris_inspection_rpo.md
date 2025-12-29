# User Story 09: Space Debris Inspection via RPO

## Summary

A space situational awareness provider tasks an inspector satellite to perform close-approach inspection of a defunct satellite that may be fragmenting. The inspector uses capability tokens to safely approach, image, and characterize the debris environment around the target.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | LeoLabs Space Domain Awareness | - |
| **Inspector Satellite** | Astroscale ADRAS-J | 58974 |
| **Target Object** | Envisat (defunct) | 27386 |
| **Tasking Relay** | Iridium constellation | Various |
| **Data Relay** | TDRS-12 | 39504 |
| **Ground Station** | NASA White Sands | - |

## Scenario

### Context

Ground-based radar has detected anomalous radar cross-section changes around Envisat, a 8-ton defunct ESA satellite in 773 km orbit. LeoLabs needs close-range inspection to:
1. Determine if fragmentation is occurring
2. Characterize debris cloud if present
3. Assess risk to operational satellites

Astroscale's ADRAS-J inspector satellite is tasked for Rendezvous and Proximity Operations (RPO).

### RPO Mission Profile

```
Phase 1: Far-Range Rendezvous (100 km -> 1 km)
+---------------------------------------------------------------------+
|                                                                     |
|    ADRAS-J                                    Envisat               |
|       o----------------------------------------*                    |
|    Inspector                              Target (defunct)          |
|                                                                     |
|    Deltav burns to reduce relative distance                             |
|    Duration: ~24 hours                                              |
+---------------------------------------------------------------------+

Phase 2: Close-Range Inspection (1 km -> 50 m)
+---------------------------------------------------------------------+
|                                                                     |
|                          Inspection arc                             |
|                        +---------------+                            |
|    ADRAS-J --------->( o     Envisat   * )                          |
|                        +---------------+                            |
|                                                                     |
|    Station-keeping at safe distance                                 |
|    Multi-angle imaging                                              |
+---------------------------------------------------------------------+

Phase 3: Debris Field Characterization (circumnavigation)
+---------------------------------------------------------------------+
|                                                                     |
|                  +----------------------+                           |
|               +--+                      +--+                        |
|            o--+  |      Envisat *       |  +--o                     |
|               +--+                      +--+                        |
|                  +----------------------+                           |
|                                                                     |
|    Circumnavigation at 100m distance                                |
|    LIDAR + optical debris detection                                 |
+---------------------------------------------------------------------+
```

### Capability Token

LeoLabs pre-negotiated authorization with Astroscale for debris inspection:

```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "ASTROSCALE-OPS",
    "sub": "LEOLABS-SSA",
    "aud": "ADRAS-J-58974",
    "iat": 1705320000,
    "exp": 1705752000,
    "jti": "adrasj-debris-inspect-001",
    "cap": [
      "cmd:rpo:approach",
      "cmd:rpo:station_keep",
      "cmd:rpo:circumnavigate",
      "cmd:imaging:optical:hires",
      "cmd:sensor:lidar",
      "cmd:sensor:ir_thermal"
    ],
    "cns": {
      "min_approach_distance_m": 30,
      "max_relative_velocity_m_s": 0.1,
      "keep_out_zones": [],
      "lighting_required": true,
      "fuel_budget_kg": 2.5,
      "abort_triggers": [
        "relative_velocity_exceeded",
        "attitude_anomaly",
        "debris_impact_detected"
      ]
    },
    "target": {
      "norad_id": 27386,
      "name": "ENVISAT",
      "mass_kg": 8211,
      "dimensions_m": {"x": 26, "y": 10, "z": 5},
      "status": "defunct",
      "tumble_rate_deg_s": 2.5
    },
    "cmd_pub": "04c7d8e9f0a1b2c3..."
  }
}
```

### RPO Tasking Commands

**Phase 1: Approach Initiation**
```json
{
  "timestamp": "2025-01-15T06:00:00Z",
  "command_type": "cmd:rpo:approach",
  "parameters": {
    "target_norad_id": 27386,
    "approach_phase": "far_range",
    "initial_range_km": 100,
    "final_range_km": 1,
    "approach_velocity_m_s": 2.0,
    "safety_corridor": {
      "type": "cylinder",
      "radius_m": 500,
      "orientation": "velocity_vector"
    },
    "imaging_during_approach": {
      "enabled": true,
      "interval_sec": 600,
      "mode": "navigation"
    }
  }
}
```

**Phase 2: Close-Range Inspection**
```json
{
  "timestamp": "2025-01-16T06:00:00Z",
  "command_type": "cmd:rpo:station_keep",
  "parameters": {
    "station_keep_distance_m": 100,
    "position_relative_to_target": "trailing",
    "hold_duration_sec": 7200,
    "imaging_sequence": [
      {
        "sensor": "optical_hires",
        "exposure_ms": 10,
        "filter": "panchromatic",
        "frames": 100,
        "interval_sec": 60
      },
      {
        "sensor": "lidar",
        "mode": "3d_scan",
        "resolution_cm": 5,
        "fov_deg": 30
      },
      {
        "sensor": "ir_thermal",
        "bands": ["MWIR", "LWIR"],
        "frames": 50
      }
    ]
  }
}
```

**Phase 3: Circumnavigation**
```json
{
  "timestamp": "2025-01-16T08:00:00Z",
  "command_type": "cmd:rpo:circumnavigate",
  "parameters": {
    "circumnavigation_radius_m": 100,
    "plane": "orbit_normal",
    "period_minutes": 90,
    "laps": 2,
    "debris_detection": {
      "enabled": true,
      "sensor": "lidar",
      "tracking_mode": "multi_target",
      "size_threshold_cm": 1.0
    },
    "collision_avoidance": {
      "enabled": true,
      "abort_threshold_m": 30,
      "maneuver_authority": "autonomous"
    }
  }
}
```

### Inspection Data Products

**Target Characterization:**
```json
{
  "inspection_id": "ADRASJ-ENVISAT-2025-001",
  "target": {
    "norad_id": 27386,
    "name": "ENVISAT",
    "inspection_time": "2025-01-16T06:00:00Z"
  },
  "structural_assessment": {
    "overall_integrity": "degraded",
    "solar_array_status": "partially_deployed",
    "antenna_status": "intact",
    "thermal_blankets": "degraded_flaking",
    "visible_damage": [
      {
        "location": "solar_array_hinge",
        "type": "material_delamination",
        "size_cm": 45
      },
      {
        "location": "forward_radiator",
        "type": "micrometeoroid_impact",
        "size_cm": 2.3
      }
    ]
  },
  "tumble_analysis": {
    "rotation_rate_deg_s": 2.47,
    "rotation_axis": {"x": 0.12, "y": 0.95, "z": 0.29},
    "stability": "stable_rotation"
  },
  "thermal_map": {
    "hotspots": [],
    "average_temp_K": 285,
    "temp_range_K": {"min": 220, "max": 310}
  }
}
```

**Debris Field Characterization:**
```json
{
  "debris_survey": {
    "survey_volume": {
      "type": "sphere",
      "center": "ENVISAT",
      "radius_m": 500
    },
    "detection_summary": {
      "total_objects_detected": 23,
      "size_distribution": {
        ">10cm": 3,
        "5-10cm": 7,
        "1-5cm": 13
      }
    },
    "tracked_debris": [
      {
        "debris_id": "ENV-DEB-001",
        "size_cm": 12,
        "relative_position_m": {"x": 145, "y": -23, "z": 67},
        "relative_velocity_m_s": {"x": 0.02, "y": -0.01, "z": 0.03},
        "probable_source": "thermal_blanket_fragment"
      },
      {
        "debris_id": "ENV-DEB-002",
        "size_cm": 8,
        "relative_position_m": {"x": -78, "y": 112, "z": -34},
        "relative_velocity_m_s": {"x": -0.01, "y": 0.02, "z": -0.02},
        "probable_source": "solar_array_material"
      }
    ],
    "fragmentation_assessment": {
      "active_fragmentation": false,
      "recent_fragmentation": true,
      "estimated_event_date": "2024-11-15T00:00:00Z",
      "confidence": 0.75
    },
    "collision_risk": {
      "debris_within_500m": 23,
      "debris_crossing_leo_traffic": 3,
      "conjunction_screening_recommended": true
    }
  }
}
```

### LIDAR 3D Model

```json
{
  "lidar_model": {
    "scan_id": "ADRASJ-LIDAR-2025-001",
    "point_count": 2450000,
    "resolution_cm": 5,
    "coverage_pct": 94,
    "model_format": "PLY",
    "model_url": "s3://leolabs-ssa/envisat/envisat_3d_model.ply",
    "derived_measurements": {
      "overall_dimensions_m": {"x": 25.8, "y": 9.7, "z": 4.9},
      "solar_array_deployed_pct": 72,
      "volume_m3": 1235,
      "surface_area_m2": 890
    }
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | LeoLabs detects radar anomaly around Envisat |
| T+2:00 | Inspection task submitted to ADRAS-J |
| T+4:00 | Far-range approach begins |
| T+28:00 | 1 km station-keeping achieved |
| T+30:00 | Close-range inspection begins |
| T+32:00 | Station-keeping imaging complete |
| T+34:00 | Circumnavigation begins |
| T+37:00 | Circumnavigation complete |
| T+38:00 | Data relay via TDRS-12 |
| T+40:00 | Full inspection report delivered |

**Total mission duration: 40 hours**

## Acceptance Criteria

- [ ] Approach within 100m without collision
- [ ] Tumble rate characterized to +/-0.1 deg/s
- [ ] Debris >1cm detected within 500m radius
- [ ] 3D LIDAR model with 5cm resolution
- [ ] Assessment report within 48 hours

## Technical Notes

### ADRAS-J Specifications
- **Mission**: Active Debris Removal demonstrator
- **Mass**: 150 kg
- **Propulsion**: Hydrazine thrusters
- **Sensors**: Optical camera, LIDAR, IR thermal
- **Proximity ops**: Capable to <10m approach
- **CDTI**: Collision Detection and Tracking Instrument

### Envisat Characteristics
- **Launch**: 2002
- **Failure**: 2012 (contact lost)
- **Mass**: 8,211 kg
- **Size**: 26m x 10m x 5m
- **Orbit**: 773 km, 98.5deg inclination
- **Tumble**: ~2.5 deg/s (post-failure)

### RPO Safety Requirements
- **Keep-out sphere**: 30m minimum
- **Relative velocity**: <0.1 m/s at close range
- **Lighting**: Sunlit target required
- **Abort capability**: Autonomous collision avoidance

## Value Proposition

Close-range RPO inspection provides detailed characterization impossible from ground radar. The debris field assessment enables accurate collision risk modeling, potentially preventing cascading Kessler syndrome events in the LEO environment.
