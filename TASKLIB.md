# Satellite Tasking Library: Unified Protocol Specification

## Abstract

This document specifies a unified protocol for inter-satellite task authorization and payment. It combines cryptographic capability tokens for command authorization with Bitcoin Lightning Network Hash Time-Locked Contracts (HTLCs) for trustless payment settlement. Satellites execute tasks and settle payments during Inter-Satellite Link (ISL) contact windows without requiring real-time ground station involvement.

---

## 1. Introduction

### 1.1 Problem Statement

Commercial satellite operations require:

1. **Task Authorization**: Satellites must verify commands originate from authorized parties
2. **Cross-Operator Coordination**: Different operators' satellites must collaborate without shared trust infrastructure
3. **Trustless Payment**: Operators should not need to trust each other for payment validity
4. **Intermittent Connectivity**: ISL contact windows of 2-15 minutes during orbital passes
5. **Fair Exchange**: Payment only if task completed; no payment theft

### 1.2 Key Assumptions

**Satellites have sufficient ISL contact time for interactive protocols.**

During a close approach, two LEO satellites have:
- Contact window: 2-15 minutes typical
- ISL latency: 1-50ms depending on distance
- Round trips available: Hundreds to thousands

This is sufficient for:
- Capability token verification (~10ms)
- MuSig2 signing (3 round trips, ~150ms)
- HTLC protocol (10 messages, ~500ms)
- Task execution (variable, seconds to minutes)

### 1.3 Design Goals

| Goal | Description |
|------|-------------|
| **Cryptographic Authorization** | Capability tokens prove permission without real-time ground contact |
| **Trustless Payments** | Payment enforced by Bitcoin script, not third parties |
| **Direct S2S Settlement** | Payments complete during ISL contact, no ground delegation |
| **Atomic Execution** | Task+payment either complete together or refund completely |
| **Multi-Hop Routing** | Tasks and payments can route through satellite constellations |
| **Capability Attenuation** | Delegated authority can only be narrowed, never expanded |

### 1.4 System Overview

```
+-----------------------------------------------------------------------------+
|                         TASKLIB ARCHITECTURE                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|                              PRE-MISSION                                    |
|  +----------------+                              +----------------+         |
|  |  Customer's    |    Capability Token          |   Target's     |         |
|  |  Operator      |  <------------------------>  |   Operator     |         |
|  +-------+--------+    (ground agreement)        +-------+--------+         |
|          |                                               |                  |
|          | Token uploaded                      Operator pubkey              |
|          v                                     burned in at mfg             |
|  +----------------+                              +----------------+         |
|  |   Customer     |                              |    Target      |         |
|  |   Satellite    |                              |   Satellite    |         |
|  |   (Payer)      |                              |   (Executor)   |         |
|  +-------+--------+                              +-------+--------+         |
|          |                                               |                  |
|  ========================================================================   |
|                              ISL CONTACT                                    |
|  ========================================================================   |
|          |                                               |                  |
|          |  1. Lightning channel reestablish             |                  |
|          |<--------------------------------------------->|                  |
|          |                                               |                  |
|          |  2. Task request + capability token           |                  |
|          |  3. Invoice + estimated duration              |                  |
|          |<--------------------------------------------->|                  |
|          |                                               |                  |
|          |  4. HTLC locked (payment_hash H)              |                  |
|          |--------------------------------------------->|                  |
|          |                                               |                  |
|          |             5. Task execution                 |                  |
|          |                    ...                        |                  |
|          |                                               |                  |
|          |  6. Proof of execution                        |                  |
|          |<---------------------------------------------|                  |
|          |                                               |                  |
|          |  7. HTLC fulfilled (preimage R)               |                  |
|          |<---------------------------------------------|                  |
|          |                                               |                  |
|  ========================================================================   |
|                              POST-CONTACT                                   |
|  ========================================================================   |
|          |                                               |                  |
|          |  Ground: On-chain settlement if needed        |                  |
|          |  Ground: Watchtower monitoring                |                  |
|          |                                               |                  |
+-----------------------------------------------------------------------------+
```

---

## 2. Authorization Layer: Capability Tokens

### 2.1 Design Principles

Capability tokens are inspired by UCAN (User Controlled Authorization Networks) and OAuth2 delegation. The target satellite's operator pre-signs authorization tokens that the commanding satellite presents during ISL contact.

**Key Insight**: The target satellite has its operator's public key burned in at manufacturing (for verifying software updates). This enables asymmetric verification: the operator signs tokens offline, and the target verifies them on-orbit.

### 2.2 Capability Token Structure

```
+----------------------------------------------------------------+
|                    CAPABILITY TOKEN (SAT-CAP)                   |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- alg: "ES256" (ECDSA with secp256k1)                      |
|  +-- typ: "SAT-CAP"                                           |
|  +-- enc: "CBOR"           # Compact binary encoding          |
+----------------------------------------------------------------+
|  Payload                                                       |
|  +-- iss: "ESA-COPERNICUS"       # Issuer (target's operator) |
|  +-- sub: "ICEYE-X14-51070"      # Subject (commander sat)    |
|  +-- aud: "SENTINEL-2C-62261"    # Audience (target sat)      |
|  +-- iat: 1705320000             # Issued at (Unix timestamp) |
|  +-- nbf: 1705320000             # Not valid before           |
|  +-- exp: 1705406400             # Expiration (24-48 hr)      |
|  +-- jti: "cap-2025-001-abc"     # Unique token ID (nonce)    |
|  |                                                             |
|  +-- cap: [                      # Capabilities granted       |
|  |     "cmd:imaging:msi",        # Command satellite's MSI    |
|  |     "cmd:attitude:point",     # Adjust pointing            |
|  |     "data:receive:msi_l1b"    # Receive MSI L1B data       |
|  |   ]                                                        |
|  |                                                             |
|  +-- cns: {                      # Constraints                |
|  |     "max_range_km": 100,      # Proximity requirement      |
|  |     "geographic_bounds": {    # AOI restriction            |
|  |       "type": "Polygon",                                   |
|  |       "coordinates": [...]                                 |
|  |     },                                                     |
|  |     "max_tasks": 10,          # Rate limiting              |
|  |     "max_delegation_depth": 2 # Chaining limit             |
|  |   }                                                        |
|  |                                                             |
|  +-- cmd_pub: "02a1b2c3d4..."    # Commander's secp256k1 key  |
|  |                                                             |
|  +-- pmt: {                      # Payment terms              |
|        "currency": "BTC",                                     |
|        "channel_id": "abc123...",# Lightning channel          |
|        "rate_sats_per_km2": 100, # Pricing                    |
|        "max_amount_sats": 50000  # Budget cap                 |
|      }                                                        |
+----------------------------------------------------------------+
|  Signature                                                     |
|  +-- ECDSA signature by operator's private key                |
+----------------------------------------------------------------+
```

### 2.3 Capability Types

| Category | Capability | Description |
|----------|------------|-------------|
| **Imaging** | `cmd:imaging:*` | All imaging commands |
| | `cmd:imaging:msi` | Multispectral imager |
| | `cmd:imaging:sar:spotlight` | SAR spotlight mode |
| **Attitude** | `cmd:attitude:point` | Repoint satellite |
| | `cmd:attitude:track` | Track ground target |
| **Data** | `data:receive:<source>` | Receive data from source |
| | `data:relay:<dest>` | Relay data toward destination |
| | `data:process:<algo>` | Apply processing algorithm |
| **RPO** | `cmd:rpo:approach` | Proximity approach |
| | `cmd:rpo:inspect` | Visual/LIDAR inspection |
| | `cmd:rpo:dock` | Docking operation |
| **Auction** | `task:bid:*` | Bid on any task type |
| | `task:execute:imaging` | Execute imaging tasks |

### 2.4 Constraint Schema

```json
{
  "cns": {
    "proximity": {
      "max_range_km": 100,
      "min_range_m": 30,
      "max_relative_velocity_m_s": 0.1
    },
    "geographic": {
      "type": "Polygon",
      "coordinates": [[[-180, -40], [180, -40], [180, 40], [-180, 40], [-180, -40]]]
    },
    "temporal": {
      "valid_hours_utc": [6, 18],
      "blackout_periods": []
    },
    "rate_limits": {
      "max_tasks": 10,
      "max_tasks_per_hour": 2,
      "max_data_gb": 50
    },
    "delegation": {
      "max_depth": 3,
      "allowed_delegates": ["STARLINK-*", "IRIDIUM-*"]
    }
  }
}
```

---

## 3. Payment Layer: Lightning HTLCs

### 3.1 Lightning Network Integration

Each satellite runs a lightweight Lightning node. Payment channels are established between satellites that frequently pass each other or between satellites and their operators' ground stations.

```
+-----------------------------------------------------------------------------+
|                    SATELLITE LIGHTNING NETWORK                               |
+-----------------------------------------------------------------------------+
|                                                                             |
|                           SPACE SEGMENT                                     |
|  ========================================================================   |
|                                                                             |
|        +----------+         ISL          +----------+                       |
|        |Satellite |<-------------------->|Satellite |                       |
|        |    A     |  (payment channel)   |    B     |                       |
|        | LN Node  |                      | LN Node  |                       |
|        +----+-----+                      +----+-----+                       |
|             |                                  |                            |
|        +----+-----+                      +----+-----+                       |
|        |Satellite |<----- ISL channel -->|Satellite |                       |
|        |    C     |                      |    D     |                       |
|        +----+-----+                      +----+-----+                       |
|             |                                  |                            |
|  ========================================================================   |
|                          GROUND SEGMENT                                     |
|  ========================================================================   |
|             |                                  |                            |
|        RF Downlink                        RF Downlink                       |
|             |                                  |                            |
|        +----+-----+                      +----+-----+                       |
|        | Ground   |<---- Lightning ----->| Ground   |                       |
|        |Station A |      Network         |Station B |                       |
|        | LN Node  |                      | LN Node  |                       |
|        +----+-----+                      +----+-----+                       |
|             |                                  |                            |
|             +----------> Bitcoin <-------------+                            |
|                         Blockchain                                          |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 3.2 HTLC Mechanics

An HTLC (Hash Time-Locked Contract) is a conditional payment:

```
HTLC Script:
-------------
IF
    # Success path: recipient claims with preimage
    <recipient_pubkey> CHECKSIG
    HASH256 <payment_hash> EQUAL
ELSE
    # Refund path: sender reclaims after timeout
    <sender_pubkey> CHECKSIG
    <timeout> CHECKLOCKTIMEVERIFY
ENDIF
```

**Properties**:
- Recipient can claim funds by revealing preimage $R$ where $H = \text{SHA256}(R)$
- If recipient doesn't claim, sender gets refund after timeout
- Atomic: payment either completes or refunds, no intermediate state

### 3.3 Channel Types

| Channel Type | Purpose | Settlement |
|--------------|---------|------------|
| **S2S Direct** | Payment between frequently-passing satellites | ISL contact |
| **S2S Routed** | Payment via constellation mesh | Multi-hop HTLC |
| **S2G** | Satellite to ground station | Ground contact |
| **G2G** | Cross-operator settlement | Standard Lightning |

### 3.4 Timing Budget

```
+-----------------------------------------------------------------------------+
|                    ISL CONTACT TIMING BUDGET                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Scenario: LEO satellites, 5-minute ISL window, 20ms RTT                    |
|                                                                             |
|  Protocol Phase              Messages    RTTs    Time (worst case)          |
|  -----------------------------------------------------------------          |
|  Connection establishment         4        2          40ms                  |
|  Channel reestablish              4        2          40ms                  |
|  Task request + token verify      2        1          20ms                  |
|  Invoice exchange                 2        1          20ms                  |
|  HTLC addition (BOLT 2)           5        5         100ms                  |
|  Task execution              (variable)    -     1-60 seconds               |
|  Proof of execution               2        1          20ms                  |
|  HTLC fulfillment                 5        5         100ms                  |
|  -----------------------------------------------------------------          |
|  Total protocol overhead:                           ~340ms                  |
|  Available for task execution:                    4+ minutes                |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 4. Unified Task-Payment Protocol

### 4.1 Task Request Message

The commanding satellite sends a task request that includes both authorization and payment setup:

```
+----------------------------------------------------------------+
|                    TASK REQUEST MESSAGE                         |
+----------------------------------------------------------------+
|  CCSDS Primary Header (6 bytes)                                |
|  +-- Version: 000                                              |
|  +-- Type: 1 (TC)                                              |
|  +-- APID: Target's ISL task APID                             |
|  +-- Sequence Count                                            |
+----------------------------------------------------------------+
|  Task Header                                                   |
|  +-- message_type: "task_request"                             |
|  +-- task_id: "IMG-2025-001-ICEYE"                            |
|  +-- timestamp: 1705320000                                     |
+----------------------------------------------------------------+
|  Authorization                                                 |
|  +-- capability_token: <CBOR-encoded SAT-CAP>                 |
|  +-- commander_signature: ECDSA(cmd_privkey, task_header)     |
+----------------------------------------------------------------+
|  Task Specification                                            |
|  +-- task_type: "imaging"                                     |
|  +-- target: {                                                |
|  |     "type": "Polygon",                                     |
|  |     "coordinates": [[[139, 35], [145, 35], ...]]          |
|  |   }                                                        |
|  +-- parameters: {                                            |
|  |     "sensor": "MSI",                                       |
|  |     "resolution_m": 10,                                    |
|  |     "bands": ["B02", "B03", "B04", "B08"]                  |
|  |   }                                                        |
|  +-- constraints: {                                           |
|        "cloud_cover_max_pct": 20,                             |
|        "sun_elevation_min_deg": 30                            |
|      }                                                        |
+----------------------------------------------------------------+
|  Payment Offer                                                 |
|  +-- max_amount_sats: 25000                                   |
|  +-- timeout_blocks: 144                                       |
+----------------------------------------------------------------+
|  Frame Check (CRC-16)                                          |
+----------------------------------------------------------------+
```

### 4.2 Task Accept + Invoice

The target satellite validates authorization and responds with an invoice:

```
+----------------------------------------------------------------+
|                    TASK ACCEPT MESSAGE                          |
+----------------------------------------------------------------+
|  Task Header                                                   |
|  +-- message_type: "task_accept"                              |
|  +-- task_id: "IMG-2025-001-ICEYE"                            |
|  +-- timestamp: 1705320001                                     |
|  +-- in_reply_to: <task_request_hash>                         |
+----------------------------------------------------------------+
|  Execution Plan                                                |
|  +-- estimated_duration_sec: 45                               |
|  +-- earliest_start: 1705320005                               |
|  +-- data_volume_mb: 250                                      |
|  +-- quality_estimate: 0.92                                   |
+----------------------------------------------------------------+
|  Lightning Invoice (BOLT 11)                                   |
|  +-- payment_hash: $H = \text{SHA256}(R)$                     |
|  +-- amount_sats: 22000                                        |
|  +-- description: "IMG-2025-001-ICEYE"                        |
|  +-- expiry_sec: 3600                                          |
|  +-- route_hints: [...]                                        |
+----------------------------------------------------------------+
|  Executor Signature                                            |
|  +-- ECDSA(executor_privkey, message)                         |
+----------------------------------------------------------------+
```

### 4.3 Complete Protocol Flow

```
+-----------------------------------------------------------------------------+
|                    TASK-PAYMENT PROTOCOL                                     |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Satellite A (Customer/Payer)              Satellite B (Executor/Payee)     |
|                                                                             |
|  ISL CONTACT ESTABLISHED:                                                   |
|  ========================                                                   |
|                                                                             |
|       |<--------------- ISL Link Up ----------------------->|               |
|       |                                                     |               |
|       |<-> channel_reestablish (BOLT 2) ------------------->|               |
|       |                                                     |               |
|                                                                             |
|  PHASE 1: AUTHORIZATION + NEGOTIATION                                       |
|  ------------------------------------                                       |
|       |                                                     |               |
|       |--- task_request ----------------------------------->|               |
|       |    * capability_token (proves authorization)        |               |
|       |    * task_specification                             |               |
|       |    * payment_offer                                  |               |
|       |    * commander_signature                            |               |
|       |                                                     |               |
|       |         +-------------------------------------------+               |
|       |         | Verify:                                   |               |
|       |         | 1. Token signature (operator pubkey)      |               |
|       |         | 2. Token not expired                      |               |
|       |         | 3. aud == self                            |               |
|       |         | 4. jti not replayed                       |               |
|       |         | 5. Command in cap[]                       |               |
|       |         | 6. Commander signature (cmd_pub)          |               |
|       |         | 7. Constraints satisfied                  |               |
|       |         +-------------------------------------------+               |
|       |                                                     |               |
|       |<-- task_accept + invoice ---------------------------|               |
|       |    * execution_plan                                 |               |
|       |    * invoice (payment_hash H)                       |               |
|       |    * executor_signature                             |               |
|       |                                                     |               |
|                                                                             |
|  PHASE 2: PAYMENT LOCK (HTLC)                                               |
|  ----------------------------                                               |
|       |                                                     |               |
|       |--- update_add_htlc (hash=H, amount=22000) --------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|       |                                                     |               |
|  Payment is now LOCKED. B can claim by revealing preimage R.                |
|  A cannot revoke. Either B claims or timeout refunds A.                     |
|                                                                             |
|                                                                             |
|  PHASE 3: TASK EXECUTION                                                    |
|  -----------------------                                                    |
|       |                                                     |               |
|       |                          Satellite B executes task: |               |
|       |                          * Slew to target           |               |
|       |                          * Configure instrument     |               |
|       |                          * Acquire data             |               |
|       |                          * Process if required      |               |
|       |                                                     |               |
|       |<-- task_progress (optional) ------------------------|               |
|       |                                                     |               |
|                                                                             |
|  PHASE 4: PROOF OF EXECUTION                                                |
|  ---------------------------                                                |
|       |                                                     |               |
|       |<-- proof_of_execution ------------------------------|               |
|       |    * task_id                                        |               |
|       |    * parameters_as_executed                         |               |
|       |    * product_hash: SHA256(data)                     |               |
|       |    * thumbnail (optional)                           |               |
|       |    * executor_signature                             |               |
|       |                                                     |               |
|       |    [A verifies proof meets requirements]            |               |
|       |                                                     |               |
|                                                                             |
|  PHASE 5: PAYMENT SETTLEMENT                                                |
|  ---------------------------                                                |
|       |                                                     |               |
|       |<-- update_fulfill_htlc (preimage=R) ----------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|       |                                                     |               |
|  Payment COMPLETE. A has preimage R as receipt.                             |
|  B's channel balance increased by 22000 sats.                               |
|                                                                             |
|  OPTIONAL: DATA DELIVERY                                                    |
|  -----------------------                                                    |
|       |                                                     |               |
|       |<-- data_transfer (if data fits in ISL window) ------|               |
|       |    OR                                               |               |
|       |<-- data_pointer (relay via Starlink/ground) --------|               |
|       |                                                     |               |
|       |<--------------- ISL Link Down --------------------->|               |
|                                                                             |
|  TOTAL TIME: ~1-5 minutes depending on task                                 |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 4.4 Proof of Execution

```
+----------------------------------------------------------------+
|                    PROOF OF EXECUTION                           |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- task_id: "IMG-2025-001-ICEYE"                            |
|  +-- executor: "SENTINEL-2C-62261"                            |
|  +-- execution_time: "2025-01-15T14:30:00Z"                   |
|  +-- proof_type: "imaging"                                     |
+----------------------------------------------------------------+
|  Execution Summary                                             |
|  +-- status: "completed"                                       |
|  +-- parameters_as_executed: {                                 |
|  |     "center_lat": 38.5,                                     |
|  |     "center_lon": 142.1,                                    |
|  |     "off_nadir_deg": 8.2,                                   |
|  |     "cloud_cover_pct": 12,                                  |
|  |     "gsd_m": 10.2                                           |
|  |   }                                                         |
|  +-- deviations_from_request: []                               |
+----------------------------------------------------------------+
|  Cryptographic Proof                                           |
|  +-- product_hash: "sha256:a1b2c3d4e5f6..."                   |
|  +-- metadata_hash: "sha256:1a2b3c4d5e6f..."                   |
|  +-- thumbnail_hash: "sha256:f6e5d4c3b2a1..."                  |
|  +-- merkle_root: "sha256:abcd1234..."                         |
+----------------------------------------------------------------+
|  Data Delivery                                                 |
|  +-- delivery_method: "isl_direct" | "starlink_relay" | "gs"  |
|  +-- data_size_bytes: 262144000                               |
|  +-- delivery_eta: "2025-01-15T15:00:00Z"                     |
+----------------------------------------------------------------+
|  Executor Signature                                            |
|  +-- ECDSA signature over all above fields                     |
+----------------------------------------------------------------+
```

---

## 5. Multi-Hop Delegation and Payment

### 5.1 Delegation Chain

When tasks must route through multiple satellites, each hop creates a delegation token:

```
+-----------------------------------------------------------------------------+
|                    MULTI-HOP TASK DELEGATION                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Customer                                                                   |
|     |                                                                       |
|     |  Root token from Target's operator                                    |
|     v                                                                       |
|  +---------+                                                                |
|  | Sat A   |  Has: root_token (iss=ESA, sub=A, aud=Target)                 |
|  |(Iridium)|  Creates: del_1 (iss=A, sub=B, aud=Target)                    |
|  +----+----+                                                                |
|       |                                                                     |
|       |  ISL: task_request + del_1 + chain=[root_token]                    |
|       v                                                                     |
|  +---------+                                                                |
|  | Sat B   |  Verifies: del_1 signed by A, caps subset root, exp <= root     |
|  |(Iridium)|  Creates: del_2 (iss=B, sub=C, aud=Target)                    |
|  +----+----+                                                                |
|       |                                                                     |
|       |  ISL: task_request + del_2 + chain=[root_token, del_1]             |
|       v                                                                     |
|  +---------+                                                                |
|  | Sat C   |  Verifies entire chain back to root                           |
|  |(Target) |  Executes task if chain valid                                 |
|  +---------+                                                                |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 5.2 Delegation Token Structure

```
+----------------------------------------------------------------+
|                    DELEGATION TOKEN (SAT-CAP-DEL)               |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- alg: "ES256"                                              |
|  +-- typ: "SAT-CAP-DEL"                                        |
|  +-- chn: 2                      # Chain depth (0 = root)      |
+----------------------------------------------------------------+
|  Payload                                                       |
|  +-- iss: "IRIDIUM-168"          # Delegating satellite        |
|  +-- sub: "IRIDIUM-172"          # Delegate (next hop)         |
|  +-- aud: "SENTINEL-2C"          # Final target (unchanged)    |
|  +-- root_iss: "ESA-COPERNICUS"  # Original token issuer       |
|  +-- root_jti: "cap-001"         # Original token ID           |
|  +-- parent_jti: "del-001"       # Parent delegation ID        |
|  +-- iat: 1705330805                                           |
|  +-- exp: 1705334400             # Must be <= parent exp       |
|  +-- jti: "del-002"              # This delegation's ID        |
|  +-- cap: [...]                  # Must be subset of parent    |
|  +-- cns: {...}                  # Must be >= restrictive      |
|  +-- del_pub: "02d5e6..."        # Delegate's public key       |
+----------------------------------------------------------------+
|  Delegation Chain (reference or full tokens)                   |
|  +-- chain: [<root_jti>, <del_1_jti>]  # Compact form          |
+----------------------------------------------------------------+
|  Signature                                                     |
|  +-- ECDSA signature by delegating satellite's private key    |
+----------------------------------------------------------------+
```

### 5.3 Delegation Rules

1. **Capability Attenuation**: Child can only have $\subseteq$ parent capabilities
2. **Constraint Tightening**: Child constraints must be $\geq$ restrictive
3. **Expiration Inheritance**: Child expiration must be $\leq$ parent
4. **Maximum Depth**: Root token specifies `max_delegation_depth`

### 5.4 Multi-Hop Payment

Payments route through the same path using standard Lightning onion routing:

```
+-----------------------------------------------------------------------------+
|                    MULTI-HOP PAYMENT ROUTING                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Sat A              Sat B (Router)        Sat C (Router)        Sat D       |
|  (Payer)                                                        (Payee)     |
|    |                    |                    |                    |         |
|    |<-- ISL ----------->|<-- ISL ---------->|<-- ISL ----------->|         |
|    |   Channel 1        |   Channel 2       |   Channel 3        |         |
|    |                    |                    |                    |         |
|                                                                             |
|  Payment: A pays D 10,000 sats via B, C                                     |
|  Routing fees: B takes 50 sats, C takes 50 sats                             |
|                                                                             |
|  HTLC Chain (same payment_hash H throughout):                               |
|  ----------------------------------------------                             |
|    |                    |                    |                    |         |
|    |- HTLC 10,100 sats >|                    |                    |         |
|    |  timeout: T        |- HTLC 10,050 sats >|                    |         |
|    |                    |  timeout: T-144    |- HTLC 10,000 sats >|         |
|    |                    |                    |  timeout: T-288    |         |
|    |                    |                    |                    |         |
|    |                    |                    |<-- preimage R -----|         |
|    |                    |<-- preimage R -----|                    |         |
|    |<-- preimage R -----|                    |                    |         |
|    |                    |                    |                    |         |
|                                                                             |
|  Decreasing timeouts ensure D claims first, then C, B, A                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 6. Fair Exchange and Arbiter

### 6.1 The Problem

Task-for-payment is a fair exchange problem:
- A wants to pay only if task is completed correctly
- B wants payment assurance before executing task

**Cryptography cannot solve this.** We need minimal trust.

### 6.2 Trust-Minimized Arbiter

```
+-----------------------------------------------------------------------------+
|                    ARBITER TRUST MODEL                                       |
+-----------------------------------------------------------------------------+
|                                                                             |
|  What the arbiter CANNOT do:                                                |
|  ---------------------------                                                |
|  * Steal funds (doesn't hold keys or preimages)                             |
|  * Create fake payments                                                     |
|  * Forge task completion                                                    |
|  * Prevent eventual settlement (HTLC timeout guarantees refund)             |
|                                                                             |
|  What the arbiter CAN do:                                                   |
|  ------------------------                                                   |
|  * Delay payment release                                                    |
|  * Wrongly approve incomplete task (B gets paid unfairly)                   |
|  * Wrongly reject complete task (B not paid, but A refunded)                |
|                                                                             |
|  Trust is limited to JUDGMENT, not CUSTODY.                                 |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 6.3 Settlement Options

**Option 1: Immediate Settlement (No Arbiter)**
- B completes task during ISL window
- A verifies completion directly
- B reveals preimage, payment settles
- Works for: Simple tasks, trusted relationships, low value

**Option 2: Deferred Settlement with Arbiter**
- HTLC locked during ISL contact
- B executes task, sends proof to arbiter
- Arbiter verifies and signals approval
- B reveals preimage on next ISL contact

**Option 3: Timeout-Based Default**
- B submits completion proof
- If no dispute within X hours: auto-approve
- A must actively dispute to block payment

---

## 7. Distributed Task Allocation (CBBA)

### 7.1 Auction-Based Task Distribution

For constellation-wide task distribution, satellites use the Consensus-Based Bundle Algorithm:

```
+-----------------------------------------------------------------------------+
|                    CBBA DISTRIBUTED AUCTION                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  PHASE 1: BUNDLE BUILDING (Local)                                           |
|  -------------------------------                                            |
|  Each satellite greedily builds a task bundle:                              |
|                                                                             |
|    SAT-1: "Task A costs me 10 units, Task C costs 15"                       |
|    SAT-2: "Task A costs me 8 units, Task B costs 12"                        |
|    SAT-3: "Task B costs me 6 units, Task C costs 20"                        |
|                                                                             |
|                                                                             |
|  PHASE 2: CONSENSUS (Distributed)                                           |
|  --------------------------------                                           |
|  Satellites exchange bids with ISL neighbors:                               |
|                                                                             |
|    SAT-1 -> SAT-2: "I bid 10 for Task A"                                     |
|    SAT-2 -> SAT-1: "I bid 8 for Task A"  <- Lower cost wins                   |
|                                                                             |
|    SAT-1: "OK, you take A. I'll rebid on B or C."                           |
|                                                                             |
|                                                                             |
|  ITERATION: Repeat until no conflicts remain                                |
|                                                                             |
|                                                                             |
|  Properties:                                                                |
|  * Converges to conflict-free assignment                                    |
|  * Polynomial-time algorithm                                                |
|  * Tolerates partial communication graphs                                   |
|  * Decentralized execution with local information only                      |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 7.2 Auction Bid Structure

```
+----------------------------------------------------------------+
|                    CROSS-OPERATOR AUCTION BID                   |
+----------------------------------------------------------------+
|  Bid Header                                                    |
|  +-- bidder_id: "ICEYE-X14-51070"                             |
|  +-- task_id: "CHARTER-2025-JAP-IMG-001"                      |
|  +-- bid_value: 8.5              # Lower is better            |
|  +-- timestamp: 1705312800                                     |
+----------------------------------------------------------------+
|  Authorization                                                 |
|  +-- capability_token: <SAT-CAP>                              |
|  |     +-- cap: ["task:bid:imaging", "task:execute:imaging"]  |
|  +-- bidder_signature: ECDSA(...)                             |
+----------------------------------------------------------------+
|  Cost Breakdown                                                |
|  +-- fuel_kg: 0.02                                            |
|  +-- time_sec: 45                                             |
|  +-- opportunity_cost: 3.2                                    |
|  +-- capability_match: 0.95                                   |
+----------------------------------------------------------------+
|  Execution Details                                             |
|  +-- earliest_execution: "2025-01-15T07:30:00Z"              |
|  +-- data_latency_hours: 1.5                                  |
|  +-- coverage_km2: 30000                                       |
+----------------------------------------------------------------+
```

### 7.3 Bid Value Semantics

The bid value encodes **cost to execute**, not willingness to pay:

```python
def compute_bid(satellite: Satellite, task: Task) -> float:
    """Lower bid = better suited to execute task"""

    # Fuel cost to slew and maneuver
    fuel_cost = estimate_fuel(satellite.position, task.target)

    # Time until satellite can begin
    time_cost = compute_access_window(satellite.orbit, task.target)

    # Opportunity cost (other tasks displaced)
    opportunity_cost = evaluate_queue_impact(satellite.task_queue, task)

    # Capability mismatch penalty
    capability_penalty = 1.0 / sensor_match(satellite.sensors, task.requirements)

    return fuel_cost + time_cost + opportunity_cost + capability_penalty
```

---

## 8. Ground Station Role

Ground stations handle on-chain settlement and watchtower functions, but do NOT participate in space-segment payment flows.

### 8.1 Functions

```
+-----------------------------------------------------------------------------+
|                    GROUND STATION FUNCTIONS                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. CHANNEL FUNDING                                                         |
|  * Satellite requests channel open with another satellite                   |
|  * Funding transaction created (2-of-2 MuSig2)                              |
|  * Ground station broadcasts funding tx to Bitcoin network                  |
|  * Monitors for confirmations                                               |
|                                                                             |
|  2. COOPERATIVE CLOSE                                                       |
|  * Satellites agree to close channel (during ISL contact)                   |
|  * Create and sign closing transaction                                      |
|  * Ground station broadcasts closing tx                                     |
|                                                                             |
|  3. FORCE CLOSE                                                             |
|  * Satellite cannot reach counterparty                                      |
|  * Satellite sends commitment tx to ground station                          |
|  * Ground station broadcasts and monitors                                   |
|                                                                             |
|  4. WATCHTOWER                                                              |
|  * Monitor for cheating attempts (old commitment broadcasts)                |
|  * Broadcast penalty transactions if needed                                 |
|  * Monitor HTLC timeouts                                                    |
|                                                                             |
|  TRUST MODEL:                                                               |
|  * Ground station operated by satellite's own operator                      |
|  * Cannot steal funds (doesn't have satellite's keys)                       |
|  * Can only delay or fail to broadcast                                      |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 9. Emergency Authorization

### 9.1 Emergency Capability Class

```json
{
  "typ": "SAT-CAP-EMERG",
  "emergency_class": "CHARTER_ACTIVATION",
  "priority": "IMMEDIATE",
  "cap": [
    "cmd:imaging:*",
    "cmd:attitude:point",
    "data:relay:any"
  ],
  "cns": {
    "emergency_types": ["earthquake", "tsunami", "volcanic", "flood"],
    "geographic_bounds": "CHARTER_AOI",
    "max_tasks_per_activation": 10,
    "audit_required": true
  },
  "activation": {
    "activation_id": "CHARTER-2025-JAP-001",
    "activated_by": "UN-SPIDER",
    "activation_time": "2025-01-15T06:15:00Z"
  }
}
```

### 9.2 Authorization Levels

| Level | Authorization | Use Case | Audit |
|-------|---------------|----------|-------|
| **Pre-Authorized** | Standing tokens to responders | International Charter, SAR | Optional |
| **Rapid Approval** | Expedited issuance (minutes) | Government agencies | Required |
| **Act-First** | Execute, authorize later | Collision avoidance, life safety | Mandatory |

---

## 10. Security Analysis

### 10.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| **Unauthorized command** | Capability token verification |
| **Replay attack** | Token ID (jti) in used-token cache |
| **Man-in-the-middle** | ECDSA signatures on all messages |
| **Payment theft** | HTLC timeout guarantees refund |
| **Old state broadcast** | Watchtower penalty transactions |
| **Clock manipulation** | GPS-disciplined clocks, tolerant windows |

### 10.2 Cryptographic Properties

| Property | Mechanism |
|----------|-----------|
| **Authentication** | Operator signature on token; commander signature on command |
| **Authorization** | Explicit capability list in token |
| **Integrity** | ECDSA signatures over all data |
| **Freshness** | Timestamps, expiration, nonces |
| **Non-repudiation** | Payment preimage serves as receipt |
| **Atomicity** | HTLC: either complete or timeout refund |

---

## 11. Implementation

### 11.1 Core Data Structures

```python
@dataclass
class CapabilityToken:
    issuer: str                    # Target's operator ID
    subject: str                   # Commanding satellite ID
    audience: str                  # Target satellite ID
    issued_at: int                 # Unix timestamp
    expires_at: int
    token_id: str                  # Unique nonce (jti)
    capabilities: list[str]        # Permitted operations
    constraints: dict              # Range, region, rate limits
    commander_pubkey: bytes        # secp256k1 public key
    payment_terms: dict | None     # Lightning channel, rates
    signature: bytes               # Operator's ECDSA signature

@dataclass
class TaskRequest:
    task_id: str
    capability_token: CapabilityToken
    task_type: str
    target: dict                   # GeoJSON
    parameters: dict
    constraints: dict
    payment_offer: dict
    commander_signature: bytes

@dataclass
class TaskAccept:
    task_id: str
    execution_plan: dict
    invoice: LightningInvoice      # BOLT 11
    executor_signature: bytes

@dataclass
class ProofOfExecution:
    task_id: str
    executor: str
    execution_time: int
    parameters_as_executed: dict
    product_hash: bytes            # SHA256 of output
    delivery_info: dict
    executor_signature: bytes

@dataclass
class DelegationToken:
    header: dict                   # typ, alg, chn
    issuer: str                    # Delegating satellite
    subject: str                   # Delegate
    audience: str                  # Final target
    root_issuer: str
    root_jti: str
    parent_jti: str
    issued_at: int
    expires_at: int
    token_id: str
    capabilities: list[str]        # subset of parent
    constraints: dict              # >= restrictive
    delegate_pubkey: bytes
    chain: list[str]               # Parent token IDs
    signature: bytes
```

### 11.2 Verification Functions

```python
def verify_capability_token(token: CapabilityToken,
                            target: Satellite) -> bool:
    """Verify single-hop capability token"""

    # 1. Verify signature by operator
    if not verify_ecdsa(token, target.operator_pubkey):
        return False

    # 2. Check audience matches target
    if token.audience != target.id:
        return False

    # 3. Check not expired
    if token.expires_at < now():
        return False

    # 4. Check not replayed
    if token.token_id in target.used_tokens:
        return False
    target.used_tokens.add(token.token_id)

    return True

def verify_delegation_chain(token: DelegationToken,
                            chain: list[CapabilityToken | DelegationToken],
                            target: Satellite) -> bool:
    """Verify complete delegation chain"""

    full_chain = chain + [token]

    # 1. Verify root is from target's operator
    root = full_chain[0]
    if not verify_ecdsa(root, target.operator_pubkey):
        return False
    if root.audience != target.id:
        return False

    # 2. Walk chain verifying each delegation
    for i in range(1, len(full_chain)):
        parent = full_chain[i-1]
        child = full_chain[i]

        # Verify parent signed child
        parent_pubkey = parent.commander_pubkey if i == 1 else parent.delegate_pubkey
        if not verify_ecdsa(child, parent_pubkey):
            return False

        # Verify capability attenuation
        if not is_subset(child.capabilities, parent.capabilities):
            return False

        # Verify expiration inheritance
        if child.expires_at > parent.expires_at:
            return False

    return True
```

### 11.3 Satellite Node Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **CPU** | ARM Cortex-A class | ECDSA, SHA256 |
| **RAM** | 64 MB minimum | Channel state, token cache |
| **Storage** | 10 MB | Channels, used jti cache |
| **RNG** | Hardware TRNG | Key/nonce generation |
| **Clock** | GPS-disciplined | HTLC timeouts |

---

## 12. PTLC Future Enhancement

When Point Time-Locked Contracts become available in Lightning Network, task execution can be cryptographically bound to payment:

```
+-----------------------------------------------------------------------------+
|                    PTLC TASK-PAYMENT BINDING                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Setup:                                                                     |
|  * A wants B to execute task T with expected output O                       |
|  * Adaptor point: P = Hash-to-Curve(task_id || B_pubkey)                   |
|  * Adaptor secret: s = B's signature on output_hash                        |
|                                                                             |
|  Protocol:                                                                  |
|  1. A creates PTLC locked to point P                                        |
|  2. B executes task, produces output O                                      |
|  3. B computes output_hash = SHA256(O)                                      |
|  4. B signs: sig_B = Sign(B_privkey, output_hash)                          |
|  5. sig_B IS the adaptor secret that unlocks PTLC                          |
|  6. Payment completes; A receives sig_B as cryptographic proof             |
|                                                                             |
|  Properties:                                                                |
|  * B cannot claim without producing signed output                           |
|  * A receives cryptographic proof of task completion                        |
|  * No separate preimage management                                          |
|  * Proof and payment are atomic                                             |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Implementation Status**:
- Schnorr (BIP 340): Complete
- MuSig2 (BIP 327): Complete
- Taproot channels: Experimental (LND v0.17+)
- PTLC in Lightning: Research phase

**Timeline**: PTLCs in production Lightning estimated 2-4 years.

---

## 13. References

### Standards
- CCSDS 133.0-B-2 Space Packet Protocol
- CCSDS 355.0-B-2 Space Data Link Security
- ECSS-E-ST-70-41C Packet Utilization Standard

### Lightning Network
- [BOLT 2: Peer Protocol](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md)
- [BOLT 3: Transactions](https://github.com/lightning/bolts/blob/master/03-transactions.md)
- [BOLT 4: Onion Routing](https://github.com/lightning/bolts/blob/master/04-onion-routing.md)
- [BOLT 11: Invoice Protocol](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md)

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/)
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)

### Academic
- Choi et al., "Consensus-Based Decentralized Auctions for Robust Task Allocation" (MIT)
- UCAN Specification: https://ucan.xyz/
