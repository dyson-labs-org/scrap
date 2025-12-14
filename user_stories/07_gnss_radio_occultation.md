# User Story 07: GNSS Radio Occultation Weather Data via Spire Constellation

## Summary

A numerical weather prediction center needs additional atmospheric profile data over a data-sparse ocean region to improve hurricane track forecasts. Spire's Lemur constellation is tasked via distributed coordination to maximize radio occultation coverage, with data relayed through AWS Ground Station network.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | NOAA National Hurricane Center (NHC) | - |
| **Constellation Coordinator** | Spire Mission Operations | - |
| **Data Collection 1** | LEMUR-2 PETERG | 42841 |
| **Data Collection 2** | LEMUR-2 ZACHARY | 42845 |
| **Data Collection 3** | LEMUR-2 BROWNCOW | 43125 |
| **Reference GNSS** | GPS, GLONASS, Galileo, BeiDou | Various |
| **Ground Stations** | AWS Ground Station (multiple) | - |
| **Data Assimilation** | NOAA NCEP GFS | - |

## Scenario

### Context

Hurricane Maria is intensifying in the Caribbean. NHC needs atmospheric temperature and moisture profiles in the 200km radius around the storm center to improve intensity and track forecasts. Traditional radiosondes and dropsondes are unavailable over the open ocean.

GNSS Radio Occultation (GNSS-RO) can provide vertical profiles from surface to 40km altitude by measuring GPS signal bending through the atmosphere.

### Coordinated Collection Strategy

```
                         +-------------------------------------+
                         |     Hurricane Maria AOI             |
                         |   (15-22degN, 60-70degW)                |
                         |   200km radius coverage needed      |
                         +---------------+---------------------+
                                         |
                    Required: >50 occultation profiles in 6 hours
                                         |
              +--------------------------+--------------------------+
              |                          |                          |
              v                          v                          v
       +-------------+            +-------------+            +-------------+
       | LEMUR-2     |            | LEMUR-2     |            | LEMUR-2     |
       | PETERG      |            | ZACHARY     |            | BROWNCOW    |
       | (42841)     |            | (42845)     |            | (43125)     |
       +------+------+            +------+------+            +------+------+
              |                          |                          |
              |    GNSS signal bends     |                          |
              |    through atmosphere    |                          |
              |                          |                          |
       +------+------+            +------+------+            +------+------+
       |    GPS      |            |   GLONASS   |            |   Galileo   |
       |  Satellites |            |  Satellites |            |  Satellites |
       +-------------+            +-------------+            +-------------+
              |                          |                          |
              +--------------------------+--------------------------+
                                         |
                              Occultation Profiles
                                         |
              +--------------------------+--------------------------+
              |                          |                          |
              v                          v                          v
       +-------------+            +-------------+            +-------------+
       | AWS GS      |            | AWS GS      |            | AWS GS      |
       | Ohio        |            | Oregon      |            | Singapore   |
       +------+------+            +------+------+            +------+------+
              |                          |                          |
              +--------------------------+--------------------------+
                                         |
                              +----------+----------+
                              |  NOAA NCEP GFS      |
                              |  Data Assimilation  |
                              +---------------------+
```

### Constellation Coordination Task

```json
{
  "task_id": "GNSS-RO-MARIA-2025-001",
  "task_type": "coordinated_gnss_ro",
  "target_region": {
    "type": "Circle",
    "center": {"lat": 18.5, "lon": -65.0},
    "radius_km": 200
  },
  "storm_tracking": {
    "storm_id": "AL152025",
    "name": "MARIA",
    "forecast_track": [
      {"time": "2025-01-15T12:00:00Z", "lat": 18.5, "lon": -65.0},
      {"time": "2025-01-15T18:00:00Z", "lat": 19.2, "lon": -66.5},
      {"time": "2025-01-16T00:00:00Z", "lat": 20.0, "lon": -68.0}
    ]
  },
  "collection_window": {
    "start": "2025-01-15T12:00:00Z",
    "end": "2025-01-15T18:00:00Z"
  },
  "requirements": {
    "min_profiles": 50,
    "vertical_range_km": {"min": 0, "max": 40},
    "vertical_resolution_m": 200,
    "max_latency_hours": 2,
    "gnss_systems": ["GPS", "GLONASS", "Galileo", "BeiDou"]
  },
  "priority": "HURRICANE_WARNING"
}
```

### Satellite Assignments

The constellation coordinator assigns collection windows:

```json
{
  "assignments": [
    {
      "satellite": "LEMUR-2 PETERG",
      "norad_id": 42841,
      "passes": [
        {
          "start": "2025-01-15T12:15:00Z",
          "end": "2025-01-15T12:27:00Z",
          "expected_occultations": 8,
          "gnss_targets": ["GPS-PRN04", "GPS-PRN15", "GLONASS-R07"]
        },
        {
          "start": "2025-01-15T14:05:00Z",
          "end": "2025-01-15T14:18:00Z",
          "expected_occultations": 7,
          "gnss_targets": ["GAL-E01", "GAL-E12", "GPS-PRN22"]
        }
      ]
    },
    {
      "satellite": "LEMUR-2 ZACHARY",
      "norad_id": 42845,
      "passes": [
        {
          "start": "2025-01-15T13:10:00Z",
          "end": "2025-01-15T13:22:00Z",
          "expected_occultations": 9,
          "gnss_targets": ["GPS-PRN08", "BDS-C01", "GLONASS-R14"]
        }
      ]
    },
    {
      "satellite": "LEMUR-2 BROWNCOW",
      "norad_id": 43125,
      "passes": [
        {
          "start": "2025-01-15T15:30:00Z",
          "end": "2025-01-15T15:44:00Z",
          "expected_occultations": 11,
          "gnss_targets": ["GPS-PRN31", "GAL-E24", "GLONASS-R22"]
        }
      ]
    }
  ],
  "total_expected_occultations": 72,
  "coverage_estimate_pct": 85
}
```

### GNSS-RO Collection Command

```json
{
  "timestamp": "2025-01-15T12:00:00Z",
  "command_type": "cmd:gnss_ro:collection",
  "parameters": {
    "collection_mode": "all_gnss",
    "gnss_systems": {
      "gps": {"enabled": true, "prn_range": [1, 32]},
      "glonass": {"enabled": true, "slot_range": [1, 24]},
      "galileo": {"enabled": true, "svid_range": [1, 36]},
      "beidou": {"enabled": true, "prn_range": [1, 63]}
    },
    "occultation_geometry": {
      "elevation_angle_min_deg": -90,
      "elevation_angle_max_deg": 0,
      "azimuth_filter": null
    },
    "sampling": {
      "rate_hz": 50,
      "phase_data": true,
      "snr_data": true,
      "nav_data": true
    },
    "onboard_processing": {
      "excess_phase": true,
      "bending_angle": true
    },
    "data_routing": {
      "method": "aws_ground_station",
      "priority": "high",
      "destination": "s3://noaa-gnss-ro/hurricane/maria/"
    }
  }
}
```

### Occultation Profile Data

Each occultation produces a vertical atmospheric profile:

```json
{
  "occultation_id": "LEMUR-PETERG-2025015-121845",
  "timestamp": "2025-01-15T12:18:45Z",
  "gnss_satellite": "GPS-PRN15",
  "leo_satellite": "LEMUR-2 PETERG",
  "tangent_point": {
    "latitude": 18.234,
    "longitude": -64.567,
    "distance_from_storm_center_km": 85
  },
  "geometry": {
    "azimuth_deg": 245,
    "occultation_type": "setting"
  },
  "profile": {
    "altitude_km": [0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0, 40.0],
    "bending_angle_rad": [0.0235, 0.0198, 0.0142, 0.0078, 0.0032, 0.0015, 0.0008, 0.0003, 0.0001],
    "refractivity_N": [325.2, 298.4, 245.6, 142.3, 52.1, 18.9, 7.2, 1.4, 0.3],
    "temperature_K": [299.5, 295.2, 285.4, 258.3, 223.8, 213.5, 216.8, 228.4, 252.1],
    "pressure_hPa": [1008.2, 950.3, 850.2, 540.1, 265.4, 121.8, 55.2, 11.8, 2.9],
    "water_vapor_g_kg": [18.5, 16.2, 12.4, 5.8, 0.8, 0.1, 0.01, 0.001, 0.0001]
  },
  "quality_flags": {
    "overall": "GOOD",
    "surface_penetration": true,
    "tropopause_detected": true,
    "multipath_affected_below_km": 1.5
  }
}
```

### Hurricane-Specific Products

```json
{
  "storm_environment_analysis": {
    "storm_id": "AL152025",
    "analysis_time": "2025-01-15T18:00:00Z",
    "profiles_assimilated": 67,
    "key_findings": {
      "warm_core": {
        "detected": true,
        "anomaly_K": 8.5,
        "altitude_km": 8.2
      },
      "upper_level_outflow": {
        "divergence_s-1": 2.3e-5,
        "altitude_km": 12.5
      },
      "mid_level_moisture": {
        "relative_humidity_pct": 78,
        "saturation_deficit_g_kg": 2.1
      },
      "low_level_wind_shear": {
        "estimated_knots": 12,
        "direction_deg": 270
      }
    },
    "intensity_guidance": {
      "current_category": 3,
      "24hr_forecast_category": 4,
      "rapid_intensification_probability": 0.65
    }
  }
}
```

### Data Assimilation Impact

```json
{
  "data_assimilation_report": {
    "model": "GFS",
    "cycle": "2025-01-15T18:00:00Z",
    "gnss_ro_impact": {
      "profiles_assimilated": 67,
      "rejected": 5,
      "total_observations": 4824,
      "analysis_increment_temperature_K": {
        "mean": 0.3,
        "max": 1.8,
        "region": "mid-troposphere"
      },
      "analysis_increment_moisture_pct": {
        "mean": 5.2,
        "max": 15.3,
        "region": "lower-troposphere"
      },
      "track_forecast_improvement_km": {
        "24hr": 18,
        "48hr": 35,
        "72hr": 52
      },
      "intensity_forecast_improvement_kt": {
        "24hr": 8,
        "48hr": 12,
        "72hr": 15
      }
    }
  }
}
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | NHC requests enhanced GNSS-RO coverage |
| T+0:10 | Spire constellation coordination complete |
| T+0:15 | First Lemur pass begins collection |
| T+0:30 | First profiles downlinked via AWS GS Ohio |
| T+1:00 | Mid-collection: 25 profiles acquired |
| T+2:00 | Collection complete: 67 profiles |
| T+2:15 | All data at NOAA NCEP |
| T+2:30 | Data quality control complete |
| T+3:00 | Profiles assimilated into 18Z GFS cycle |
| T+4:00 | Improved hurricane forecast issued |

## Acceptance Criteria

- [ ] >=50 occultation profiles within target region
- [ ] Profiles span surface to 40km altitude
- [ ] Data latency < 3 hours from collection to assimilation
- [ ] Warm core structure detected in composite analysis
- [ ] Track forecast improvement >=15km at 48hr

## Technical Notes

### Spire Lemur GNSS-RO Specifications
- **Orbit**: 500-600 km, various inclinations
- **GNSS receivers**: GPS, GLONASS, Galileo, BeiDou
- **Sampling rate**: 50 Hz
- **Vertical resolution**: ~200 m
- **Profiles per day**: 750-1000 per satellite
- **Accuracy**: Temperature +/-0.5 K, Pressure +/-0.5%

### GNSS-RO Physics
- GPS signal bends as it passes through atmosphere
- Bending angle alpha proportional to refractivity gradient dN/dr
- Refractivity N = f(pressure, temperature, water vapor)
- Abel inversion retrieves vertical profiles

### Hurricane Assimilation Value
- GNSS-RO provides all-weather profiles (not affected by clouds)
- Vertical resolution superior to infrared sounders
- Complements dropsondes in data-sparse regions
- Most impact in mid-troposphere (500-300 hPa)

## Value Proposition

Coordinated GNSS-RO collection provides critical atmospheric data in hurricane environments where conventional observations are unavailable. The 67 profiles improve track forecasts by 35 km at 48 hours, potentially saving lives through earlier and more accurate warnings.
