# SCRAP: Secure Capabilities and Routed Authorization Protocol

## Abstract

This document specifies SCRAP (Secure Capabilities and Routed Authorization Protocol), a unified protocol for autonomous agent task authorization and payment. It combines cryptographic capability tokens for command authorization with Bitcoin Lightning Network payments for trustless settlement. While the primary use case is inter-satellite operations, SCRAP applies to any intermittently-connected autonomous agents: vehicles, drones, IoT devices, AI agents, and remote infrastructure.

**Separation of concerns:**
- **Satellites**: Execute tasks, route data via ISL, verify capability tokens
- **Operators**: Handle all payment logic via Lightning channels (ground-based, always online)

Payment coordination occurs between operators on the ground, not between satellites. This avoids the impossibility of multi-hop Lightning routing over sparse, intermittent ISL connectivity. Satellites execute tasks authorized by capability tokens; operators settle payments atomically using adaptor signatures.

SCRAP complements SISL (Secure Inter-Satellite Link) at the link layer.

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
| **Operator-Level Settlement** | Payments settled via operator Lightning channels (always online) |
| **Atomic Execution** | Task+payment either complete together or refund completely |
| **Multi-Hop Task Routing** | Tasks route through satellite constellations via ISL |
| **Capability Attenuation** | Delegated authority can only be narrowed, never expanded |

### 1.4 Relationship to Existing Standards

SCRAP **layers on top of** existing spacecraft security rather than replacing it:

```
+---------------------------+
|     SCRAP Protocol         |  <- Application-layer: WHO may do WHAT
+---------------------------+
|     CCSDS SDLS            |  <- Link-layer: IS this channel authentic
+---------------------------+
|     Physical (RF/Optical) |
+---------------------------+
```

**CCSDS SDLS** provides link-layer security (authenticated encryption of frames). It answers: "Is this ISL transmission authentic and unmodified?"

**SCRAP** provides application-layer authorization. It answers: "Does this authenticated peer have permission to execute this specific task?"

Current systems cannot support delegation because they rely on symmetric keys—only the key holder can authenticate. SCRAP uses asymmetric signatures: anyone can verify a capability token, but only the operator can issue one. This enables:

- Delegation chains (satellite A authorizes satellite B to command satellite C)
- Capability attenuation (delegate can only narrow permissions, never expand)
- Cross-operator authorization (without sharing secrets)

See [../research/CNC_RESEARCH.md](../research/CNC_RESEARCH.md) §7 "Gap Analysis" for detailed comparison with CCSDS SDLS, commercial APIs, and emerging ISL authentication protocols.

> **Naming**: SCRAP complements the protocol stack: **SISL** (Secure Inter-Satellite Link) at the link layer, **SCRAP** at the payment/authorization layer, and **SAT-CAP** tokens for capability delegation.

### 1.5 System Overview

```
+-----------------------------------------------------------------------------+
|                         SCRAP ARCHITECTURE                                    |
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

### 1.6 Service Discovery and Token Issuance

Service discovery and token issuance occur **before** the on-orbit protocol:

- Operators run internet-accessible **Operator API** endpoints
- Customers authenticate via OAuth2 and request capability tokens
- Tokens are uploaded to commanding satellites during ground contact windows
- On-orbit protocol assumes capability tokens already exist

**Operator API** ([OPERATOR_API.md](OPERATOR_API.md)) specifies:

| Endpoint | Purpose |
|----------|---------|
| `GET /operator` | Operator signing pubkey (trust root) |
| `GET /satellites` | Satellite catalog with identity pubkeys |
| `POST /tokens` | Request signed capability token |
| `GET /tokens/{token_id}` | Token status and revocation |
| `GET /channels` | Lightning channel info for settlement |

This separation keeps the on-orbit protocol simple and deterministic. Satellites verify pre-arranged tokens; they do not participate in service discovery or token issuance.

---

## 2. Authorization Layer: Capability Tokens

### 2.1 Design Principles

Capability tokens are inspired by UCAN (User Controlled Authorization Networks) and OAuth2 delegation. The target satellite's operator pre-signs authorization tokens that the commanding satellite presents during ISL contact.

**Key Insight**: The target satellite has its operator's public key burned in at manufacturing (for verifying software updates). This enables asymmetric verification: the operator signs tokens offline, and the target verifies them on-orbit.

### 2.2 Capability Token Structure

The capability token authorizes a commander to execute specific tasks on a target
satellite. The target's operator signs the token; the target verifies against its
operator's pubkey (burned in at manufacturing).

```
+----------------------------------------------------------------+
|                    CAPABILITY TOKEN (TLV-encoded)               |
+----------------------------------------------------------------+
|  REQUIRED FIELDS                                               |
|  +-- version: 1                  # Protocol version            |
|  +-- issuer: <33-byte pubkey>    # Target's operator (signer)  |
|  +-- subject: <variable>         # Commander (pubkey or ID)    |
|  +-- audience: <variable>        # Target satellite            |
|  +-- issued_at: 1705320000       # Unix timestamp (uint32)     |
|  +-- expires_at: 1705406400      # Expiration (uint32)         |
|  +-- token_id: <16 random bytes> # Unique ID for replay prot.  |
|  +-- capability: "cmd:imaging:msi"    # [MAY repeat]           |
|  +-- capability: "cmd:attitude:point" # Multiple capabilities  |
+----------------------------------------------------------------+
|  OPTIONAL CONSTRAINTS (narrow authorization)                   |
|  +-- constraint_geo: <GeoJSON>   # Geographic bounds           |
|  +-- constraint_rate: [10, 3600] # Max 10 per hour             |
|  +-- constraint_amount: 50000    # Max satoshis                |
|  +-- constraint_after: 1705320000 # Not before this time       |
+----------------------------------------------------------------+
|  DELEGATION FIELDS (if not root token)                         |
|  +-- root_issuer: <33-byte pubkey>  # Original operator        |
|  +-- root_token_id: <16 bytes>      # Root token reference     |
|  +-- parent_token_id: <16 bytes>    # Parent token reference   |
|  +-- chain_depth: 1                 # Depth in chain (root=0)  |
+----------------------------------------------------------------+
|  SIGNATURE (must be last)                                      |
|  +-- signature: <64-byte BIP-340 Schnorr>                      |
+----------------------------------------------------------------+
```

**Trust model:** The target satellite has its operator's pubkey burned in at
manufacturing. When a commander presents a token, the target verifies the
signature against this known pubkey. For delegated tokens, the target verifies
the chain back to its operator.

**Payment terms** are negotiated per-task in the task request/accept flow, not
in the capability token. The token authorizes WHAT may be done; the task request
specifies HOW MUCH to pay.

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

### 2.5 Token ID Generation

The `token_id` field (TLV type 12) provides replay protection and unique identification.
It consists of 16 cryptographically random bytes.

**TLV format (canonical):** 16 random bytes stored as TLV type 12.

**Human-readable format (for logs/APIs):** A string format may be used for debugging.

#### 2.5.1 Binary Format (Canonical)

```python
import secrets

def generate_token_id() -> bytes:
    """Generate unique 16-byte token ID with replay protection."""
    return secrets.token_bytes(16)  # 128 bits of entropy
```

#### 2.5.2 String Format (Logs/APIs)

For debugging and API responses, a human-readable string format may be used:

```
token_id_str = <prefix>-<timestamp>-<hex>

Where:
  prefix    = issuer-specific identifier (1-16 ASCII characters)
  timestamp = Unix timestamp in seconds (decimal, 10 digits)
  hex       = token_id bytes, hex-encoded (32 characters)

Example: "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01"
```

**Total length**: 1-16 + 1 + 10 + 1 + 32 = 45-60 characters

#### 2.5.3 Uniqueness Scope

- **Per-issuer uniqueness**: The `token_id` MUST be unique within a single issuer's token space
- **Global uniqueness**: The combination of `(issuer, token_id)` MUST be globally unique
- **Collision probability**: With 128-bit random component, collision probability is negligible (~2^-64 after 2^64 tokens)

#### 2.5.4 TLV Encoding

Capability tokens use TLV (Type-Length-Value) encoding, following Lightning Network conventions (BOLT 1). This provides a compact binary format with forward compatibility.

**TLV Record Structure:**
```
type:   BigSize (1-9 bytes, typically 1-2)
length: BigSize (1-9 bytes, typically 1-2)
value:  [length] bytes
```

**BigSize Encoding** (BOLT 1):
- 0x00-0xFC: 1 byte (value as-is)
- 0xFD + 2 bytes: values 0xFD-0xFFFF
- 0xFE + 4 bytes: values 0x10000-0xFFFFFFFF
- 0xFF + 8 bytes: larger values

**Token TLV Types:**

| Type | Name | Length | Description |
|------|------|--------|-------------|
| 0 | version | 1 | Protocol version (0x01) |
| 2 | issuer | 33 | Target's operator pubkey (signer, trust root) |
| 4 | subject | var | Commander identifier (who may use this token) |
| 6 | audience | var | Target satellite identifier (who executes) |
| 8 | issued_at | 4 | Unix timestamp (uint32 big-endian) |
| 10 | expires_at | 4 | Unix timestamp (uint32 big-endian) |
| 12 | token_id | 16 | Unique identifier (random bytes) |
| 14 | capability | var | Capability string (UTF-8) [MAY repeat] |
| 240 | signature | 64 | BIP-340 Schnorr signature (MUST be last) |

**Optional Types (odd - ignore if unknown):**

| Type | Name | Length | Description |
|------|------|--------|-------------|
| 1 | flags | 1 | Reserved flags |
| 13 | constraint_geo | var | GeoJSON polygon (UTF-8) |
| 15 | constraint_rate | 8 | [uint32 count, uint32 period_sec] |
| 17 | constraint_amount | 8 | Satoshi limit (uint64 big-endian) |
| 19 | constraint_after | 4 | Not-before timestamp (uint32) |

**Delegation Types (for non-root tokens):**

| Type | Name | Length | Description |
|------|------|--------|-------------|
| 20 | root_issuer | 33 | Target's operator pubkey (for chain verification) |
| 22 | root_token_id | 16 | Root token's token_id (issued by operator) |
| 24 | parent_token_id | 16 | Immediate parent's token_id |
| 26 | chain_depth | 1 | Depth in delegation chain (root=0) |

**Encoding Rules:**
1. Records MUST appear in ascending type order
2. Type 14 (capability) MAY appear multiple times
3. Type 240 (signature) MUST appear exactly once, last
4. Unknown even types: MUST reject entire token
5. Unknown odd types: MUST ignore (forward compatibility)

**Example Encoding:**
```
00 01 01                             # type=0, len=1, version=1
02 21 <33-byte-pubkey>               # type=2, len=33, issuer
04 0f 49 43 45 59 45 2d 58 31 34 ... # type=4, len=15, subject="ICEYE-X14-51070"
06 12 53 45 4e 54 49 4e 45 4c ...    # type=6, len=18, audience="SENTINEL-2C-62261"
08 04 65 a5 1e 00                    # type=8, len=4, issued_at
0a 04 65 a6 0f 80                    # type=10, len=4, expires_at
0c 10 <16-byte-random>               # type=12, len=16, token_id
0e 0f 63 6d 64 3a 69 6d 61 67 ...    # type=14, len=15, capability="cmd:imaging:msi"
f0 40 <64-byte-signature>            # type=240, len=64, signature
```

### 2.6 Priority and Preemption

Capability tokens authorize single tasks. The protocol does **not** specify:

- Task queue priority ordering
- Preemption of in-progress tasks
- Emergency override semantics

These are **operator implementation details**:

| Concern | Operator Responsibility |
|---------|------------------------|
| Scheduling | Operators time task uploads to avoid conflicts |
| Priority | Satellite firmware may implement issuer-based priority |
| Emergency | Pre-issued tokens with wider capability grants |
| Conflicts | Ground operators coordinate before upload |

**Rationale**: Keeping priority/preemption out of the protocol maintains simplicity. Operators know their satellites' capabilities and workloads; they schedule tasks accordingly. If cross-operator priority coordination becomes necessary, it may be added in a future protocol version as an optional capability token field.

---

## 3. Payment Layer: Lightning HTLCs

### 3.1 Lightning Network Integration

**Payment occurs between operators, not satellites.** Operators are ground-based and always online, enabling standard Lightning Network routing. Satellites execute tasks and route data, but do not handle payment logic.

```
+-----------------------------------------------------------------------------+
|                    OPERATOR LIGHTNING NETWORK                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|                        PAYMENT LAYER (Ground)                               |
|  ========================================================================   |
|                                                                             |
|        +----------+       Lightning       +----------+                      |
|        |Operator  |<--------------------->|Operator  |                      |
|        |    X     |      Channel          |    Y     |                      |
|        | LN Node  |                       | LN Node  |                      |
|        +----+-----+                       +----+-----+                      |
|             |                                  |                            |
|             +--------> Gateway <---------------+                            |
|                       (optional)                                            |
|                                                                             |
|  Operators are ALWAYS ONLINE. Standard Lightning routing.                   |
|                                                                             |
|  ========================================================================   |
|                        TASK LAYER (Space)                                   |
|  ========================================================================   |
|                                                                             |
|        +----------+         ISL          +----------+                       |
|        |Satellite |<-------------------->|Satellite |                       |
|        |    B     |     (data only)      |    C     |                       |
|        |  (Op X)  |                      |  (Op Y)  |                       |
|        +----------+                      +----------+                       |
|                                                                             |
|  Satellites execute tasks and route data. NO payment logic.                 |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Key Insight**: Satellite-to-satellite channels don't work due to sparse ISL connectivity. Multi-hop Lightning requires real-time coordination that's impossible with intermittent ISL windows. Moving payment logic to operators (who are always online) solves this.

See [CHANNELS.md](../future/CHANNELS.md) §2.3 "Why Satellite Channels Don't Work" for detailed analysis.

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
| **Op-to-Op** | Payment between operators | Standard Lightning |
| **Gateway-to-Op** | Customer payment routing | Standard Lightning |
| **Op-to-Gateway** | Multi-gateway routing | Standard Lightning |

**Note**: Satellite-to-satellite channels are NOT used. All payment channels exist between ground-based operators who are always online.

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

The commanding satellite sends a task request that includes both authorization and payment setup. SCRAP messages are **transport-agnostic**; framing and integrity checks are provided by the transport binding (see §16 Transport Bindings).

```
+----------------------------------------------------------------+
|                    TASK REQUEST MESSAGE                         |
+----------------------------------------------------------------+
|  Message Header                                                |
|  +-- message_type: 0x01 (task_request)                        |
|  +-- length: <payload length in bytes>                        |
|  +-- task_id: "IMG-2025-001-ICEYE"                            |
|  +-- timestamp: 1705320000                                     |
+----------------------------------------------------------------+
|  Authorization                                                 |
|  +-- capability_token: <TLV-encoded SAT-CAP>                  |
|  +-- commander_signature: Schnorr(cmd_privkey, task_hash)     |
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
```

**Message Type Codes:**
| Code | Message |
|------|---------|
| 0x01 | TaskRequest |
| 0x02 | TaskAccept |
| 0x03 | TaskReject |
| 0x04 | ProofOfExecution |
| 0x05 | DisputeMessage |
| 0x10 | LightningMessage |
| 0x11 | CapabilityToken |

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
|  +-- Schnorr(executor_privkey, message_hash)                  |
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
|       |         | 4. token_id not replayed                  |               |
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
|  +-- Schnorr signature over all above fields                   |
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

Delegation tokens use the same TLV format as root tokens, with additional fields
for chain verification. The delegating satellite signs the token.

```
+----------------------------------------------------------------+
|                    DELEGATION TOKEN (TLV-encoded)               |
+----------------------------------------------------------------+
|  REQUIRED FIELDS (same as root token)                          |
|  +-- version: 1                                                |
|  +-- issuer: <delegator's pubkey>    # Who is delegating       |
|  +-- subject: <delegate's pubkey>    # Who receives delegation |
|  +-- audience: <target satellite>    # Final target (unchanged)|
|  +-- issued_at: 1705330805                                     |
|  +-- expires_at: 1705334400          # Must be <= parent       |
|  +-- token_id: <16 random bytes>                               |
|  +-- capability: "cmd:relay:store"   # Must be subset parent   |
+----------------------------------------------------------------+
|  DELEGATION FIELDS (required for non-root)                     |
|  +-- root_issuer: <operator pubkey>  # Target's operator       |
|  +-- root_token_id: <16 bytes>       # Original token ID       |
|  +-- parent_token_id: <16 bytes>     # Parent token ID         |
|  +-- chain_depth: 2                  # Depth (root=0)          |
+----------------------------------------------------------------+
|  OPTIONAL CONSTRAINTS (must be >= restrictive as parent)       |
|  +-- constraint_rate: [5, 3600]      # Stricter than parent    |
+----------------------------------------------------------------+
|  SIGNATURE                                                     |
|  +-- signature: <64-byte Schnorr by delegator>                 |
+----------------------------------------------------------------+
```

**Presentation:** When presenting a delegated token, the commander includes the
full chain of tokens from root to the presented token. The target verifies each
link in the chain.

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

### 5.5 Routing Model

SCRAP uses **source routing** with **onion encryption**:

| Property | Description |
|----------|-------------|
| **Source-routed** | Ground operator computes complete path before upload |
| **Onion-wrapped** | Task bundle encrypted in layers; each hop sees only next hop |
| **No satellite routing** | Satellites have no routing tables or topology knowledge |
| **Ground re-computation** | Route failures require new task bundle from ground |

```
ROUTING FLOW:

Ground Operator:
  1. Computes route: A → B → C → D
  2. Wraps task bundle in onion layers (innermost = final destination)
  3. Uploads wrapped bundle to first hop (A) during ground contact

Satellite A:
  1. Decrypts outer layer
  2. Sees: next_hop = B, inner_packet = [encrypted blob]
  3. Forwards inner_packet to B via ISL
  4. Cannot see contents for C or D (encrypted to their keys)

Satellite B, C:
  - Same process: decrypt layer, forward inner packet

Satellite D (final):
  1. Decrypts innermost layer
  2. Sees: task = [imaging|processing|etc], no next_hop
  3. Executes task, delivers output
```

**Rationale**: Source routing simplifies satellite firmware (no routing protocol needed), enables route privacy (intermediate hops don't know full path), and allows ground operators to optimize routes based on current orbital geometry.

See [PTLC-FALLBACK.md](PTLC-FALLBACK.md) §7 for detailed onion packet format.

### 5.6 Ground Relay Hops

Ground stations participate as **relay hops** in task chains, enabling high-bandwidth transfers between satellites without direct ISL capability.

```
GROUND RELAY ARCHITECTURE:

Sat_A ──RF──► Ground_1 ═══Internet═══ Ground_2 ──RF──► Sat_B
(imaging)    (downlink)              (uplink)        (processing)
  │             │                       │                │
PTLC[0]      PTLC[1]                 PTLC[2]          PTLC[3]

  └─────────── May be different operators ───────────────┘
```

**Key properties**:

| Property | Description |
|----------|-------------|
| **Separate hops** | Downlink and uplink are separate capability tokens and payments |
| **Different operators** | Ground_1 and Ground_2 may be operated by different entities |
| **Parallel operation** | Both satellites can communicate with ground simultaneously |
| **Internet transit** | Data between ground stations uses standard internet routing; no SCRAP hop required |

**Ground hop capability tokens** follow the same structure as satellite tokens:
- `aud`: Ground station identifier
- `cap`: `["relay:downlink:*"]` or `["relay:uplink:*"]`
- `cns`: Bandwidth limits, data size limits, time windows

**Use cases**:
- High-bandwidth imagery transfer (exceeds ISL capacity)
- Bridging satellites without ISL capability
- Leveraging existing ground infrastructure

### 5.7 Pipeline Model

Task chains flow **forward only** through a pipeline to final delivery:

```
PIPELINE FLOW (not request/response):

[upload] → [relay] → [imaging] → [processing] → [downlink] → Customer
                                                     │
                                              Final delivery
```

**Key properties**:

| Property | Description |
|----------|-------------|
| **Forward data flow** | Each hop's output is the next hop's input |
| **Final delivery** | Last hop delivers to designated endpoint (not back through chain) |
| **Backward ack flow** | Small acknowledgments flow backward for payment settlement |
| **No data return** | Payload data does not return through the originating chain (acks are separate) |

**This is NOT request/response**:
- **Request**: Capability token + payment commitment (small, via any path)
- **Response**: Data delivered to endpoint (large, via optimized forward path)

The customer initiates the pipeline but receives output at the designated endpoint, which may be a ground station, cloud storage, or another satellite—not necessarily back through the originating relay chain.

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

### 6.3 Settlement Model: Timeout-Default (Favor Executor)

The primary settlement model for SCRAP is **timeout-default**, which favors the executor (payee) and requires the customer (payer) to actively dispute if unsatisfied.

**Rationale**: In satellite operations, the executor bears real costs (fuel, opportunity, wear) regardless of whether the customer is satisfied. Requiring active dispute rather than active approval:
1. Protects executors from unresponsive customers
2. Reduces ISL bandwidth (no approval message needed)
3. Creates economic incentive for customers to monitor results promptly

```
+-----------------------------------------------------------------------------+
|                    TIMEOUT-DEFAULT SETTLEMENT                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Timeline:                                                                  |
|                                                                             |
|  T+0:00    HTLC locked during ISL contact                                   |
|  T+0:05    Task execution begins                                            |
|  T+0:45    Task complete, proof generated                                   |
|  T+1:00    ISL ends, proof relayed to customer via any path                 |
|            |                                                                |
|            v                                                                |
|  +------------------+     +------------------+     +------------------+      |
|  |  Proof relayed   | --> |  Dispute window  | --> |  Auto-settle     |      |
|  |  to customer     |     |  (configurable)  |     |  if no dispute   |      |
|  +------------------+     +------------------+     +------------------+      |
|                                                                             |
|  Default dispute window: 6 hours (configurable per task)                    |
|  HTLC timeout: dispute_window + 12 hours (safety margin)                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 6.4 Timeout-Default Protocol

```
+-----------------------------------------------------------------------------+
|                    TIMEOUT-DEFAULT PROTOCOL FLOW                             |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Customer (A)                    Executor (B)                Ground Relay   |
|       |                              |                           |          |
|       |--- HTLC lock (T=18hr) ------>|                           |          |
|       |                              |                           |          |
|       |                         [Execute task]                   |          |
|       |                              |                           |          |
|       |                              |--- Proof of Execution --->|          |
|       |<----------------------- Proof relayed -------------------|          |
|       |                              |                           |          |
|       |  [Dispute window: 6 hours]   |                           |          |
|       |                              |                           |          |
|   OPTION A: Customer satisfied (no action)                                  |
|       |                              |                           |          |
|       |  [6 hours pass, no dispute]  |                           |          |
|       |                              |                           |          |
|       |<-- Preimage revealed --------|  (on next ISL contact)    |          |
|       |                              |                           |          |
|   OPTION B: Customer disputes                                               |
|       |                              |                           |          |
|       |--- Dispute message --------------------------------->|   |          |
|       |   (signed, with evidence)    |                       |   |          |
|       |                              |                       |   |          |
|       |                              |<-- Dispute notification --|          |
|       |                              |                           |          |
|       |  [HTLC timeout expires, A refunded]                      |          |
|       |                              |                           |          |
+-----------------------------------------------------------------------------+
```

### 6.5 Dispute Evidence Requirements

| Dispute Type | Required Evidence | Resolution |
|--------------|-------------------|------------|
| **Task not executed** | Missing proof within dispute window | Auto-refund at HTLC timeout |
| **Proof invalid** | Signature verification failure | Auto-refund |
| **Quality insufficient** | Proof hash vs delivered data mismatch | Manual review (future) |
| **Constraints violated** | Proof parameters outside task constraints | Auto-refund |

### 6.6 Settlement Options Summary

| Model | Use Case | Trust Requirement |
|-------|----------|-------------------|
| **Immediate** | Simple tasks, same-orbit ISL | None (direct verification) |
| **Timeout-Default** | Standard operations | Customer monitors results |
| **Arbiter Panel** | High-value, cross-operator | Federation of arbiters |

**Default for CubeSat testbed**: Timeout-default with 6-hour dispute window.

### 6.7 DisputeMessage Structure

When a customer initiates a dispute, they broadcast a signed message:

```python
@dataclass
class DisputeMessage:
    task_token_id: bytes       # 16 bytes, reference to original task
    payment_hash: bytes        # 32 bytes, identifies the HTLC
    dispute_type: str          # "no_proof" | "invalid_proof" | "constraint_violation"
    evidence: DisputeEvidence  # Type-specific evidence
    timestamp: int             # Unix timestamp
    customer_sig: bytes        # BIP-340 Schnorr signature

    def message_hash(self) -> bytes:
        return tagged_hash(
            "SCRAP/dispute/v1",
            self.task_token_id +
            self.payment_hash +
            self.dispute_type.encode() +
            self.evidence.serialize() +
            self.timestamp.to_bytes(4, 'big')
        )

@dataclass
class DisputeEvidence:
    proof_received: bytes | None     # The proof that was received (if any)
    expected_output_hash: bytes | None  # What was expected
    actual_output_hash: bytes | None    # What was received
    constraint_violated: str | None     # Which constraint failed

    def serialize(self) -> bytes:
        """Serialize evidence as TLV records."""
        tlv = TLVWriter()
        if self.proof_received:
            tlv.write(0, self.proof_received)
        if self.expected_output_hash:
            tlv.write(2, self.expected_output_hash)
        if self.actual_output_hash:
            tlv.write(4, self.actual_output_hash)
        if self.constraint_violated:
            tlv.write(6, self.constraint_violated.encode('utf-8'))
        return tlv.to_bytes()
```

**Dispute Types**:

| Type | Evidence Required | Resolution |
|------|-------------------|------------|
| `no_proof` | None (timeout elapsed) | Auto-refund |
| `invalid_proof` | `proof_received`, signature verification failure | Auto-refund |
| `hash_mismatch` | `expected_output_hash`, `actual_output_hash` | Auto-refund if hashes differ |
| `constraint_violation` | `constraint_violated`, proof showing violation | Auto-refund |

### 6.8 Proof Model: Delivery Only

SCRAP proves **delivery**, not **correctness**:

| Task Type | Proof | What It Proves |
|-----------|-------|----------------|
| **Relay** | Next hop acknowledgment signature | Data was forwarded |
| **Imaging** | Output data hash + executor signature | Image was captured |
| **Processing** | Output data hash + executor signature | Computation was performed |
| **Downlink** | Ground station receipt signature | Data was delivered |

**The protocol does NOT verify**:
- Image quality or content accuracy
- Computation correctness (only that computation occurred)
- Data validity beyond cryptographic authentication
- Whether output meets customer expectations

**Trust model**:

```
REPUTATION-BASED TRUST:

┌─────────────────────────────────────────────────────────────────┐
│  Off-Chain                          On-Chain                    │
│                                                                 │
│  Operator reputation ◄────────────► Payment settlement          │
│  Registry blacklisting              Timeout-default arbiter     │
│  Legal recourse (large claims)      Dispute evidence            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

- Operators have reputation maintained off-chain
- Bad actors are blacklisted from the service registry
- Small claims are not worth disputing (timeout-default favors executor)
- Large claims have off-chain legal recourse

**Rationale**: Verifying correctness on-chain would require:
1. Uploading full output data (impractical for imagery/video)
2. Defining quality metrics in smart contracts (subjective)
3. Oracle-based verification (adds trust assumptions)

The hash-based delivery proof is simple, deterministic, and sufficient for the trust model where operators have reputation at stake.

**Arbitration scope**: Arbiters (§6.2-6.6) resolve **delivery disputes** (was proof provided? did timeout expire?), not **quality disputes** (was the image good enough?).

---

## 7. Ground Station Role

Ground stations handle on-chain settlement and watchtower functions, but do NOT participate in space-segment payment flows.

### 7.1 Functions

```
+-----------------------------------------------------------------------------+
|                    GROUND STATION FUNCTIONS                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. CHANNEL FUNDING                                                         |
|  * Satellite requests channel open with another satellite                   |
|  * Funding transaction created (2-of-2 multisig or MuSig2*)                 |
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

* Channel Funding Output Types:
  - Current Lightning (2024): 2-of-2 OP_CHECKMULTISIG (P2WSH)
  - Taproot channels (experimental): MuSig2 aggregate key (P2TR)

  SCRAP is designed to work with either. Taproot channels provide smaller
  on-chain footprint and improved privacy but require MuSig2 support in
  LDK (available in LDK 0.0.123+, experimental).
```

---

## 8. Emergency Authorization

### 8.1 Emergency Capability Class

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

### 8.2 Authorization Levels

| Level | Authorization | Use Case | Audit |
|-------|---------------|----------|-------|
| **Pre-Authorized** | Standing tokens to responders | International Charter, SAR | Optional |
| **Rapid Approval** | Expedited issuance (minutes) | Government agencies | Required |
| **Act-First** | Execute, authorize later | Collision avoidance, life safety | Mandatory |

---

## 9. Security Analysis

### 9.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| **Unauthorized command** | Capability token verification |
| **Replay attack** | Token ID (token_id) in used-token cache |
| **Man-in-the-middle** | BIP-340 Schnorr signatures on all messages |
| **Payment theft** | HTLC timeout guarantees refund |
| **Old state broadcast** | Watchtower penalty transactions |
| **Clock manipulation** | GPS-disciplined clocks, tolerant windows |

### 9.2 Cryptographic Properties

| Property | Mechanism |
|----------|-----------|
| **Authentication** | Operator signature on token; commander signature on command |
| **Authorization** | Explicit capability list in token |
| **Integrity** | BIP-340 Schnorr signatures over all data |
| **Freshness** | Timestamps, expiration, nonces |
| **Non-repudiation** | Payment preimage serves as receipt |
| **Atomicity** | HTLC: either complete or timeout refund |

---

## 10. Implementation

### 10.1 Core Data Structures

```python
@dataclass
class CapabilityToken:
    """TLV-encoded capability token."""
    version: int                   # Protocol version (1)
    issuer: bytes                  # Target's operator pubkey (33 bytes)
    subject: bytes | str           # Commander pubkey or identifier
    audience: bytes | str          # Target satellite pubkey or identifier
    issued_at: int                 # Unix timestamp (uint32)
    expires_at: int                # Unix timestamp (uint32)
    token_id: bytes                # Unique ID (16 random bytes)
    capabilities: list[str]        # Permitted operations
    constraints: dict | None       # Optional: geo, rate, amount, after
    # Delegation fields (None for root tokens)
    root_issuer: bytes | None      # Target's operator (for delegation)
    root_token_id: bytes | None    # Root token ID (16 bytes)
    parent_token_id: bytes | None  # Parent token ID (16 bytes)
    chain_depth: int | None        # Delegation depth (root=0)
    signature: bytes               # BIP-340 Schnorr (64 bytes)

@dataclass
class TaskRequest:
    task_id: str
    capability_token: bytes        # TLV-encoded token
    delegation_chain: list[bytes]  # Parent tokens if delegated
    task_type: str
    target: dict                   # GeoJSON
    parameters: dict
    constraints: dict
    payment_offer: dict            # max_sats, timeout_blocks
    commander_signature: bytes     # Schnorr signature

@dataclass
class TaskAccept:
    task_id: str
    execution_plan: dict
    invoice: LightningInvoice      # BOLT 11
    executor_signature: bytes      # Schnorr signature

@dataclass
class ProofOfExecution:
    task_id: str
    executor: bytes                # Executor pubkey
    execution_time: int
    parameters_as_executed: dict
    product_hash: bytes            # SHA256 of output
    delivery_info: dict
    executor_signature: bytes      # Schnorr signature
```

### 10.2 Helper Functions

```python
import hashlib

def tagged_hash(tag: str, msg: bytes) -> bytes:
    """
    BIP-340 style tagged hash with domain separation.
    Prevents cross-protocol attacks by binding hash to specific context.
    """
    tag_hash = hashlib.sha256(tag.encode('utf-8')).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()

def schnorr_verify(message_hash: bytes, signature: bytes, pubkey: bytes) -> bool:
    """
    Verify BIP-340 Schnorr signature.

    Args:
        message_hash: 32-byte hash of message
        signature: 64-byte Schnorr signature
        pubkey: 32-byte x-only pubkey (or 33-byte compressed, first byte stripped)

    Returns:
        True if signature is valid

    Note: Use a proper cryptographic library (secp256k1, libsecp256k1-py)
    for production implementation.
    """
    # Implementation depends on crypto library
    # Example: return secp256k1.schnorr_verify(message_hash, signature, pubkey)
    raise NotImplementedError("Use secp256k1 library")
```

### 10.3 Verification Functions

```python
def verify_capability_token(token: CapabilityToken,
                            target: Satellite) -> bool:
    """Verify single-hop (root) capability token."""

    # 1. Verify signature by operator (BIP-340 Schnorr)
    token_data = token.serialize_tlv(exclude_signature=True)
    token_hash = tagged_hash("SCRAP/token/v1", token_data)
    if not schnorr_verify(token_hash, token.signature, target.operator_pubkey):
        return False

    # 2. Check audience matches target
    if token.audience != target.id and token.audience != target.pubkey:
        return False

    # 3. Check not expired
    if token.expires_at < get_secure_time():
        return False

    # 4. Check not replayed (token_id is 16 bytes)
    if token.token_id in target.used_tokens:
        return False
    target.used_tokens.add(token.token_id, token.expires_at)

    return True

def verify_delegation_chain(token: CapabilityToken,
                            chain: list[CapabilityToken],
                            target: Satellite) -> bool:
    """Verify delegated token with full chain back to root."""

    full_chain = chain + [token]

    # 1. Verify root is from target's operator
    root = full_chain[0]
    root_data = root.serialize_tlv(exclude_signature=True)
    root_hash = tagged_hash("SCRAP/token/v1", root_data)
    if not schnorr_verify(root_hash, root.signature, target.operator_pubkey):
        return False
    if root.audience != target.id and root.audience != target.pubkey:
        return False
    if root.chain_depth is not None and root.chain_depth != 0:
        return False  # Root must have depth 0 or None

    # 2. Walk chain verifying each delegation
    for i in range(1, len(full_chain)):
        parent = full_chain[i-1]
        child = full_chain[i]

        # Child issuer must match parent subject
        if child.issuer != parent.subject:
            return False

        # Verify child signature by parent's subject (who is the delegator)
        child_data = child.serialize_tlv(exclude_signature=True)
        child_hash = tagged_hash("SCRAP/delegation/v1", child_data)
        if not schnorr_verify(child_hash, child.signature, parent.subject):
            return False

        # Verify capability attenuation
        if not is_subset(child.capabilities, parent.capabilities):
            return False

        # Verify expiration inheritance
        if child.expires_at > parent.expires_at:
            return False

        # Verify chain depth
        expected_depth = (parent.chain_depth or 0) + 1
        if child.chain_depth != expected_depth:
            return False

        # Verify root references match
        if child.root_issuer != target.operator_pubkey:
            return False
        if child.root_token_id != root.token_id:
            return False

    return True
```

### 10.4 Used-Token Cache Management

The `used_tokens` cache prevents replay attacks but must be bounded to prevent memory exhaustion.

#### 10.4.1 Cache Structure

```python
from dataclasses import dataclass
from typing import Dict
import time

@dataclass
class UsedTokenEntry:
    token_id: bytes      # 16-byte token identifier
    expires_at: int      # Token expiration timestamp
    added_at: int        # When entry was added to cache

class UsedTokenCache:
    """
    Bounded cache for used token IDs with automatic expiration.

    Storage requirement: ~100 bytes per entry
    Default capacity: 10,000 entries = ~1 MB
    """

    def __init__(self, max_entries: int = 10000):
        self.entries: Dict[bytes, UsedTokenEntry] = {}
        self.max_entries = max_entries

    def contains(self, token_id: bytes) -> bool:
        """Check if token has been used."""
        if token_id in self.entries:
            return True
        return False

    def add(self, token_id: bytes, expires_at: int) -> None:
        """Add token to used cache."""
        # Evict expired entries if at capacity
        if len(self.entries) >= self.max_entries:
            self._evict_expired()

        # If still at capacity, evict oldest entries
        if len(self.entries) >= self.max_entries:
            self._evict_oldest(count=self.max_entries // 10)

        self.entries[token_id] = UsedTokenEntry(
            token_id=token_id,
            expires_at=expires_at,
            added_at=int(time.time())
        )

    def _evict_expired(self) -> int:
        """Remove entries for expired tokens. Returns count evicted."""
        now = int(time.time())
        expired = [tid for tid, entry in self.entries.items()
                   if entry.expires_at < now]
        for tid in expired:
            del self.entries[tid]
        return len(expired)

    def _evict_oldest(self, count: int) -> None:
        """Remove oldest entries by added_at timestamp."""
        if count >= len(self.entries):
            self.entries.clear()
            return

        sorted_entries = sorted(self.entries.items(),
                                key=lambda x: x[1].added_at)
        for tid, _ in sorted_entries[:count]:
            del self.entries[tid]
```

#### 10.4.2 Eviction Policy

| Trigger | Action |
|---------|--------|
| Cache at capacity | Evict all expired entries |
| Still at capacity after expiry eviction | Evict oldest 10% by `added_at` |
| Periodic maintenance (every 1 hour) | Evict all expired entries |
| Satellite reboot | Load persisted cache from NVM |

#### 10.4.3 Persistence Requirements

- Cache MUST be persisted to non-volatile memory on modification
- Persistence frequency: after every 100 additions or every 5 minutes (whichever first)
- On reboot: load cache from NVM before accepting any tokens
- **Critical**: Failure to persist cache enables replay attacks after reboot

#### 10.4.4 Security Considerations

**Attack: Cache exhaustion via expired tokens**
- Adversary submits many tokens with `exp` far in future
- Mitigation: Reject tokens with `exp > now + MAX_TOKEN_LIFETIME` (default: 7 days)

**Attack: Replay after cache eviction**
- Adversary waits for their token to be evicted, then replays
- Mitigation: Expired entries are evicted first; active tokens survive longer
- Mitigation: Tokens with `exp` in the past are rejected before cache check

#### 10.4.5 Atomic Verification Order

Token verification MUST follow this exact order to prevent race conditions and ensure atomic replay protection:

```python
def verify_and_mark_token(token: CapabilityToken, target: Satellite) -> VerifyResult:
    """
    Atomically verify token and mark as used.

    CRITICAL: Steps 1-4 (validation) must complete before step 5 (cache add).
    Otherwise, a valid token could be rejected on retry after partial failure.

    Returns: VerifyResult with status and reason
    """

    # === PHASE 1: STATELESS VALIDATION (no side effects) ===

    # 1. Structural validation
    if not token.has_required_fields():
        return VerifyResult(REJECT, "malformed_token")

    # 2. Time bounds (cheap check before crypto)
    current_time = get_secure_time()

    if token.expires_at < current_time:
        return VerifyResult(REJECT, "expired")

    if token.expires_at > current_time + MAX_TOKEN_LIFETIME:
        return VerifyResult(REJECT, "expiry_too_far")

    if hasattr(token, 'issued_at') and token.issued_at > current_time + CLOCK_SKEW:
        return VerifyResult(REJECT, "future_issued")

    # 3. Audience validation
    if token.audience != target.id and token.audience != "*":
        return VerifyResult(REJECT, "wrong_audience")

    # 4. Signature verification (expensive, do last in stateless phase)
    token_data = token.serialize_tlv(exclude_signature=True)
    token_hash = tagged_hash("SCRAP/token/v1", token_data)
    if not schnorr_verify(token_hash, token.signature, target.operator_pubkey):
        return VerifyResult(REJECT, "invalid_signature")

    # === PHASE 2: STATEFUL OPERATIONS (atomic with cache) ===

    # 5. Replay check and mark (MUST be atomic)
    with target.used_tokens.lock:
        if target.used_tokens.contains(token.token_id):
            return VerifyResult(REJECT, "replayed")

        # Token is valid - mark as used BEFORE returning success
        target.used_tokens.add(token.token_id, token.expires_at)

    return VerifyResult(ACCEPT, None)
```

**Verification Order Rationale:**

| Step | Purpose | Why This Order |
|------|---------|----------------|
| 1. Structure | Fast reject malformed | Cheapest check |
| 2. Time bounds | Reject expired/future | Prevents cache pollution |
| 3. Audience | Reject wrong target | Quick rejection |
| 4. Signature | Cryptographic proof | Expensive, do after cheap checks |
| 5. Replay check+mark | Prevent double-use | MUST be atomic and last |

**Critical Invariant:** The cache addition (step 5b) MUST happen atomically with the cache check (step 5a) and MUST occur before returning success. If these are not atomic, two concurrent verifications of the same token could both pass the check before either marks it used.

### 10.5 Satellite Node Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **CPU** | ARM Cortex-A class | Schnorr, SHA256 |
| **RAM** | 64 MB minimum | Channel state, token cache |
| **Storage** | 10 MB | Channels, used token_id cache |
| **RNG** | Hardware TRNG | Key/nonce generation |
| **Clock** | See timing requirements below | HTLC timeouts |

#### 10.5.1 Timing Requirements

HTLC timeouts require accurate timekeeping. Two configurations are supported:

**GPS-Disciplined (Recommended)**:
- GPS/GNSS receiver provides UTC time
- Clock accuracy: ±1 microsecond typical
- No drift between ground contacts
- Required for: FHSS mode, tight HTLC margins

**Ground-Uplinked (Fallback)**:
- Time synchronized during ground station contacts
- Clock accuracy: depends on onboard oscillator quality
- Drift: ~1-10 ppm typical (0.1-1 second/day)
- Requires: conservative HTLC timeout margins (+6 hours)

| Timing Source | HTLC Margin | Use Case |
|---------------|-------------|----------|
| GPS-disciplined | 24 hours/hop | Standard operations |
| Ground-uplinked (TCXO) | 30 hours/hop | No GPS, frequent ground contact |
| Ground-uplinked (XO) | 48 hours/hop | No GPS, infrequent ground contact |

**GPS Receiver Prevalence**: Research indicates GPS/GNSS receivers are standard on most operational CubeSats requiring orbit determination or precise timing, but may be absent on educational or technology demonstration missions. Implementations SHOULD support ground-uplinked time as fallback.

#### 10.5.2 Clock Security

Clock manipulation is a critical attack vector because SCRAP uses Bitcoin timelocks (CLTV) for HTLC expiration. An adversary who can shift perceived time can:

- **Premature timeout**: Steal funds via early refund claim
- **Prevented claims**: Lock funds past true expiration
- **State desync**: Cause channel disputes

**get_secure_time() Implementation:**

```python
def get_secure_time() -> int:
    """
    Return current Unix timestamp from secure time source.

    SECURITY: This function must resist timing attacks.
    """

    sources = []

    # Collect all available timing sources
    if gps_available():
        sources.append(("gps", gps_time(), WEIGHT_GPS))

    if ground_ntp_recent():  # Within last orbit
        sources.append(("ntp", ground_ntp_time(), WEIGHT_NTP))

    sources.append(("rtc", rtc_time(), WEIGHT_RTC))

    # Sanity check: reject outliers
    times = [s[1] for s in sources]
    median = sorted(times)[len(times) // 2]

    valid_sources = [(name, t, w) for name, t, w in sources
                     if abs(t - median) < MAX_CLOCK_DEVIATION]

    if not valid_sources:
        # All sources disagree - possible attack or failure
        log_anomaly("clock_disagreement", sources)
        # Fall back to RTC with extended margins
        return rtc_time()

    # Weighted average of valid sources
    total_weight = sum(w for _, _, w in valid_sources)
    weighted_time = sum(t * w for _, t, w in valid_sources) / total_weight

    return int(weighted_time)

# Weights for timing source arbitration
WEIGHT_GPS = 10   # High confidence, spoofable
WEIGHT_NTP = 5    # Medium confidence, ground-verified
WEIGHT_RTC = 1    # Low confidence, no external verification
MAX_CLOCK_DEVIATION = 60  # Reject sources >60s from median
```

**Spoofing Detection Indicators:**
- Sudden time jump (>1s without eclipse/maneuver)
- Position jump inconsistent with orbital mechanics
- GPS signal strength anomalies
- Doppler shift mismatch
- Disagreement between multiple GPS receivers

**Response to Suspected Spoofing:**
1. Fall back to ground NTP + RTC
2. Increase timeout margins (conservative)
3. Alert ground station
4. Continue operation with extended safety margins

For adversarial environments (military/contested operations), see [ADVERSARIAL.md](ADVERSARIAL.md) Section 2 "Clock Security" for multi-source timing architecture and enhanced spoofing detection.

---

## 11. Cryptographic Architecture

### 11.1 Elliptic Curve Selection

#### 11.1.1 Default: secp256k1 Only (Recommended)

SCRAP uses **secp256k1 exclusively** for all cryptographic operations:

| Operation | Curve | Algorithm | Frequency |
|-----------|-------|-----------|-----------|
| SISL X3DH key agreement | secp256k1 | ECDH × 3 | Once per session |
| Capability token signatures | secp256k1 | BIP-340 Schnorr | Once per task |
| Proof-of-execution signatures | secp256k1 | BIP-340 Schnorr | Once per task |
| Lightning PTLCs | secp256k1 | Schnorr adaptor | Once per payment |
| Onion routing (per-hop) | secp256k1 | ECDH | Per relay hop |
| BIP-32 key derivation | secp256k1 | Point multiplication | At provisioning |

**Rationale for single-curve design**:

1. **Simplicity**: One key hierarchy to provision, protect, and audit
2. **Lightning-native**: No curve translation or bridging layers
3. **Verifiable parameters**: Koblitz curve with deterministic generation (no unexplained NIST seed constants)
4. **Battle-tested**: libsecp256k1 secures billions of dollars in Bitcoin
5. **Sufficient performance**: All ECC operations are infrequent enough for software implementation

#### 11.1.2 Hardware Implementation Options

| Implementation | Platform | ECDH Time | ECDSA Sign | Radiation | Notes |
|----------------|----------|-----------|------------|-----------|-------|
| libsecp256k1 (software) | LEON3-FT 100 MHz | ~200 ms | ~100 ms | N/A | Baseline for rad-hard |
| libsecp256k1 (software) | ARM Cortex-A53 1.2 GHz | ~12 ms | ~6 ms | N/A | Typical CubeSat OBC |
| FPGA soft core | RTG4 / XQRKU060 | ~0.5 ms | ~0.2 ms | 100 krad | Zcash Foundation design |
| FPGA soft core | Artix-7 + TMR | ~0.5 ms | ~0.2 ms | ~20 krad | LEO CubeSat viable |

**FPGA Implementation Sources**:
- Zcash Foundation: https://github.com/HowToLoveChina/secp256k1-systemverlog-fpga (SystemVerilog, GPL-3.0)
- Xilinx Vitis: https://xilinx.github.io/Vitis_Libraries/security/ (HLS C++, Apache-2.0)

**No space-grade HSM supports secp256k1 natively**. Hardware acceleration requires FPGA soft cores.

#### 11.1.3 When to Consider P-256

P-256 (secp256r1) may be used for **SISL link-layer authentication only** when:

1. **Government contract requires FIPS 140-2/3 compliance**
   - secp256k1 is not in NIST SP 800-186
   - P-256 is FIPS-approved

2. **Interfacing with existing CCSDS SDLS infrastructure**
   - Some ground systems mandate P-256 for frame authentication

3. **Using COTS secure elements in low-radiation environments**
   - ATECC608 provides hardware P-256 at ~5 ms per ECDH
   - NOT radiation-hardened (suitable for shielded GEO bus only)

**P-256 architecture (if required)**:

```
┌─────────────────────────────────────────────────────────────────┐
│                    DUAL KEY HIERARCHY                           │
├─────────────────────────────────────────────────────────────────┤
│  P-256 Key (SISL only):                                         │
│    Purpose: X3DH link authentication                            │
│    Storage: ATECC608 secure element (if available)              │
│    Derivation: HKDF(operator_seed, "sisl-p256" || sat_id)      │
│                                                                 │
│  secp256k1 Keys (SCRAP/Lightning):                               │
│    Purpose: Payments, capability tokens, proofs, onion routing  │
│    Storage: RAM (derived at boot)                               │
│    Derivation: BIP-32 m/7227'/0'/sat_id'/...                   │
└─────────────────────────────────────────────────────────────────┘
```

**Dual-curve costs**:
- Trust list storage doubles (two public keys per satellite)
- Two key derivation paths to implement and verify
- SISL and SCRAP use different identity keys
- Complexity increases attack surface

**P-256 is NEVER used for**:
- Lightning HTLCs (Bitcoin requires secp256k1)
- BIP-32 key derivation (standard is secp256k1-only)
- Onion routing (Sphinx protocol uses secp256k1)
- Capability tokens (must be verifiable by Lightning nodes)
- Proof-of-execution (settlement requires secp256k1 signatures)

#### 11.1.4 Recommendation Summary

| Deployment | Recommended Curve(s) | Rationale |
|------------|---------------------|-----------|
| Commercial LEO constellation | secp256k1 only | Simplicity, Lightning-native |
| Government/military | P-256 (SISL) + secp256k1 (SCRAP) | FIPS compliance |
| CCSDS ground integration | P-256 (SISL) + secp256k1 (SCRAP) | Legacy compatibility |
| Deep space / high radiation | secp256k1 only (FPGA) | No COTS secure elements viable |

**Default choice: secp256k1 only.** Add P-256 only when contractually required.

### 11.2 Space-Specific Security Model

**Threat Model Differences from Terrestrial Systems**:

| Threat | Terrestrial | Space | Implication |
|--------|-------------|-------|-------------|
| Physical key extraction | High risk | Negligible | HSM not required for physical security |
| Side-channel attacks | Feasible | Impractical | No shielding requirements |
| Supply chain compromise | High risk | Controlled | Operator controls all flight software |
| Remote exploitation | Primary threat | Primary threat | Software security critical |
| Key exfiltration via malware | High risk | Low risk | No untrusted code execution |

**Rationale**: Hardware Security Modules (HSMs) primarily defend against physical attacks (cold boot, probing, side-channel). In space:
- Physical access requires a space mission costing $10M+
- Operators control 100% of software loaded on spacecraft
- No USB ports, network services, or user-installable software
- Radiation-induced bit flips are a greater concern than adversarial attacks

**Recommended Implementation**:

| Component | Implementation | Rationale |
|-----------|----------------|-----------|
| Private keys | RAM storage | Physical access infeasible |
| Key derivation | Software BIP-32 | Operator-controlled boot |
| ECDSA signing | libsecp256k1 | Battle-tested, constant-time |
| Random numbers | Hardware TRNG | Required for nonces |

**Performance on Space-Grade Hardware**:

| Processor | ECDSA Sign | ECDSA Verify | Notes |
|-----------|------------|--------------|-------|
| ARM Cortex-A53 (1.2 GHz) | ~25ms | ~50ms | Typical CubeSat OBC |
| ARM Cortex-A72 (1.8 GHz) | ~12ms | ~25ms | Higher-end CubeSat |
| LEON3 (100 MHz) | ~400ms | ~800ms | Rad-hard, ESA standard |
| Xilinx Zynq (667 MHz) | ~60ms | ~120ms | Space-grade FPGA SoC |

For ISL windows of 5+ minutes, software ECDSA is acceptable on all listed processors.

**Key Protection**:
- Keys derived at boot from encrypted seed stored in non-volatile memory
- Seed encrypted with operator-specific key burned at manufacturing
- No runtime key export capability
- Key zeroization on anomaly detection

### 11.3 Key Hierarchy

```
+-----------------------------------------------------------------------------+
|                    SATELLITE KEY HIERARCHY                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Root Keys (Ground, cold storage)                                           |
|  ================================                                           |
|  * Operator master key (offline, never transmitted)                         |
|  * Satellite seed = HMAC-SHA256(master_key, sat_id)                        |
|                                                                             |
|  Satellite Keys (RAM, derived at boot)                                      |
|  =====================================                                      |
|  * Identity key: signs proofs, capability tokens                            |
|  * Channel keys: per Lightning channel (BIP-32 derived)                     |
|  * Session keys: ephemeral ECDH for ISL encryption                          |
|                                                                             |
|  Derivation (BIP-32):                                                       |
|  * Identity:  m/7227'/0'/sat_id'/0/0                                       |
|  * Channel N: m/7227'/0'/sat_id'/1/N                                       |
|  * Session:   m/7227'/0'/sat_id'/2/epoch                                   |
|                                                                             |
|  Storage:                                                                   |
|  * Encrypted seed in NVM (AES-256, operator key)                           |
|  * Derived keys in RAM only                                                 |
|  * No key export interface                                                  |
|                                                                             |
+-----------------------------------------------------------------------------+
```

#### 12.3.1 Derivation Path Rationale

**Purpose index 7227'**: SCRAP uses a dedicated BIP-32 purpose to avoid collision with standard wallet derivation paths (BIP-44 uses 44', BIP-84 uses 84', etc.). The value 7227 is arbitrary but memorable ("SCRAP" → 7227 on phone keypad).

| Path Component | Value | Description |
|----------------|-------|-------------|
| Purpose | 7227' | SCRAP-specific (hardened) |
| Coin type | 0' | Bitcoin mainnet (hardened) |
| Account | sat_id' | NORAD catalog ID (hardened) |
| Change | 0/1/2 | Key category (identity/channel/session) |
| Index | N | Key index within category |

**Hardened derivation** (indicated by ') is used for purpose, coin type, and account to prevent child key compromise from revealing parent keys.

### 11.4 Domain Separators

Domain separation prevents cross-protocol attacks where a signature valid in one context could be replayed in another. SCRAP uses tagged hashes following BIP-340 conventions.

#### 11.4.1 Tag Definitions

| Tag | Purpose | Context |
|-----|---------|---------|
| `SCRAP/token/v1` | Capability token signature | Target's operator signs token |
| `SCRAP/binding/v1` | Payment-capability binding | Commander signs token_id+payment_hash |
| `SCRAP/proof/v1` | Execution proof | Executor signs proof payload |
| `SCRAP/delegation/v1` | Delegation token | Delegator signs delegation payload |

#### 11.4.2 Tagged Hash Construction

Following BIP-340, tagged hashes are computed as:

```
tagged_hash(tag, msg) = SHA256(SHA256(tag) || SHA256(tag) || msg)
```

The double SHA256 of the tag creates a 64-byte midstate that can be precomputed for efficiency.

#### 11.4.3 Application to SCRAP Messages

**Capability Token Signature:**
```
# Signature covers all TLV records except signature (type 240)
token_data = TLV_serialize(token, exclude_types=[240])
token_hash = tagged_hash("SCRAP/token/v1", token_data)
signature = schnorr_sign(operator_key, token_hash)
```

**Payment-Capability Binding:**
```
# token_id is TLV type 12 (16 bytes)
binding_msg = token_id || payment_hash
binding_hash = tagged_hash("SCRAP/binding/v1", binding_msg)
signature = schnorr_sign(commander_key, binding_hash)
```

**Execution Proof:**
```
proof_msg = task_token_id || payment_hash || output_hash || timestamp_be8
proof_hash = tagged_hash("SCRAP/proof/v1", proof_msg)
signature = schnorr_sign(executor_key, proof_hash)
```

**Delegation Token:**
```
# Signature covers all TLV records except signature (type 240)
delegation_data = TLV_serialize(delegation, exclude_types=[240])
delegation_hash = tagged_hash("SCRAP/delegation/v1", delegation_data)
signature = schnorr_sign(delegator_key, delegation_hash)
```

#### 11.4.4 Security Properties

Domain separation ensures:
1. **No cross-context replay**: A token signature cannot be reused as a proof signature
2. **Version isolation**: `v1` tags prevent future protocol versions from accepting old signatures
3. **Protocol isolation**: SCRAP signatures cannot be replayed in Bitcoin or Lightning contexts
4. **Collision resistance**: Different tag prefixes guarantee different hash outputs for identical messages

### 11.5 Threshold Signatures (FROST/ROAST)

For coalition operations requiring m-of-n authorization, SCRAP uses threshold Schnorr signatures via [FROST](https://eprint.iacr.org/2020/852) (Flexible Round-Optimized Schnorr Threshold signatures) or [ROAST](https://eprint.iacr.org/2022/550) (Robust Asynchronous Schnorr Threshold signatures).

#### 11.5.1 When to Use Threshold Signatures

| Scenario | Single Signer | Threshold (FROST/ROAST) |
|----------|---------------|-------------------------|
| Commercial operator | Yes | No |
| Coalition/joint operations | No | Yes |
| High-value asset control | Optional | Recommended |
| Regulatory requirement | Depends | As required |

#### 11.5.2 Properties

**FROST properties:**
- t-of-n threshold Schnorr signatures
- Produces standard BIP-340 signatures (indistinguishable from single-signer)
- Requires coordinated signing rounds

**ROAST properties:**
- Wrapper around FROST for robustness
- Handles malicious/unresponsive signers
- Guaranteed termination if t honest parties exist
- Recommended for space operations where communication may fail

#### 11.5.3 Coalition Capability Token

```
CoalitionCapabilityToken:
  v: 1
  iss: <frost_aggregate_pubkey>    # Threshold aggregate key
  iss_threshold: "2-of-3"          # Human-readable policy
  iss_parties: [pubkey_A, pubkey_B, pubkey_C]  # For audit
  sub: "coalition-satellite-id"
  aud: "executor-satellite-id"
  cap: ["cmd:relay:priority"]
  sig: <frost_aggregate_signature> # Standard Schnorr sig
```

**Key property:** The resulting signature is a standard BIP-340 Schnorr signature. Verifiers cannot distinguish threshold signatures from single-signer signatures, preserving privacy of the authorization structure.

#### 11.5.4 Setup and Issuance

1. **Key generation (once)**: Coalition partners run FROST Distributed Key Generation (DKG)
2. **Aggregate key**: The threshold aggregate public key becomes the token issuer
3. **Token issuance**: Requires t-of-n signing session via FROST/ROAST
4. **Verification**: Standard Schnorr verification against aggregate key

#### 11.5.5 Coalition Channel Funding

For coalition-controlled channel funds:

```
Funding output:
  <frost_aggregate_key> CHECKSIG

Update/Settlement:
  Signed with FROST/ROAST by coalition threshold
```

This enables m-of-n control over channel funds without revealing the threshold structure on-chain.

For detailed coalition operation scenarios including cross-domain authorization, see [ADVERSARIAL.md](ADVERSARIAL.md) Section 5 "Coalition Operations".

---

## 12. Payment-Capability Token Binding

### 12.1 Binding Structure

Capability tokens and Lightning payments are cryptographically bound to prevent payment without authorization and authorization without payment:

```
+-----------------------------------------------------------------------------+
|                    PAYMENT-CAPABILITY BINDING                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Task Request = {                                                           |
|    capability_token,                                                        |
|    payment_hash,                                                            |
|    binding_signature                                                        |
|  }                                                                          |
|                                                                             |
|  Binding: Schnorr_Sign(                                                     |
|    requester_key,                                                           |
|    tagged_hash("SCRAP/binding/v1", token_id || payment_hash)                |
|  )                                                                          |
|                                                                             |
|  Verification:                                                              |
|  1. Verify capability_token signature (iss authority)                       |
|  2. Verify binding_signature (sub is requester)                             |
|  3. Verify SHA256 commitment links token to payment                         |
|  4. Verify HTLC payment_hash matches                                        |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 12.2 TLV-Encoded Bound Request

```python
@dataclass
class BoundTaskRequest:
    capability_token: bytes      # TLV-encoded capability token
    payment_hash: bytes          # 32 bytes, SHA256(preimage)
    payment_amount_msat: int     # Payment amount in millisatoshi
    htlc_timeout_blocks: int     # HTLC timeout in Bitcoin blocks
    binding_sig: bytes           # BIP-340 Schnorr signature over binding hash

    def binding_hash(self) -> bytes:
        # Extract token_id (type 12) from TLV-encoded token
        token_id = tlv_extract(self.capability_token, type=12)
        return tagged_hash(
            "SCRAP/binding/v1",
            token_id + self.payment_hash
        )

    def verify_binding(self, requester_pubkey: bytes) -> bool:
        return schnorr_verify(
            self.binding_hash(),
            self.binding_sig,
            requester_pubkey
        )
```

### 12.3 On-Execution Proof

When the executor completes the task, they generate a proof that:
1. Proves task completion
2. Binds to the original request
3. Enables payment settlement

```python
@dataclass
class ExecutionProof:
    task_token_id: bytes         # 16 bytes, from capability token
    payment_hash: bytes          # 32 bytes, binds proof to specific HTLC
    output_hash: bytes           # SHA256 of task output
    execution_timestamp: int     # Unix timestamp (uint32)
    executor_sig: bytes          # BIP-340 Schnorr signature

    def proof_hash(self) -> bytes:
        return tagged_hash(
            "SCRAP/proof/v1",
            self.task_token_id +
            self.payment_hash +
            self.output_hash +
            self.execution_timestamp.to_bytes(4, 'big')
        )

    def verify(self, executor_pubkey: bytes) -> bool:
        return schnorr_verify(
            self.proof_hash(),
            self.executor_sig,
            executor_pubkey
        )
```

**Critical binding**: The `payment_hash` field ensures this proof can only be used to settle the specific HTLC that was locked for this task. Without it, a proof could be replayed against a different payment.

### 12.4 Settlement with Preimage

Upon successful execution:
1. Executor generates ExecutionProof
2. Executor reveals HTLC preimage
3. Customer verifies proof before accepting settlement
4. If dispute, customer has evidence (proof mismatch)

```
Customer                          Executor
    |                                |
    |  proof = ExecutionProof(...)   |
    |<-------------------------------|
    |                                |
    |  verify proof                  |
    |  if valid:                     |
    |    accept HTLC settlement      |
    |  else:                         |
    |    initiate dispute            |
    |                                |
```

---

## 13. HTLC Timeout Analysis for Orbital Scenarios

### 13.1 Timeout Chain Requirements

Multi-hop HTLC chains require decreasing timeouts to prevent routing nodes from being stuck with unresolvable HTLCs:

```
+-----------------------------------------------------------------------------+
|                    HTLC TIMEOUT CHAIN                                        |
+-----------------------------------------------------------------------------+
|                                                                             |
|  For N-hop route, timeout at hop i must exceed timeout at hop i+1           |
|  by at least: block_time * safety_margin                                    |
|                                                                             |
|  Example (3-hop, 144-block margin per hop = ~24 hours):                     |
|                                                                             |
|  Customer --> Relay-1 --> Relay-2 --> Executor                              |
|  T=432 blk    T=288 blk   T=144 blk   T=0 (final)                           |
|                                                                             |
|  Total lockup: 432 blocks = ~72 hours                                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 13.2 Orbital Contact Constraints

LEO satellites have intermittent ISL contact windows:

| Orbital Configuration | Contact Window | Gap Between Contacts |
|-----------------------|----------------|----------------------|
| Same-plane adjacent | Near-continuous | Minutes |
| Cross-plane (60° separation) | 5-15 minutes | 40-80 minutes |
| LEO-GEO relay | 40+ minutes | Per orbit |
| LEO-LEO distant | 2-15 minutes | 1-6 hours |

### 13.3 Timeout Selection Guidelines

```
+-----------------------------------------------------------------------------+
|                    TIMEOUT SELECTION                                         |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Variables:                                                                 |
|  - dispute_window: Time for customer to dispute (default: 6 hours)         |
|  - max_contact_gap: Maximum time between ISL opportunities (per route)      |
|  - hops: Number of routing hops                                             |
|  - margin_per_hop: 144 blocks (~24 hours, Lightning convention)             |
|                                                                             |
|  Formula:                                                                   |
|  final_timeout = dispute_window + max_contact_gap + margin_per_hop          |
|  hop_n_timeout = final_timeout + (N - n) * margin_per_hop                   |
|                                                                             |
|  Example (CubeSat testbed, 2-hop):                                          |
|  - dispute_window: 36 blocks (6 hours)                                      |
|  - max_contact_gap: 12 blocks (2 hours, CubeSat ISL)                        |
|  - margin_per_hop: 144 blocks (24 hours)                                    |
|                                                                             |
|  final_timeout = 36 + 12 + 144 = 192 blocks (~32 hours)                     |
|  hop_1_timeout = 192 + 144 = 336 blocks (~56 hours)                         |
|                                                                             |
|  Note: For 2-hop route, customer timeout = hop_1_timeout = 56 hours         |
|  (customer connects directly to first relay hop)                            |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 13.4 CubeSat Testbed Configuration

For single-operator CubeSat constellation:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Hops | 1-2 | Single operator, no cross-federation |
| Dispute window | 6 hours | Ground monitoring cycle |
| Max contact gap | 2 hours | Conservative for CubeSat ISL |
| Margin per hop | 24 hours | Standard Lightning |
| **Max customer timeout** | 56 hours | 2-hop worst case |

**Implication**: HTLCs may be locked for up to 56 hours. Operators must provision channel liquidity accordingly.

### 13.5 Timeout Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Executor misses contact | Proof not delivered within dispute_window | Auto-refund at customer timeout |
| Customer offline | Cannot dispute | Executor claims payment after dispute_window |
| Intermediate node offline | Cannot forward preimage | Upstream nodes claim at their timeout |

---

## 14. CubeSat Testbed Demonstration

The initial demonstration uses **UHF inter-satellite links** on existing CubeSats to prove protocol correctness at low bandwidth:

| Aspect | UHF Demo | Production Target |
|--------|----------|-------------------|
| **ISL Band** | 435-438 MHz (amateur/experimental) | Optical (1550nm) or Ka-band |
| **Data Rate** | ~9.6 kbps | 25+ Gbps |
| **Regulatory** | Amateur/experimental (jurisdiction-dependent) | Per [../future/AGS.md](../future/AGS.md) |

**UHF ISL Capability**:
- ✓ Relay: capability tokens (~1 KB)
- ✓ Relay: signatures and acknowledgments (64-100 bytes)
- ✓ Relay: small data packets, proofs
- ✗ Cannot relay: imagery, bulk sensor data

**What the demo proves**:
- Protocol cryptographic correctness
- Multi-hop onion routing works
- Adaptor signatures bind task to payment
- On-chain PTLC settlement

**What the demo does NOT prove**:
- High-bandwidth data relay (UHF limitation)
- Production latency (depends on ISL technology)
- Imaging/processing task execution (depends on partner capabilities)

### 14.1 Demonstration Objectives

| Objective | Validation Criteria |
|-----------|-------------------|
| Capability token verification | <100ms verify time on OBC |
| HTLC lock during ISL | Successful lock in 5-minute window |
| Task execution | Relay task completes, proof generated |
| Timeout-default settlement | Payment settles without dispute |
| Dispute flow | Customer can block payment with evidence |
| Multi-hop routing | 3+ hop task chain completes |

### 14.2 Constellation Configuration

**Minimum Viable Constellation**: 2-3 CubeSats with UHF ISL

```
+-----------------------------------------------------------------------------+
|                    CUBESAT TESTBED ARCHITECTURE                              |
+-----------------------------------------------------------------------------+
|                                                                             |
|                 Ground Operator Station                                      |
|                         |                                                    |
|           +-------------+-------------+                                      |
|           |                           |                                      |
|           v                           v                                      |
|     +-----------+               +-----------+                                |
|     | CubeSat-1 |<--- ISL ----->| CubeSat-2 |                                |
|     | (Relay)   |               | (Executor)|                                |
|     +-----------+               +-----------+                                |
|           |                           |                                      |
|           |  UHF/S-band ground link   |                                      |
|           +-------------+-------------+                                      |
|                         |                                                    |
|                 Ground Operator Station                                      |
|                                                                             |
|  Lightning channels:                                                         |
|  - Ground <-> CubeSat-1 (pre-funded)                                        |
|  - Ground <-> CubeSat-2 (pre-funded)                                        |
|  - CubeSat-1 <-> CubeSat-2 (via ground triangulation initially)             |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 14.3 Hardware Requirements

| Component | Specification | Candidate |
|-----------|--------------|-----------|
| OBC | ARM Cortex-A, 512MB RAM | Raspberry Pi CM4 (demo) |
| Crypto | Software secp256k1 | libsecp256k1 |
| Storage | 8GB eMMC | Standard |
| ISL | RF or optical | UHF crosslink or COTS laser |
| Ground link | UHF/S-band | Standard CubeSat |

### 14.4 Software Stack

```
+---------------------------+
|     SCRAP Protocol         |  <- Capability tokens, proofs
+---------------------------+
|     LDK (Lightning)       |  <- HTLC management, channels
+---------------------------+
|     libsecp256k1          |  <- Cryptographic primitives
+---------------------------+
|     CCSDS Space Packet    |  <- Framing (optional)
+---------------------------+
|     Linux / RTOS          |
+---------------------------+
```

### 14.5 Lightning Implementation Recommendations

#### 14.5.1 Implementation Comparison

| Implementation | Language | Binary Size | RAM Usage | Embedded Support | Recommendation |
|----------------|----------|-------------|-----------|------------------|----------------|
| **LDK** | Rust | ~2 MB | ~10 MB | Excellent | **Recommended** |
| **ldk-node** | Rust | ~4 MB | ~20 MB | Good | Alternative |
| **Core Lightning (CLN)** | C | ~15 MB | ~50 MB | Poor | Not recommended |
| **LND** | Go | ~30 MB | ~100 MB | Poor | Not recommended |
| **Eclair** | Scala/JVM | ~100 MB | ~200 MB | No | Not suitable |

#### 14.5.2 Why LDK

**Lightning Dev Kit (LDK)** is the recommended implementation for satellite integration:

1. **Modular architecture**: Use only the components needed
   - `lightning` crate: Channel state machine, HTLC management
   - `lightning-persister`: Pluggable storage backend
   - `lightning-net-tokio`: Async networking (replaceable for ISL)
   - `lightning-invoice`: BOLT11 invoice handling

2. **No runtime dependencies**:
   - No external database (SQLite optional)
   - No background daemon
   - No RPC server overhead

3. **Custom transport layer**:
   - Replace TCP/IP with ISL framing
   - CCSDS Space Packet encapsulation
   - Store-and-forward compatible

4. **Deterministic operation**:
   - No background threads required
   - Event-driven architecture
   - Predictable memory usage

5. **Rust safety guarantees**:
   - Memory safety without garbage collection
   - No null pointer exceptions
   - Compile-time concurrency checks

#### 14.5.3 LDK Integration Architecture

```
+-----------------------------------------------------------------------------+
|                    LDK SATELLITE INTEGRATION                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  SCRAP Layer                                                                 |
|  +-----------------------------------------------------------------------+  |
|  |  CapabilityTokenVerifier  |  ExecutionProofGenerator  |  Dispatcher  |  |
|  +-----------------------------------------------------------------------+  |
|                                      |                                      |
|                                      v                                      |
|  LDK Layer                                                                  |
|  +-----------------------------------------------------------------------+  |
|  |                         ChannelManager                                |  |
|  |  +------------------+  +------------------+  +------------------+     |  |
|  |  | Channel 1        |  | Channel 2        |  | Channel N        |     |  |
|  |  | (Ground-Sat1)    |  | (Sat1-Sat2)      |  | (SatN-Ground)    |     |  |
|  |  +------------------+  +------------------+  +------------------+     |  |
|  +-----------------------------------------------------------------------+  |
|                                      |                                      |
|  +------------------+  +------------------+  +------------------+           |
|  | KeysManager      |  | Persister        |  | FeeEstimator     |           |
|  | (RAM keys)       |  | (NVM storage)    |  | (static fees)    |           |
|  +------------------+  +------------------+  +------------------+           |
|                                      |                                      |
|  Transport Layer                                                            |
|  +-----------------------------------------------------------------------+  |
|  |  ISLMessageRouter                                                     |  |
|  |  +------------------+  +------------------+  +------------------+     |  |
|  |  | ISL TX Queue     |  | ISL RX Queue     |  | Store-Forward   |     |  |
|  |  +------------------+  +------------------+  +------------------+     |  |
|  +-----------------------------------------------------------------------+  |
|                                                                             |
+-----------------------------------------------------------------------------+
```

#### 14.5.4 Key LDK Customizations for Space

**1. Custom Persister (NVM-backed)**:
```rust
// LDK 0.0.123+ API (December 2024)
use lightning::sign::ecdsa::EcdsaChannelSigner;
use lightning::chain::chainmonitor::Persist;
use lightning::chain::ChannelMonitorUpdateStatus;

struct SatellitePersister {
    nvm: NonVolatileMemory,
    write_cache: HashMap<String, Vec<u8>>,
}

impl<Signer: EcdsaChannelSigner> Persist<Signer> for SatellitePersister {
    fn persist_new_channel(
        &self,
        channel_id: OutPoint,
        data: &ChannelMonitor<Signer>,
    ) -> ChannelMonitorUpdateStatus {
        let encoded = data.encode();
        match self.nvm.write(&format!("chan_{}", channel_id), &encoded) {
            Ok(_) => ChannelMonitorUpdateStatus::Completed,
            Err(_) => ChannelMonitorUpdateStatus::UnrecoverableError,
        }
    }

    fn update_persisted_channel(
        &self,
        channel_id: OutPoint,
        _update: Option<&ChannelMonitorUpdate>,
        data: &ChannelMonitor<Signer>,
    ) -> ChannelMonitorUpdateStatus {
        // For space applications, always persist full state (not incremental)
        self.persist_new_channel(channel_id, data)
    }

    fn archive_persisted_channel(&self, channel_id: OutPoint) {
        let _ = self.nvm.delete(&format!("chan_{}", channel_id));
    }
}
```

**2. Custom MessageRouter (ISL transport)**:
```rust
struct ISLMessageRouter {
    isl_interface: ISLInterface,
    pending_messages: VecDeque<(PublicKey, Message)>,
}

impl MessageSendEventsProvider for ISLMessageRouter {
    fn get_and_clear_pending_msg_events(&self) -> Vec<MessageSendEvent> {
        // Queue messages for next ISL contact window
    }
}

impl RoutingMessageHandler for ISLMessageRouter {
    // Handle incoming Lightning messages from ISL frames
}
```

**3. Static Fee Estimator**:
```rust
struct SatelliteFeeEstimator;

impl FeeEstimator for SatelliteFeeEstimator {
    fn get_est_sat_per_1000_weight(&self, _target: ConfirmationTarget) -> u32 {
        // Use conservative static fee (10 sat/vbyte = 2500 sat/kw)
        // Ground station updates via uplink during contacts
        2500
    }
}
```

**4. Event-Driven Processing**:
```rust
// LDK 0.0.123+ API (December 2024)
use lightning::events::{Event, PaymentPurpose};

fn process_ldk_events(
    channel_manager: &ChannelManager,
    isl: &ISLInterface,
    scap_handler: &ScapHandler,
) {
    // Called during each ISL contact window
    for event in channel_manager.get_and_clear_pending_events() {
        match event {
            // PaymentClaimable replaced PaymentReceived in LDK 0.0.118+
            Event::PaymentClaimable {
                payment_hash,
                amount_msat,
                purpose,
                ..
            } => {
                // Extract payment preimage from purpose
                let preimage = match purpose {
                    PaymentPurpose::Bolt11InvoicePayment { payment_preimage, .. } => {
                        payment_preimage
                    }
                    _ => None,
                };

                if let Some(preimage) = preimage {
                    // Verify associated capability token
                    // Execute task
                    // Generate proof
                    // Claim payment
                    channel_manager.claim_funds(preimage);
                } else {
                    // Cannot claim without preimage - fail the HTLC
                    channel_manager.fail_htlc_backwards(&payment_hash);
                }
            }

            Event::PaymentClaimed { payment_hash, amount_msat, .. } => {
                // Payment successfully claimed - log for accounting
                log::info!("Payment claimed: {} for {} msat",
                    hex::encode(payment_hash.0), amount_msat);
            }

            Event::PaymentSent { payment_preimage, payment_hash, .. } => {
                // Outgoing payment succeeded - store preimage as receipt
                log::info!("Payment sent: {}", hex::encode(payment_hash.0));
            }

            Event::ChannelClosed { channel_id, reason, .. } => {
                // Handle force-close, may need ground intervention
                log::warn!("Channel {} closed: {:?}",
                    hex::encode(channel_id.0), reason);
                scap_handler.notify_ground_station_channel_closed(channel_id);
            }

            _ => {}
        }
    }
}
```

#### 14.5.5 Channel Management Strategy

**Pre-flight Setup**:
1. Open channels between ground and each satellite (on-chain)
2. Fund channels with 6-month operational capacity
3. Store channel state snapshots in satellite NVM

**In-flight Operations**:
| Scenario | Action |
|----------|--------|
| Normal payment | Update channel state, persist to NVM |
| Inbound capacity depleted | Ground initiates splice-in (requires contact) |
| Outbound capacity depleted | Route through alternative channel |
| Channel force-closed | Ground monitors, resolves on-chain |
| Peer offline > 2 weeks | Consider cooperative close at next contact |

**Ground Station Role**:
- Watchtower for all satellite channels
- Fee estimation updates via uplink
- Channel rebalancing during contacts
- On-chain transaction broadcasting

#### 14.5.6 Alternatives Considered

**Core Lightning (CLN) Plugins**:
- Pro: C implementation, smaller than LND
- Con: Requires full daemon, RPC overhead, not designed for embedded
- Verdict: Not suitable for resource-constrained OBC

**Custom Minimal Implementation**:
- Pro: Smallest possible footprint
- Con: Months of development, security risk, no ecosystem support
- Verdict: Not recommended; LDK provides sufficient flexibility

**Offloading to Ground**:
- Pro: Simpler on-board software
- Con: Requires ground contact for every payment, defeats purpose
- Verdict: Hybrid approach possible (ground holds keys, satellite holds state)

### 14.6 Test Scenarios

**Scenario 1: Direct Task Execution**
- CubeSat-1 submits task to CubeSat-2
- CubeSat-2 executes, returns proof
- Payment settles via timeout-default

**Scenario 2: Relay Task**
- Ground submits task via CubeSat-1 to CubeSat-2
- 2-hop HTLC chain
- CubeSat-2 executes, preimage propagates back

**Scenario 3: Dispute**
- CubeSat-2 provides invalid proof
- Ground operator disputes
- HTLC times out, funds return to sender

### 14.7 Success Metrics

| Metric | Target |
|--------|--------|
| Token verification latency | <100ms |
| HTLC lock latency | <500ms |
| End-to-end task latency | <30 minutes |
| Settlement success rate | >95% |
| Dispute resolution | 100% correct outcome |

---

## 15. PTLC Future Enhancement

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

## 16. Transport Bindings

SCRAP is **transport-agnostic**. The core protocol (capability tokens, task messages, proofs, Lightning messages) is independent of the underlying transport layer. This section defines bindings for specific transports.

### 16.1 Transport Independence

SCRAP messages have a common structure regardless of transport:

```
SCRAP Message (transport-independent):
+----------------+--------+----------------------------------------+
| SCRAP Msg Type  | Length | SCRAP Message Body (TLV-encoded)        |
| 1 byte         | 2 bytes| Variable (≤65535 bytes)                |
+----------------+--------+----------------------------------------+
```

Each transport binding specifies how this message is framed, secured, and delivered. Implementations MUST support at least one binding; multiple bindings MAY be supported for interoperability.

| Binding | Use Case | Security | Typical Deployment |
|---------|----------|----------|-------------------|
| SISL | Direct ISL | X3DH + AES-GCM | Production ISL |
| SPP | CCSDS infrastructure | SDLS or application-layer | NASA/ESA missions |
| AX.25 | Amateur/CubeSat | Application-layer | Phase 1 testbed |
| IP/UDP | Commercial relay | TLS or application-layer | Starlink, ground |

### 16.2 SISL Binding (Default for ISL)

When operating over SISL (Secure Inter-Satellite Link), SCRAP messages are carried in SISL frame payloads. SISL provides link-layer security (X3DH authentication, AES-256-GCM encryption).

**Protocol Stack:**

```
+-----------------------------------------------------------------------------+
|                    SCRAP OVER SISL PROTOCOL STACK                             |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Layer 7: SCRAP Application                                                  |
|  +-----------------------------------------------------------------------+  |
|  |  Capability Tokens | Task Requests | Proofs | Lightning Messages      |  |
|  +-----------------------------------------------------------------------+  |
|                                      |                                      |
|                                      v                                      |
|  Layer 6: SISL Security Sublayer                                            |
|  +-----------------------------------------------------------------------+  |
|  |  X3DH Key Agreement | AES-256-GCM Encryption | Anti-replay             |  |
|  +-----------------------------------------------------------------------+  |
|                                      |                                      |
|                                      v                                      |
|  Layer 5: SISL Data Services                                                |
|  +-----------------------------------------------------------------------+  |
|  |  Fragmentation | Selective ARQ | Sequenced Delivery                   |  |
|  +-----------------------------------------------------------------------+  |
|                                      |                                      |
|                                      v                                      |
|  Layers 1-4: SISL Physical + Coding + MAC + Frame                           |
|  +-----------------------------------------------------------------------+  |
|  |  Spread Spectrum | FEC | CRC-32C | ISL RF                             |  |
|  +-----------------------------------------------------------------------+  |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Frame Format:**

```
SISL Frame:
+-------+------------+-----+----+---------------------+----------+----------+
| ASM   | Frame Hdr  | Seq | IV | SCRAP Message        | Auth Tag | CRC-32C  |
| 4 B   | 4 B        | 4 B |12 B| ≤2000 bytes         | 16 B     | 4 B      |
+-------+------------+-----+----+---------------------+----------+----------+
```

SISL provides: authentication, encryption, integrity, replay protection, and fragmentation. SCRAP messages are simply placed in the payload field.

### 16.3 SPP Binding (CCSDS 133.0-B)

For CCSDS-compliant missions, SCRAP messages are encapsulated in Space Packets per CCSDS 133.0-B-2.

**Packet Format:**

```
Space Packet with SCRAP Payload:
+-----------------------------------------------------------------------------+
| Primary Header (6 bytes)                                                     |
| +-- Version Number: 000 (always)                                            |
| +-- Packet Type: 1 (TC) for requests, 0 (TM) for responses                  |
| +-- Secondary Header Flag: 1                                                 |
| +-- APID: Allocated for SCRAP (operator-assigned, recommend 0x100-0x1FF)     |
| +-- Sequence Flags: 11 (unsegmented)                                        |
| +-- Packet Sequence Count: 0-16383 (rolling)                                |
| +-- Packet Data Length: (total length - 7)                                  |
+-----------------------------------------------------------------------------+
| Secondary Header (variable, optional)                                        |
| +-- Timestamp (CCSDS CUC or CDS format)                                     |
+-----------------------------------------------------------------------------+
| User Data Field                                                              |
| +-- SCRAP Message (Type + Length + TLV body)                                 |
+-----------------------------------------------------------------------------+
```

**APID Allocation:**
| APID Range | Usage |
|------------|-------|
| 0x100 | SCRAP TaskRequest/TaskAccept/TaskReject |
| 0x101 | SCRAP ProofOfExecution |
| 0x102 | SCRAP DisputeMessage |
| 0x110 | SCRAP LightningMessage |
| 0x111 | SCRAP CapabilityToken |

**Security:** SPP itself provides no security. Use with CCSDS SDLS (355.0-B) for link-layer encryption, or rely on SCRAP's application-layer signatures for authentication.

### 16.4 AX.25 Binding (Amateur/CubeSat)

For CubeSat missions using amateur radio, SCRAP messages are encapsulated in AX.25 UI (Unnumbered Information) frames.

**Frame Format:**

```
AX.25 UI Frame with SCRAP Payload:
+-----------------------------------------------------------------------------+
| Flag: 0x7E                                                                   |
+-----------------------------------------------------------------------------+
| Address Field (14+ bytes)                                                    |
| +-- Destination: Target satellite callsign (e.g., "CUBES1-0")              |
| +-- Source: Commander satellite callsign (e.g., "CUBES2-0")                |
| +-- Digipeaters: Optional relay path                                        |
+-----------------------------------------------------------------------------+
| Control: 0x03 (UI frame)                                                     |
+-----------------------------------------------------------------------------+
| PID: 0xF0 (no layer 3)                                                       |
+-----------------------------------------------------------------------------+
| Information Field                                                            |
| +-- SCRAP Message (Type + Length + TLV body)                                 |
| +-- Maximum 256 bytes recommended for UHF                                   |
+-----------------------------------------------------------------------------+
| FCS: 16-bit CRC-CCITT                                                        |
+-----------------------------------------------------------------------------+
| Flag: 0x7E                                                                   |
+-----------------------------------------------------------------------------+
```

**Callsign Mapping:** Satellite NORAD ID maps to callsign via operator's amateur license. Example: NORAD 51070 → "ICEYE1-0".

**Security:** AX.25 provides no encryption (regulatory requirement for amateur). SCRAP capability token signatures provide authentication. For sensitive operations, use licensed spectrum with SISL binding instead.

**Fragmentation:** Large SCRAP messages (>256 bytes) should be fragmented at the application layer. Include fragment sequence numbers in a SCRAP extension field.

### 16.5 IP/UDP Binding (Commercial Relay)

For commercial relay services (Starlink, AWS Ground Station, etc.), SCRAP messages are carried over IP/UDP.

**Packet Format:**

```
UDP Datagram with SCRAP Payload:
+-----------------------------------------------------------------------------+
| IP Header (20 bytes, IPv4)                                                   |
+-----------------------------------------------------------------------------+
| UDP Header (8 bytes)                                                         |
| +-- Source Port: Ephemeral                                                  |
| +-- Destination Port: 7227 (SCRAP default, "SCRAP" on phone keypad)          |
| +-- Length: UDP header + SCRAP message                                       |
| +-- Checksum                                                                |
+-----------------------------------------------------------------------------+
| UDP Payload                                                                  |
| +-- SCRAP Message (Type + Length + TLV body)                                 |
+-----------------------------------------------------------------------------+
```

**Port Assignment:** Default port 7227 (mnemonic: "SCRAP"). Operators MAY use alternate ports.

**Security:** UDP provides no security. Options:
1. **DTLS 1.3**: Recommended for ground-to-ground relay
2. **Application-layer**: SCRAP signatures sufficient for authentication; add encryption wrapper if confidentiality needed
3. **VPN/IPsec**: If operating over private network

**MTU Considerations:** UDP over satellite relay may have restricted MTU. Fragment SCRAP messages if needed; use SCRAP extension field for reassembly.

### 16.6 Key Sharing (SISL Binding)

When using the SISL binding, SCRAP and SISL share cryptographic infrastructure:

| Key Type | SISL Usage | SCRAP Usage |
|----------|------------|------------|
| Identity key (`m/7227'/0'/sat_id'/0/0`) | X3DH static key | Capability token verification, proof signing |
| Ephemeral keys | X3DH session establishment | Not used (SISL handles) |
| Session keys | Link encryption (AES-GCM) | Not used (SISL handles) |

**Single Key Benefit**: Satellites maintain one identity key pair for both link authentication and application-layer authorization. This simplifies key management but requires that:
1. The identity key is protected with the same rigor as SISL requires
2. Key compromise affects both SISL links and SCRAP authorizations

### 16.7 Session Lifecycle (SISL Binding)

```
SISL establishes                SCRAP operates over
authenticated link              encrypted channel
       |                              |
       v                              v
+-------------+                +----------------+
|   IDLE      |                | Waiting for    |
|             |                | SISL session   |
+------+------+                +-------+--------+
       |                               |
       | SISL Hail/ACK                 |
       | (X3DH key agreement)          |
       v                               |
+-------------+                        |
| SISL        |<-----------------------+
| LINK_READY  |
+------+------+
       |
       | SISL P2P channel established
       v
+-------------+                +----------------+
| SISL        |  Task Request  | SCRAP           |
| P2P_ACTIVE  |<-------------->| Task-Payment   |
|             |  over SISL     | Protocol       |
+------+------+                +----------------+
       |
       | Session complete or timeout
       v
+-------------+
|   IDLE      |
+-------------+
```

### 16.8 Trust List Alignment (SISL Binding)

SISL trust lists and SCRAP capability tokens use the same identity keys:

- **SISL trust list**: `{norad_id: pubkey}` mappings for link-layer authentication
- **SCRAP capability token**: `cmd_pub` field contains the same identity pubkey

A satellite MUST verify that:
1. The ISL peer's SISL identity matches a trust list entry
2. The capability token's `cmd_pub` matches the SISL-authenticated peer identity

```python
def verify_scap_request_over_sisl(
    sisl_session: SISLSession,
    scap_request: TaskRequest,
) -> bool:
    """Verify SCRAP request came from authenticated SISL peer."""

    # Get SISL-authenticated peer identity
    peer_pubkey = sisl_session.peer_identity_pubkey

    # Verify capability token
    if not verify_capability_token(scap_request.capability_token, self):
        return False

    # Verify token's commander matches SISL peer
    if scap_request.capability_token.commander_pubkey != peer_pubkey:
        return False

    return True
```

### 16.9 Timing Considerations (SISL Binding)

SISL sessions have limited duration (ISL contact window). SCRAP must complete within this window:

| Phase | Typical Duration | SISL Dependency |
|-------|------------------|-----------------|
| SISL handshake | 100-500ms | Required first |
| SCRAP task negotiation | 200-500ms | Over SISL P2P |
| Task execution | 1-300s | SISL may timeout |
| Proof + settlement | 200-500ms | Over SISL P2P |

**If SISL session ends before SCRAP completes**:
- HTLC remains locked until timeout
- Proof can be delivered via alternate path (different ISL contact, ground relay)
- Settlement completes when parties reconnect or via timeout-default

---

## 17. References

### Standards
- CCSDS 133.0-B-2 Space Packet Protocol
- CCSDS 355.0-B-2 Space Data Link Security
- ECSS-E-ST-70-41C Packet Utilization Standard
- AX.25 Link Access Protocol for Amateur Packet Radio (v2.2)

### Lightning Network
- [BOLT 2: Peer Protocol](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md)
- [BOLT 3: Transactions](https://github.com/lightning/bolts/blob/master/03-transactions.md)
- [BOLT 4: Onion Routing](https://github.com/lightning/bolts/blob/master/04-onion-routing.md)
- [BOLT 11: Invoice Protocol](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md)

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/)
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)

### Cryptographic Primitives
- [FROST: Flexible Round-Optimized Schnorr Threshold Signatures](https://eprint.iacr.org/2020/852)
- [ROAST: Robust Asynchronous Schnorr Threshold Signatures](https://eprint.iacr.org/2022/550)
- [BIP-340: Schnorr Signatures for secp256k1](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki)
- [BIP-327: MuSig2](https://github.com/bitcoin/bips/blob/master/bip-0327.mediawiki)

### Academic
- Choi et al., "Consensus-Based Decentralized Auctions for Robust Task Allocation" (MIT)
- UCAN Specification: https://ucan.xyz/

### SCRAP Extensions
- [ADVERSARIAL.md](ADVERSARIAL.md) - Military/contested environment considerations
- [SISL.md](SISL.md) - Secure Inter-Satellite Link (CCSDS integration)
- [BIP-SCRAP.md](BIP-SCRAP.md) - Informational BIP

---

## 18. Test Vectors

Test vectors for interoperability testing. All values in hexadecimal unless noted.

### 18.1 Token ID Generation

The TLV format uses 16-byte binary `token_id`. For logs and APIs, a string
representation may be used:

```
TEST VECTOR 1: Token ID Generation
==================================

Input:
  issuer_prefix = "ESA"
  timestamp = 1705320000 (2025-01-15T12:00:00Z)
  random_bytes = 0xa1b2c3d4e5f6789012345678abcdef01

TLV token_id (16 bytes):
  0xa1b2c3d4e5f6789012345678abcdef01

String format (for logs/APIs):
  "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01"
```

### 18.2 Capability Token Encoding

```
TEST VECTOR 2: TLV-Encoded Capability Token
===========================================

Input values:
  issuer_pubkey = 0x02a1b2c3d4e5f67890123456789abcdef01234567890abcdef01234567890abcd
  subject = "ICEYE-X14-51070" (UTF-8)
  audience = "SENTINEL-2C-62261" (UTF-8)
  issued_at = 1705320000 (0x65a51e40)
  expires_at = 1705406400 (0x65a66bc0)
  token_id = 0xa1b2c3d4e5f6789012345678abcdef01 (16 bytes)
  capability = "cmd:imaging:msi" (UTF-8)

TLV Encoding (excluding signature):
  00 01 01                                           # type=0, len=1, version=1
  02 21 02a1b2c3d4e5f67890123456789abcdef01234567890abcdef01234567890abcd
                                                     # type=2, len=33, issuer
  04 0f 494345 59452d 5831342d3531303730           # type=4, len=15, subject
  06 11 53454e 54494e 454c2d32432d3632323631       # type=6, len=17, audience
  08 04 65a51e40                                     # type=8, len=4, issued_at
  0a 04 65a66bc0                                     # type=10, len=4, expires_at
  0c 10 a1b2c3d4e5f6789012345678abcdef01             # type=12, len=16, token_id
  0e 0f 636d643a696d6167696e673a6d7369               # type=14, len=15, capability

Concatenated (hex, 107 bytes before signature):
  000101022102a1b2c3d4e5f67890123456789abcdef01234567890abcdef01234567890abcd
  040f49434559452d5831342d3531303730061153454e54494e454c2d32432d36323236
  310804 65a51e400a0465a66bc00c10a1b2c3d4e5f6789012345678abcdef010e0f636d
  643a696d6167696e673a6d7369

Signature input (tagged hash):
  tag = "SCRAP/token/v1"
  message = tagged_hash(tag, <TLV bytes above>)

Signature (BIP-340 Schnorr, 64 bytes):
  f0 40 <64-byte-schnorr-signature>

Total token size: 107 + 3 + 64 = 174 bytes
```

### 18.3 Payment-Capability Binding

```
TEST VECTOR 3: Binding Hash (Domain Separated)
==============================================

Tagged hash function (BIP-340 style):
  tagged_hash(tag, msg) = SHA256(SHA256(tag) || SHA256(tag) || msg)

Input:
  token_id = 0xa1b2c3d4e5f6789012345678abcdef01 (16 bytes, from TLV type 12)
  payment_hash = 0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

Binding (domain-separated):
  binding_msg = token_id || payment_hash  (48 bytes total)
  binding_hash = tagged_hash("SCRAP/binding/v1", binding_msg)

Computation:
  tag = "SCRAP/binding/v1"
  tag_hash = SHA256(tag.encode('utf-8'))
  binding_hash = SHA256(tag_hash || tag_hash || binding_msg)

Output:
  binding_hash = 0x77b72bb25ba9fbf110799924773bae55bca6834f8d34f9bf431a4a0430b32ff1

Note: The binding uses the 16-byte token_id (TLV type 12), not the
string format. This provides a fixed-size binding input.
```

### 18.4 Execution Proof

```
TEST VECTOR 4: Execution Proof Hash (Domain Separated)
======================================================

Tag precomputation:
  tag = "SCRAP/proof/v1"
  tag_hash = SHA256(tag.encode('utf-8'))

Input:
  task_token_id = 0xa1b2c3d4e5f6789012345678abcdef01 (16 bytes)
  payment_hash = 0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  output_hash = 0xfedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210
  execution_timestamp = 1705320045
  execution_timestamp (big-endian, 4 bytes) = 0x65a51e6d

Proof hash (domain-separated):
  proof_msg = task_token_id +
              payment_hash +
              output_hash +
              execution_timestamp.to_bytes(4, 'big')
  proof_hash = tagged_hash("SCRAP/proof/v1", proof_msg)
             = SHA256(tag_hash || tag_hash || proof_msg)

Output:
  proof_hash = 0x0b2656da895e0f245df96830f33fff12414b277d7587bf1db2832a06fab22982

Note: Uses the 16-byte binary token_id, not the string format.
```

### 18.5 BIP-32 Key Derivation

```
TEST VECTOR 5: SCRAP Key Derivation Path
=======================================

Input:
  master_seed = 0x000102030405060708090a0b0c0d0e0f (16 bytes, for testing only!)
  satellite_norad = 51070

BIP-32 Master Key (from seed via HMAC-SHA512 with key "Bitcoin seed"):
  Master secret (IL): 0xe8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35
  Master chain code (IR): 0x873dff81c02f525623fd1fe5167eac3a55a049de3d314bb42ee227ffed37d508

Hardened Derivation Indices:
  7227' = 7227 + 0x80000000 = 2147490875 (0x80001c3b)
  0'    = 0 + 0x80000000    = 2147483648 (0x80000000)
  51070' = 51070 + 0x80000000 = 2147534718 (0x8000c77e)

Derivation paths:
  Identity key:       m/7227'/0'/51070'/0/0
  Channel key 0:      m/7227'/0'/51070'/1/0
  Channel key 1:      m/7227'/0'/51070'/1/1
  Session epoch 0:    m/7227'/0'/51070'/2/0

Note: Full key derivation requires secp256k1 point multiplication.
Use a BIP-32 library (bip32, bip_utils, python-hdwallet) with the
master key above to compute derived keys for your implementation.
```

### 18.6 Reference Implementation

```python
#!/usr/bin/env python3
"""SCRAP Test Vector Generator - Verified"""

import hashlib
import hmac

def generate_token_id() -> bytes:
    """Generate unique 16-byte token ID."""
    # Fixed for test vector; in production use secrets.token_bytes(16)
    return bytes.fromhex("a1b2c3d4e5f6789012345678abcdef01")

def token_id_to_string(token_id: bytes, issuer_prefix: str, timestamp: int) -> str:
    """Convert binary token_id to string format for logs/APIs."""
    return f"{issuer_prefix}-{timestamp}-{token_id.hex()}"

def tagged_hash(tag: str, msg: bytes) -> bytes:
    """BIP-340 style tagged hash with domain separation."""
    tag_hash = hashlib.sha256(tag.encode('utf-8')).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()

def compute_binding_hash(token_id: bytes, payment_hash: bytes) -> bytes:
    """Compute payment-capability binding hash (domain separated)."""
    return tagged_hash("SCRAP/binding/v1", token_id + payment_hash)

def compute_proof_hash(task_token_id: bytes, payment_hash: bytes,
                       output_hash: bytes, timestamp: int) -> bytes:
    """Compute execution proof hash (domain separated)."""
    msg = task_token_id + payment_hash + output_hash + timestamp.to_bytes(4, 'big')
    return tagged_hash("SCRAP/proof/v1", msg)

def compute_bip32_master(seed: bytes) -> tuple[bytes, bytes]:
    """Compute BIP-32 master key from seed."""
    I = hmac.new(b'Bitcoin seed', seed, hashlib.sha512).digest()
    return I[:32], I[32:]  # master_secret, chain_code

if __name__ == "__main__":
    # Test Vector 1: Token ID
    token_id = generate_token_id()
    assert token_id.hex() == "a1b2c3d4e5f6789012345678abcdef01"

    # String format for logs
    token_str = token_id_to_string(token_id, "ESA", 1705320000)
    assert token_str == "ESA-1705320000-a1b2c3d4e5f6789012345678abcdef01"

    # Test Vector 3: Binding hash (domain separated)
    payment_hash = bytes.fromhex(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    )
    binding = compute_binding_hash(token_id, payment_hash)
    assert binding.hex() == "77b72bb25ba9fbf110799924773bae55bca6834f8d34f9bf431a4a0430b32ff1"

    # Test Vector 4: Proof hash (domain separated)
    output_hash = bytes.fromhex(
        "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    )
    proof = compute_proof_hash(token_id, payment_hash, output_hash, 1705320045)
    assert proof.hex() == "0b2656da895e0f245df96830f33fff12414b277d7587bf1db2832a06fab22982"

    # Test Vector 5: BIP-32 master key
    seed = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    master_secret, chain_code = compute_bip32_master(seed)
    assert master_secret.hex() == "e8f32e723decf4051aefac8e2c93c9c5b214313817cdb01a1494b917c8436b35"
    assert chain_code.hex() == "873dff81c02f525623fd1fe5167eac3a55a049de3d314bb42ee227ffed37d508"

    print("All SCRAP test vectors verified!")
```
