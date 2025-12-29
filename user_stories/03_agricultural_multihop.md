# User Story 03: Agricultural Monitoring via Multi-Hop Relay

## Summary

A precision agriculture company in rural Argentina needs multispectral imagery for crop health assessment. The task is relayed through multiple satellites due to the target satellite's position over the South Atlantic, far from ground stations.

## Actors

| Role | Entity | NORAD ID |
|------|--------|----------|
| **Customer** | AgriTech Solutions (Buenos Aires) | - |
| **Ground Station** | AWS Ground Station, Cape Town | - |
| **Relay Hop 1** | Iridium 168 | 56728 |
| **Relay Hop 2** | Iridium 172 | 56732 |
| **Target Satellite** | Sentinel-2C | 60989 |
| **Instrument** | MSI (Multi-Spectral Instrument) | - |
| **Data Relay** | Starlink mesh | Various |
| **Data Processing** | LeoLabs Orbital Data Center | - |

## Scenario

### Context

AgriTech Solutions monitors 50,000 hectares of soybean fields in the Pampas region. They need:
- NDVI vegetation index for crop stress detection
- Red-edge bands for chlorophyll estimation
- NIR bands for water stress assessment

Sentinel-2C is currently over the South Atlantic with no direct ground station access for 35 minutes.

### Multi-Hop Task Relay

```
+--------------+     +-------------+     +-------------+
|   AgriTech   |---->| AWS GS      |---->|  Iridium    |
|   Buenos     |     | Cape Town   |     |    168      |
|   Aires      |     |             |     |  (Hop 1)    |
+--------------+     +-------------+     +------+------+
                                                |
                                           Ka-band ISL
                                                |
                                                v
                                         +-------------+
                                         |  Iridium    |
                                         |    172      |
                                         |  (Hop 2)    |
                                         +------+------+
                                                |
                                         S-band to TT&C
                                         antenna (proximity)
                                                |
                                                v
                                         +---------------------+
                                         |    Sentinel-2C      |
                                         |    MSI Imager       |
                                         |    (NORAD 60989)    |
                                         +----------+----------+
                                                    |
                                              Image acquisition
                                                    |
                                                    v
                                    +------------------------------+
                                    |    Starlink Mesh Relay       |
                                    |    (laser ISL backbone)      |
                                    +--------------+---------------+
                                                   |
                                         +---------+---------+
                                         |                   |
                                         v                   v
                            +-----------------+   +-----------------+
                            | LeoLabs Orbital |   |  AWS Ground     |
                            | Data Center     |   |  Station        |
                            | (processing)    |   |  (backup path)  |
                            +--------+--------+   +-----------------+
                                     |
                               Processed NDVI
                               products
                                     |
                                     v
                            +-----------------+
                            |    AgriTech     |
                            |    Platform     |
                            +-----------------+
```

### Capability Token Chain

Each relay hop requires a delegation token:

**Hop 1 Token (AgriTech -> Iridium 168):**
```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "AGRITECH-SOLUTIONS",
    "sub": "IRIDIUM-168-56728",
    "aud": "IRIDIUM-168-56728",
    "iat": 1705330800,
    "exp": 1705334400,
    "jti": "agri-task-relay-001",
    "cap": [
      "relay:task:forward",
      "relay:data:receive"
    ],
    "cns": {
      "max_hops": 3,
      "final_target": "SENTINEL-2C-60989"
    },
    "delegation_chain": []
  }
}
```

**Hop 2 Token (Iridium 168 -> Iridium 172):**
```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "IRIDIUM-168-56728",
    "sub": "IRIDIUM-172-56732",
    "aud": "IRIDIUM-172-56732",
    "iat": 1705330805,
    "exp": 1705334400,
    "jti": "agri-task-relay-002",
    "cap": [
      "relay:task:forward",
      "cmd:imaging:msi"
    ],
    "cns": {
      "max_hops": 2,
      "final_target": "SENTINEL-2C-60989"
    },
    "delegation_chain": ["AGRITECH-SOLUTIONS"]
  }
}
```

**Final Execution Token (Iridium 172 -> Sentinel-2C):**
```json
{
  "header": { "alg": "ES256K", "typ": "SAT-CAP" },
  "payload": {
    "iss": "ESA-COPERNICUS",
    "sub": "IRIDIUM-RELAY-AUTH",
    "aud": "SENTINEL-2C-60989",
    "iat": 1705320000,
    "exp": 1705406400,
    "jti": "s2c-agri-exec-001",
    "cap": [
      "cmd:imaging:msi:all_bands",
      "cmd:attitude:point",
      "cmd:downlink:starlink"
    ],
    "cns": {
      "max_range_km": 100,
      "authorized_customers": ["AGRITECH-*"],
      "max_area_km2": 100000
    }
  }
}
```

### Imaging Command

```json
{
  "timestamp": "2025-01-15T14:45:30Z",
  "command_type": "cmd:imaging:msi:all_bands",
  "parameters": {
    "target_coords": {
      "type": "Polygon",
      "coordinates": [[
        [-62.5, -34.0], [-61.5, -34.0],
        [-61.5, -33.0], [-62.5, -33.0],
        [-62.5, -34.0]
      ]]
    },
    "bands_requested": [
      "B02", "B03", "B04",
      "B05", "B06", "B07",
      "B08", "B8A",
      "B11", "B12"
    ],
    "resolution_m": 10,
    "processing_level": "L1C",
    "data_routing": {
      "method": "starlink_relay",
      "processing_node": "LEOLABS-ODC-1",
      "products": ["NDVI", "NDRE", "NDWI"],
      "final_destination": "AGRITECH-S3-BUCKET"
    }
  }
}
```

### Data Products and Processing

| Product | Description | Processing Location |
|---------|-------------|---------------------|
| L1C TOA | Top-of-atmosphere reflectance | On-board Sentinel-2C |
| L2A BOA | Bottom-of-atmosphere reflectance | LeoLabs ODC |
| NDVI | $\frac{NIR - Red}{NIR + Red}$ vegetation index | LeoLabs ODC |
| NDRE | $\frac{NIR - RedEdge}{NIR + RedEdge}$ | LeoLabs ODC |
| NDWI | $\frac{Green - NIR}{Green + NIR}$ water index | LeoLabs ODC |
| Crop Stress Map | ML classification | LeoLabs ODC |

### Orbital Data Center Processing

The LeoLabs Orbital Data Center receives raw data via Starlink ISL and performs:

1. **Atmospheric correction** (L1C -> L2A)
2. **Index calculation** (NDVI, NDRE, NDWI)
3. **Crop stress classification** (ML inference)
4. **Compression** (lossless for science, lossy preview)
5. **Routing** to customer cloud bucket

```
Raw Data (800 MB) --> Processing --> Products (150 MB) --> Customer
         |                                    |
    Full spectral cube              Derived indices +
    10m resolution                  classification maps
```

### Timeline

| Time | Event |
|------|-------|
| T+0:00 | AgriTech submits request |
| T+0:15 | Task routed to Iridium 168 |
| T+0:25 | Iridium 168 -> Iridium 172 relay |
| T+0:35 | Iridium 172 proximity pass to Sentinel-2C |
| T+0:40 | Command received and validated |
| T+3:00 | Sentinel-2C over target AOI |
| T+3:12 | Acquisition complete |
| T+3:15 | Starlink ISL link established |
| T+3:25 | Raw data at LeoLabs ODC |
| T+3:45 | Processing complete |
| T+3:50 | Products in AgriTech S3 bucket |

**Total latency: 3 hours 50 minutes** (vs. 6+ hours via traditional ground path)

## Acceptance Criteria

- [ ] Multi-hop relay completes within 1 hour
- [ ] Each hop validates delegation chain
- [ ] Sentinel-2C acquires all 10 requested bands
- [ ] Orbital data center processes within 30 minutes
- [ ] NDVI/NDRE products meet radiometric accuracy requirements

## Technical Notes

### Sentinel-2C MSI Specifications
- **Orbit**: 786 km, sun-synchronous, 98.62deg inclination
- **Spectral bands**: 13 (443nm to 2190nm)
- **Spatial resolution**: 10m (B2,3,4,8), 20m (B5,6,7,8A,11,12), 60m (B1,9,10)
- **Swath width**: 290 km
- **Revisit time**: 5 days (with Sentinel-2A/2B)

### Iridium ISL Characteristics
- **ISL type**: Ka-band RF crosslinks
- **Connectivity**: 4 crosslinks per satellite
- **Latency per hop**: ~10ms
- **Coverage**: Global, including polar regions

### Agricultural Index Formulas
- **NDVI**: $\frac{B08 - B04}{B08 + B04}$
- **NDRE**: $\frac{B08 - B05}{B08 + B05}$
- **NDWI**: $\frac{B03 - B08}{B03 + B08}$

### LeoLabs Orbital Data Center

*Note: The "LeoLabs Orbital Data Center" in this scenario is hypothetical. LeoLabs is a space situational awareness (SSA) company providing satellite tracking and space traffic management services. This user story envisions a future orbital edge computing capability that could be operated by any provider with on-orbit processing infrastructure.*

## Value Proposition

Multi-hop relay enables tasking of satellites in coverage gaps, while orbital processing eliminates ground station downlink bottlenecks. AgriTech receives actionable crop intelligence 2 hours faster than traditional pipelines.
