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

A cargo vessel transmits a MAYDAY signal in the North Atlantic (52.3degN, 35.7degW). Weather conditions include heavy cloud cover and 40-knot winds, making optical imaging useless. The nearest ground station to Sentinel-1C is 47 minutes away. The Coast Guard needs imagery within 15 minutes.

### Task Flow

```
+--------------+     +-------------+     +---------------------------------+
|    USCG      |---->|  Iridium    |---->|      Starlink ISL Mesh          |
|   MRCC       |     |    180      |     |   (laser crosslinks, 200 Gbps)  |
+--------------+     +-------------+     +---------------+-----------------+
                                                         |
                                                    Close Approach
                                                         |
                                                         v
                                         +-----------------------------+
                                         |      Sentinel-1C            |
                                         |   SAR-C Imaging Radar       |
                                         |   (NORAD 62261)             |
                                         +---------------+-------------+
                                                         |
                                                    Laser ISL
                                                         |
                                                         v
                                         +-----------------------------+
                                         |        EDRS-C               |
                                         |   GEO Data Relay            |
                                         |   (NORAD 44475)             |
                                         +---------------+-------------+
                                                         |
                                                    Ka-band Downlink
                                                         |
                                                         v
                                         +-----------------------------+
                                         |   ESA Redu Ground Station   |
                                         |   --> USCG MRCC             |
                                         +-----------------------------+
```

### Capability Token

The token authorizes Starlink satellites to relay tasking commands to Sentinel-1C for emergency maritime imaging.

```json
{
  "header": {
    "alg": "ES256K",
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
- **Orbit**: 693 km, sun-synchronous, 98.2deg inclination
- **SAR-C band**: 5.405 GHz (C-band)
- **Swath modes**: Strip Map (80km), IW (250km), EW (400km)
- **Resolution**: 5m (IW mode)
- **On-board storage**: 1.4 Tb

### EDRS-C Specifications
- **Orbit**: GEO, 31degE
- **Laser ISL**: 1.8 Gbps bidirectional
- **Coverage**: Europe, Atlantic, Africa
- **Latency**: Near-real-time (< 2 second propagation)

## Value Proposition

Without inter-satellite tasking, the Coast Guard would wait 47 minutes for Sentinel-1C's next ground station pass, then additional time for scheduling and acquisition. The Starlink relay reduces this to 12 minutes total, potentially saving lives in maritime emergencies.

---

## Failure Scenarios

### F1: Capability Token Rejected

**Trigger**: Sentinel-1C rejects the capability token (invalid signature, expired, insufficient capabilities)

**Detection**: Starlink-7823 receives `TOKEN_REJECTED` response during ISL window

**Timeline**:
| Time | Event |
|------|-------|
| T+2:20 | Token verification fails on Sentinel-1C |
| T+2:21 | Rejection reason transmitted to Starlink-7823 |
| T+2:25 | Starlink mesh relays rejection to Iridium 180 |
| T+3:00 | USCG notified of failure with error code |

**Recovery**:
1. Ground operator (ESA) investigates token rejection reason
2. If expired: Issue new token with extended validity
3. If capability mismatch: Escalate to ESA operator for emergency override
4. Retry via next available relay path

**Payment Impact**: HTLC not locked (rejection occurs before payment commitment)

---

### F2: ISL Link Loss During Task Submission

**Trigger**: Starlink-7823 loses ISL contact with Sentinel-1C mid-transmission

**Detection**: Incomplete message receipt, no acknowledgment within timeout

**Timeline**:
| Time | Event |
|------|-------|
| T+2:15 | ISL contact established |
| T+2:18 | Capability token transmission begins |
| T+2:19 | ISL link drops (orbital geometry) |
| T+2:20 | Transmission timeout on Starlink-7823 |
| T+2:25 | Starlink mesh routes to next candidate relay |

**Recovery**:
1. Automatic retry via Starlink-7824 (adjacent in mesh)
2. If Sentinel-1C received partial token: Discard and await complete retransmission
3. New capability token with same `jti` accepted (idempotent)

**Payment Impact**: HTLC not locked (link loss before commitment)

---

### F3: SAR Acquisition Failure

**Trigger**: Sentinel-1C accepts task but SAR acquisition fails (instrument fault, attitude error)

**Detection**: No proof-of-execution generated within expected window

**Timeline**:
| Time | Event |
|------|-------|
| T+2:20 | Task accepted, HTLC locked |
| T+5:00 | SAR acquisition commanded |
| T+5:05 | Instrument reports fault |
| T+5:10 | Sentinel-1C generates `EXECUTION_FAILED` proof |
| T+5:15 | Failure relayed via EDRS-C |
| T+5:30 | USCG receives failure notification |

**Recovery**:
1. `EXECUTION_FAILED` proof triggers automatic dispute
2. HTLC times out, payment refunded to USCG
3. Ground operator investigates instrument fault
4. Alternative satellite tasked if available (Sentinel-1A/B)

**Payment Impact**: Automatic refund via timeout-default dispute

---

### F4: EDRS-C Link Unavailable

**Trigger**: EDRS-C laser terminal unavailable (scheduled maintenance, occultation)

**Detection**: Sentinel-1C cannot establish EDRS link after acquisition

**Timeline**:
| Time | Event |
|------|-------|
| T+7:30 | Acquisition complete |
| T+7:35 | EDRS-C link attempt fails |
| T+7:40 | Fallback: Store data on-board |
| T+47:00 | Data downlinked via ESA Svalbard ground station |
| T+50:00 | Ship-detection products delivered |

**Recovery**:
1. Data stored on-board (1.4 Tb capacity sufficient)
2. Proof-of-execution still generated (data hash available)
3. Delivery delayed but task completed
4. Payment proceeds via timeout-default (proof valid)

**Payment Impact**: Payment settles normally (task completed, proof valid, delivery delay acceptable for maritime SAR)

---

### F5: Proof-of-Execution Invalid

**Trigger**: Sentinel-1C returns proof, but data hash doesn't match delivered data

**Detection**: Ground verification of proof hash vs. received data fails

**Timeline**:
| Time | Event |
|------|-------|
| T+12:00 | Data and proof received |
| T+12:05 | Hash verification fails |
| T+12:10 | USCG initiates dispute |
| T+12:15 | Dispute message broadcast via ground network |
| T+18:00 | Dispute window active, HTLC locked |
| T+24:00 | HTLC timeout expires |
| T+24:01 | Funds returned to USCG |

**Recovery**:
1. Manual investigation of hash mismatch
2. If transmission corruption: Request re-transmission
3. If intentional fraud: Operator reputation impact
4. Alternative data source tasked

**Payment Impact**: Automatic refund via dispute mechanism

---

### F6: Customer Offline During Dispute Window

**Trigger**: USCG ground station offline when proof arrives

**Detection**: Proof delivered but no dispute initiated within window

**Timeline**:
| Time | Event |
|------|-------|
| T+12:00 | Proof relayed to USCG endpoint |
| T+12:01 | USCG endpoint offline (network outage) |
| T+18:00 | Dispute window expires |
| T+18:01 | Payment settles to Sentinel-1C operator |
| T+19:00 | USCG comes online, discovers settlement |

**Recovery**:
1. If data valid: No issue, payment was deserved
2. If data invalid: Out-of-band dispute with ESA operator
3. Reputation/legal mechanisms for fraud cases
4. Operational: Ensure redundant ground monitoring

**Payment Impact**: Payment settles to executor (timeout-default design favors executor)

---

## Failure Mode Summary

| Failure | Detection Point | Payment Outcome | Latency Impact |
|---------|-----------------|-----------------|----------------|
| Token rejected | Before HTLC | No payment | Retry +5 min |
| ISL link loss | Before HTLC | No payment | Retry +10 min |
| Acquisition failure | After HTLC | Refund | Mission abort |
| EDRS unavailable | After acquisition | Payment settles | Delay +35 min |
| Invalid proof | Ground verification | Refund (dispute) | +12 hours |
| Customer offline | Dispute window | Payment settles | N/A |
