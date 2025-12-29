# User Story 12: On-Orbit Data Processing via Orbital Data Center

## Summary

A climate research organization needs global ocean color data processed into derived products. Rather than downloading terabytes of raw data, the processing is performed on an orbital data center that receives data via ISL, processes it using edge computing, and delivers only the refined products to ground.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | NOAA Coral Reef Watch | - |
| **Data Source 1** | Sentinel-3A (OLCI) | 41335 |
| **Data Source 2** | Sentinel-3B (OLCI) | 43437 |
| **Data Source 3** | JPSS-2 (VIIRS) | 54234 |
| **Orbital Data Center** | Loft Orbital YAM-6 | 55123 |
| **ISL Network** | Starlink constellation | Various |
| **Ground Station** | AWS Ground Station, Oregon | - |

## Scenario

### Context

NOAA Coral Reef Watch monitors global sea surface temperature (SST) and ocean color for coral bleaching alerts. Traditional processing requires:
- Downloading 2.4 TB/day of raw ocean color data
- Ground-based atmospheric correction
- Multi-sensor fusion
- Product generation

This creates a 12-24 hour latency from acquisition to alert. An orbital data center can reduce this to 2-3 hours by processing in space.

### Orbital Processing Architecture

```
+-------------------------------------------------------------------------+
|                         Data Sources (LEO)                               |
+--------------------+--------------------+--------------------------------+
|    Sentinel-3A     |    Sentinel-3B     |         JPSS-2                 |
|    OLCI Imager     |    OLCI Imager     |      VIIRS Imager              |
|    (41335)         |    (43437)         |       (54234)                  |
+---------+----------+---------+----------+--------------+-----------------+
          |                    |                         |
          |    Starlink ISL    |     Starlink ISL       |
          |    (1.8 Gbps)      |     (1.8 Gbps)         |
          |                    |                         |
          +--------------------+-------------------------+
                               |
                               v
               +-------------------------------+
               |     Loft Orbital YAM-6        |
               |     Orbital Data Center       |
               |                               |
               |  +-------------------------+  |
               |  |   GPU Processing Unit   |  |
               |  |   - NVIDIA Jetson AGX   |  |
               |  |   - 275 TOPS AI         |  |
               |  |   - 32GB RAM            |  |
               |  +-------------------------+  |
               |                               |
               |  +-------------------------+  |
               |  |   Storage: 10 TB SSD    |  |
               |  +-------------------------+  |
               |                               |
               |  +-------------------------+  |
               |  |   Processing Pipeline   |  |
               |  |   - Atmospheric corr.   |  |
               |  |   - Ocean color deriv.  |  |
               |  |   - SST calculation     |  |
               |  |   - Anomaly detection   |  |
               |  +-------------------------+  |
               |                               |
               |  (NORAD 55123)                |
               +---------------+---------------+
                               |
                    Processed products only
                    (10% of raw data volume)
                               |
                               v
               +-------------------------------+
               |    AWS Ground Station         |
               |    Oregon                     |
               +---------------+---------------+
                               |
                               v
               +-------------------------------+
               |    NOAA Coral Reef Watch      |
               |    Bleaching Thermal Stress   |
               +-------------------------------+
```

### Processing Task Definition

```json
{
  "task_id": "CRW-GLOBAL-SST-2025-015",
  "task_type": "orbital_data_processing",
  "customer": "NOAA Coral Reef Watch",
  "processing_node": "LOFT-YAM6-55123",
  "data_sources": [
    {
      "satellite": "Sentinel-3A",
      "norad_id": 41335,
      "instrument": "OLCI",
      "data_type": "L1B_radiance",
      "bands": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 17, 18, 21],
      "expected_volume_gb_day": 180
    },
    {
      "satellite": "Sentinel-3B",
      "norad_id": 43437,
      "instrument": "OLCI",
      "data_type": "L1B_radiance",
      "bands": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 17, 18, 21],
      "expected_volume_gb_day": 180
    },
    {
      "satellite": "JPSS-2",
      "norad_id": 54234,
      "instrument": "VIIRS",
      "data_type": "SDR",
      "bands": ["M1-M16", "I1-I5"],
      "expected_volume_gb_day": 450
    }
  ],
  "processing_pipeline": {
    "steps": [
      "atmospheric_correction",
      "ocean_color_derivation",
      "sst_calculation",
      "multi_sensor_fusion",
      "anomaly_detection",
      "product_generation"
    ],
    "algorithms": {
      "atmospheric_correction": "POLYMER_v4.16",
      "ocean_color": "OC-CCI_v6.0",
      "sst": "GHRSST_SQUAM_v3",
      "fusion": "OI_AVHRR_AMSR2"
    }
  },
  "output_products": [
    "SST_daily_composite",
    "SST_anomaly_5km",
    "Chlorophyll_a_4km",
    "Bleaching_HotSpot",
    "Degree_Heating_Week",
    "Coral_Bleaching_Alert"
  ],
  "delivery": {
    "method": "ground_station_downlink",
    "format": "NetCDF4",
    "compression": "zstd",
    "destination": "s3://noaa-crw/daily/"
  }
}
```

### Capability Token for Data Access

```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "LOFT-ORBITAL",
    "sub": "NOAA-CRW",
    "aud": "LOFT-YAM6-55123",
    "iat": 1705320000,
    "exp": 1736856000,
    "jti": "crw-processing-2025",
    "cap": [
      "data:receive:sentinel3",
      "data:receive:jpss2",
      "compute:gpu:256h_day",
      "storage:10tb",
      "downlink:priority"
    ],
    "cns": {
      "processing_quota_tflops_day": 500,
      "storage_quota_tb": 10,
      "downlink_quota_gb_day": 100,
      "geographic_mask": "ocean_only",
      "latency_sla_hours": 4
    },
    "data_agreements": {
      "sentinel3": "ESA-COPERNICUS-LICENSE",
      "jpss2": "NOAA-DATA-ACCESS"
    }
  }
}
```

### ISL Data Transfer Commands

**Sentinel-3A to ODC Transfer:**
```json
{
  "timestamp": "2025-01-15T08:30:00Z",
  "command_type": "cmd:isl:data_transfer",
  "parameters": {
    "source_satellite": "SENTINEL-3A",
    "destination": "LOFT-YAM6",
    "data_type": "OLCI_L1B",
    "time_range": {
      "start": "2025-01-15T06:00:00Z",
      "end": "2025-01-15T08:00:00Z"
    },
    "geographic_filter": {
      "type": "bbox",
      "coords": [-180, -40, 180, 40]
    },
    "transfer_window": {
      "isl_established": "2025-01-15T08:32:00Z",
      "duration_sec": 600,
      "data_rate_mbps": 1200
    }
  }
}
```

### Processing Pipeline Execution

```json
{
  "processing_job": {
    "job_id": "CRW-2025-015-DAILY",
    "start_time": "2025-01-15T10:00:00Z",
    "input_data": {
      "sentinel3a_granules": 45,
      "sentinel3b_granules": 42,
      "jpss2_granules": 28,
      "total_volume_gb": 285
    },
    "pipeline_stages": [
      {
        "stage": "atmospheric_correction",
        "algorithm": "POLYMER",
        "gpu_utilization_pct": 85,
        "duration_min": 45,
        "output_volume_gb": 120
      },
      {
        "stage": "ocean_color_derivation",
        "products": ["Chlorophyll_a", "TSM", "CDOM"],
        "gpu_utilization_pct": 72,
        "duration_min": 30,
        "output_volume_gb": 45
      },
      {
        "stage": "sst_calculation",
        "method": "split_window",
        "gpu_utilization_pct": 65,
        "duration_min": 20,
        "output_volume_gb": 25
      },
      {
        "stage": "multi_sensor_fusion",
        "method": "optimal_interpolation",
        "gpu_utilization_pct": 90,
        "duration_min": 35,
        "output_volume_gb": 15
      },
      {
        "stage": "anomaly_detection",
        "baseline": "1985-2012_climatology",
        "gpu_utilization_pct": 45,
        "duration_min": 15,
        "output_volume_gb": 8
      },
      {
        "stage": "product_generation",
        "formats": ["NetCDF4", "GeoTIFF", "PNG"],
        "compression": true,
        "duration_min": 10,
        "output_volume_gb": 12
      }
    ],
    "total_processing_time_min": 155,
    "input_to_output_ratio": 23.75
  }
}
```

### Output Products

**SST Daily Composite:**
```json
{
  "product_id": "CRW-SST-DAILY-20250115",
  "product_type": "sea_surface_temperature",
  "temporal_coverage": "2025-01-15",
  "spatial_coverage": {
    "type": "global_ocean",
    "bbox": [-180, -90, 180, 90],
    "resolution_km": 5
  },
  "statistics": {
    "mean_sst_k": 292.4,
    "min_sst_k": 271.2,
    "max_sst_k": 305.8,
    "valid_pixels_pct": 78.5
  },
  "file_info": {
    "format": "NetCDF4",
    "size_mb": 450,
    "compression": "zstd_level3",
    "variables": ["sst", "sst_uncertainty", "quality_flag"]
  }
}
```

**Coral Bleaching Alert:**
```json
{
  "product_id": "CRW-BLEACHING-ALERT-20250115",
  "product_type": "coral_bleaching_thermal_stress",
  "temporal_coverage": "2025-01-15",
  "alert_areas": [
    {
      "region": "Great Barrier Reef - Northern",
      "alert_level": 2,
      "hotspot_max_c": 1.8,
      "degree_heating_weeks": 6.2,
      "bleaching_probability_pct": 75,
      "recommended_action": "monitoring_intensification"
    },
    {
      "region": "Florida Keys",
      "alert_level": 1,
      "hotspot_max_c": 1.2,
      "degree_heating_weeks": 3.1,
      "bleaching_probability_pct": 35,
      "recommended_action": "watch"
    },
    {
      "region": "Red Sea - Northern",
      "alert_level": 0,
      "hotspot_max_c": 0.5,
      "degree_heating_weeks": 0.8,
      "bleaching_probability_pct": 5,
      "recommended_action": "no_action"
    }
  ],
  "global_summary": {
    "reefs_at_alert_level_2": 12,
    "reefs_at_alert_level_1": 28,
    "reefs_at_watch": 45,
    "total_reefs_monitored": 250
  }
}
```

### Data Volume Comparison

| Stage | Traditional | Orbital Processing |
|-------|-------------|-------------------|
| Raw data acquired | 810 GB | 810 GB |
| Data downlinked | 810 GB | 35 GB |
| Ground processing | 810 GB | 0 GB |
| Downlink time (100 Mbps) | 18 hours | 47 min |
| Processing time | 6 hours | 2.5 hours |
| **Total latency** | **24+ hours** | **3 hours** |

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | Sentinel-3A morning pass begins |
| T+2:00 | Sentinel-3A data transferred to ODC via ISL |
| T+2:30 | Sentinel-3B data transferred to ODC |
| T+3:00 | JPSS-2 data transferred to ODC |
| T+3:15 | Processing pipeline initiated |
| T+5:45 | Processing complete |
| T+6:00 | Product downlink to AWS Oregon |
| T+6:30 | Products available in NOAA CRW system |

**Total latency: 6.5 hours** (vs. 24+ hours traditional)

## Acceptance Criteria

- [ ] ISL data transfers complete within 2-hour window
- [ ] Processing completes within 3 hours
- [ ] Output products < 5% of input data volume
- [ ] SST accuracy within +/-0.3 K
- [ ] Bleaching alerts issued within 6 hours
- [ ] 99% uptime SLA maintained

## Technical Notes

### Loft Orbital YAM-6 Specifications

*Note: NORAD ID 55123 is hypothetical for this scenario. Loft Orbital operates YAM-series satellites, but this specific configuration represents a future orbital data center capability.*

- **Platform**: Loft Orbital YAM (Yet Another Micro-satellite)
- **Computing**: NVIDIA Jetson AGX Orin
- **Performance**: 275 TOPS INT8, 138 TFLOPS FP16
- **Storage**: 10 TB radiation-hardened SSD
- **Power**: 500 W available for payload
- **ISL**: Starlink laser terminal

### OLCI Instrument Specifications
- **Spectral bands**: 21 (400-1020 nm)
- **Spatial resolution**: 300 m
- **Swath width**: 1270 km
- **Data rate**: 30 Mbps

### Ocean Color Algorithms
- **POLYMER**: Atmospheric correction for turbid/complex waters
- **OC-CCI**: Climate Change Initiative chlorophyll algorithms
- **GHRSST**: Group for High Resolution SST standards

## Value Proposition

Orbital data processing reduces latency from 24+ hours to 6.5 hours while decreasing downlink requirements by 95%. For coral bleaching alerts, this faster turnaround enables earlier intervention, potentially saving reef ecosystems from preventable thermal stress damage.
