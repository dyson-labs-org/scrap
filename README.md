# SCAP: Satellite Capability and Payment Protocol

A protocol specification for trustless inter-satellite task execution combining cryptographic capability tokens (SAT-CAP) with Bitcoin Lightning payments.

SCAP complements **SISL** (Secure Inter-Satellite Link) at the link layer.

## Status

**Current Phase**: Specification development for CubeSat testbed demonstration

**Target**: Flight demonstration on CubeSat constellation with ISL capability

## Overview

SCAP enables satellites to:
- **Authorize tasks** via delegated capability tokens (ECDSA-signed, CBOR-encoded)
- **Pay for services** using Bitcoin Lightning HTLCs during ISL contact windows
- **Route tasks** through multi-hop satellite constellations with capability attenuation
- **Settle payments** atomically with cryptographic proof-of-execution

---

## Document Index

### Normative Specifications

| Document | Status | Description |
|----------|--------|-------------|
| [SCAP.md](SCAP.md) | **Primary** | Unified protocol specification |
| [PROPOSAL_HTLC.md](PROPOSAL_HTLC.md) | Normative | Lightning HTLC payment protocol |
| [PROPOSAL_CHANNELS.md](PROPOSAL_CHANNELS.md) | Normative | Lightning channel management for satellites |
| [PROPOSAL_PTLC.md](PROPOSAL_PTLC.md) | Future | PTLC upgrade path (pending Lightning adoption) |

### Informative Research

| Document | Description | Informs |
|----------|-------------|---------|
| [CNC_RESEARCH.md](CNC_RESEARCH.md) | Satellite C2 protocols survey (CCSDS, PUS, SDLS) | SCAP §2-4 |
| [PAYMENT_RESEARCH.md](PAYMENT_RESEARCH.md) | Bitcoin L2 technologies for satellites | PROPOSAL_HTLC, payment binding |

### Future / Illustrative

| Document | Description | Status |
|----------|-------------|--------|
| [PROPOSAL_AUCTION.md](PROPOSAL_AUCTION.md) | Distributed auction (CBBA) for task allocation | Future capability |
| [AGS_PROPOSAL.md](AGS_PROPOSAL.md) | Artificial Ground Station relay constellation | Requires ITU X-band allocation (WRC-27+) |

### Document Dependencies

```
                    +------------------+
                    |    SCAP.md       |  <-- Primary specification
                    |   (Normative)    |
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                   |                   |
         v                   v                   v
+----------------+  +----------------+  +----------------+
| PROPOSAL_HTLC  |  | PROPOSAL_      |  | PROPOSAL_PTLC  |
| (Payment)      |  | CHANNELS       |  | (Future)       |
+-------+--------+  +----------------+  +----------------+
        |
        | informed by
        v
+----------------+     +----------------+
| PAYMENT_       |     | CNC_RESEARCH   |
| RESEARCH       |     | (C2 Protocols) |
| (Informative)  |     | (Informative)  |
+----------------+     +----------------+
```

---

## Cryptographic Architecture

**Default: secp256k1 only** for all operations (SISL link layer, SCAP application layer, Lightning payments).

| Operation | Curve | Notes |
|-----------|-------|-------|
| SISL X3DH key agreement | secp256k1 | Link-layer authentication |
| Capability tokens | secp256k1 | Task authorization |
| Lightning HTLCs | secp256k1 | **Mandatory** (Bitcoin requires it) |
| Proof-of-execution | secp256k1 | Settlement signatures |

**Rationale**: Single key hierarchy simplifies provisioning and reduces attack surface. All ECC operations are infrequent enough for software implementation (libsecp256k1). No space-grade HSM supports secp256k1 natively; hardware acceleration requires FPGA soft cores.

**P-256 option**: May be used for SISL link authentication only when FIPS 140-2/3 compliance or CCSDS SDLS interoperability is contractually required. Never used for payment operations.

See [SCAP.md §11.1](SCAP.md#111-elliptic-curve-selection) for hardware options and detailed guidance.

---

## Payment Architecture

**Critical insight: Operators handle payments, not satellites.**

Satellite-to-satellite Lightning channels don't work due to sparse, intermittent ISL connectivity. Multi-hop Lightning requires real-time coordination (milliseconds), but ISL windows are 2-15 minutes every ~90 minutes in LEO.

**Solution**: Operators maintain Lightning channels on the ground. Satellites execute tasks; operators settle payments.

```
TASK LAYER (Space):          Sat_B ──ISL──► Sat_C ──ISL──► Sat_D
                             (Op_X)         (Op_Y)         (Op_Z)

PAYMENT LAYER (Ground):      Gateway ──► Op_X ──► Op_Y ──► Op_Z
                                     (Lightning channels)

Task routing: Store-and-forward via ISL (hours acceptable)
Payment routing: Standard Lightning (milliseconds, operators online)
```

**Benefits**:
- Tasks start immediately (no on-chain wait)
- Payment settles in <1 second (operators always online)
- No on-chain transaction per task (channel reuse)
- Same adaptor signature atomicity (task completion = payment release)

See [PROPOSAL_CHANNELS.md §2](PROPOSAL_CHANNELS.md#2-architecture) for detailed architecture.

---

## Demonstration Target

### Phase 1: UHF CubeSat Protocol Demonstration

Demonstrate protocol correctness using existing CubeSats with **UHF ISL** (435-438 MHz):

| What It Proves | What It Cannot Prove |
|----------------|---------------------|
| Capability token verification | High-bandwidth data relay |
| Onion-routed task bundles | Production latency |
| Adaptor signature binding | Imaging/processing tasks |
| On-chain PTLC settlement | - |
| Multi-hop acknowledgment | - |

**UHF ISL limitations (~9.6 kbps)**:
- ✓ Relay: tokens (~1KB), signatures (64B), acks, proofs
- ✗ Cannot relay: imagery, bulk sensor data

**UHF ISL band**: Already allocated for inter-satellite service (no regulatory barrier)

See [SCAP.md §14](SCAP.md#14-cubesat-testbed-demonstration) for testbed architecture.

### Phase 2: Production ISL Deployment

Multi-operator demonstration with optical or Ka-band ISL:
1. Operator-to-operator Lightning channels
2. Multi-hop task routing (satellites)
3. Multi-hop payment routing (operators)
4. High-bandwidth data relay
5. Atomic settlement via adaptor signatures

---

## User Stories

Twelve scenarios demonstrating the protocol across different satellite operations:

| # | Scenario | Key Features | Complexity |
|---|----------|--------------|------------|
| 01 | [Emergency Maritime SAR](user_stories/01_emergency_maritime_sar.md) | Multi-hop relay, SAR imaging | Medium |
| 02 | [Wildfire Hyperspectral](user_stories/02_wildfire_hyperspectral.md) | Emergency authorization, CBBA auction | High |
| 03 | [Agricultural Multi-hop](user_stories/03_agricultural_multihop.md) | Delegation chains, orbital data center | High |
| 04 | [Volcanic Ash LIDAR](user_stories/04_lidar_cross_operator.md) | Cross-operator federation | High |
| 05 | [Ship Tracking AIS](user_stories/05_ship_tracking_ais.md) | Coordinated collection | Low |
| 06 | [Methane Detection](user_stories/06_methane_auction.md) | Two-phase auction | Medium |
| 07 | [GNSS Radio Occultation](user_stories/07_gnss_radio_occultation.md) | Constellation coordination | Medium |
| 08 | [GEO Relay Imaging](user_stories/08_geo_relay_imaging.md) | Optical ISL, emergency response | Medium |
| 09 | [Debris Inspection RPO](user_stories/09_debris_inspection_rpo.md) | Proximity operations, constraints | High |
| 10 | [Satellite Servicing](user_stories/10_satellite_servicing_rpo.md) | Docking authorization | High |
| 11 | [Disaster Response](user_stories/11_disaster_response_multi_constellation.md) | Multi-constellation coordination | High |
| 12 | [Orbital Data Center](user_stories/12_orbital_data_center.md) | On-orbit processing, data routing | Medium |

**CubeSat Testbed Candidates**: Stories 01, 05, 07 (single-operator, manageable ISL geometry)

---

## Key Concepts

**Capability Token**: Operator-signed authorization granting specific commands to a satellite
```
iss: Target's operator    cap: ["cmd:imaging:*"]
sub: Commanding satellite cns: {max_range_km: 10}
aud: Target satellite     exp: 1705406400
```

**Delegation Chain**: Multi-hop task routing where each hop attenuates capabilities (child ⊆ parent)

**HTLC Payment**: Hash Time-Locked Contract settling during ISL windows (~340ms protocol overhead)

**Timeout-Default Settlement**: If executor provides proof and no dispute within timeout, payment releases automatically

**Proof-of-Execution**: Cryptographic proof (product hash, executor signature) that releases payment

---

## Protocol Flow

```
TASK FLOW (Space, via ISL):
  Customer ──► Op_X's Sat_B ──ISL──► Op_Y's Sat_C ──ISL──► Op_Z's Sat_D
                  │                      │                      │
              [relay task]          [relay task]          [execute task]
                                                               │
                                                          [proof to ground]

PAYMENT FLOW (Ground, via Lightning):
  Customer ──► Gateway ──► Op_X ──► Op_Y ──► Op_Z
                  │           │        │        │
              [HTLC/PTLC setup, locked to adaptor point T]
                                                 │
                                            [Op_Z signs delivery ack]
                                            [reveals t = s_last]
                                                 │
                  <──────── all payments settle ─┘
```

**Key**: Task routes via satellites (ISL, hours acceptable). Payment routes via operators (Lightning, milliseconds).

---

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Capability token spec | Draft | SCAP.md §2 |
| HTLC payment protocol | Draft | PROPOSAL_HTLC.md |
| Channel management | Draft | PROPOSAL_CHANNELS.md |
| Timeout-default arbiter | Draft | SCAP.md §6.3-6.6 |
| CubeSat testbed design | Draft | SCAP.md §14 |
| Space security model | Draft | SCAP.md §11.2 |
| Test vectors | Complete | test_vectors_computed.json |
| CDDL message schemas | Complete | schemas/scap.cddl |

---

## References

### Standards
- CCSDS 133.0-B-2 Space Packet Protocol
- CCSDS 355.0-B-2 Space Data Link Security
- BOLT 2/3/4/11 Lightning Network Specifications

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/) - Recommended for embedded
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)

### Academic
- Choi et al., "Consensus-Based Decentralized Auctions for Robust Task Allocation" (MIT)
- UCAN Specification: https://ucan.xyz/
