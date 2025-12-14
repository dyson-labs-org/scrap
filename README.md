# Tasklib: Satellite Task Authorization and Payment Protocol

A protocol specification for trustless inter-satellite task execution combining cryptographic capability tokens with Bitcoin Lightning payments.

## Overview

Tasklib enables satellites to:
- **Authorize tasks** via delegated capability tokens (JWT-like, ECDSA-signed)
- **Pay for services** using Bitcoin Lightning HTLCs during ISL contact windows
- **Route tasks** through multi-hop satellite constellations with capability attenuation
- **Settle payments** atomically with cryptographic proof-of-execution

## Documents

| Document | Description |
|----------|-------------|
| [TASKLIB.md](TASKLIB.md) | Unified protocol specification |
| [CNC_RESEARCH.md](CNC_RESEARCH.md) | Satellite C2 protocols survey (CCSDS, PUS, SDLS) |
| [PAYMENT_RESEARCH.md](PAYMENT_RESEARCH.md) | Bitcoin L2 technologies for satellites |
| [PROPOSAL_HTLC.md](PROPOSAL_HTLC.md) | Lightning HTLC payment protocol details |

## User Stories

Twelve scenarios demonstrating the protocol across different satellite operations:

| # | Scenario | Key Features |
|---|----------|--------------|
| 01 | Emergency Maritime SAR | Multi-hop relay, SAR imaging |
| 02 | Wildfire Hyperspectral | Emergency authorization, CBBA auction |
| 03 | Agricultural Multi-hop | Delegation chains, orbital data center |
| 04 | Volcanic Ash LIDAR | Cross-operator federation |
| 05 | Ship Tracking AIS | Coordinated collection |
| 06 | Methane Detection | Two-phase auction (survey + quantification) |
| 07 | GNSS Radio Occultation | Constellation coordination |
| 08 | GEO Relay Imaging | Optical ISL, emergency response |
| 09 | Debris Inspection RPO | Proximity operations, constraint verification |
| 10 | Satellite Servicing | Docking authorization, attitude handover |
| 11 | Disaster Response | Multi-constellation coordination |
| 12 | Orbital Data Center | On-orbit processing, data routing |

## Key Concepts

**Capability Token**: Operator-signed authorization granting specific commands to a satellite
```
iss: Target's operator    cap: ["cmd:imaging:*"]
sub: Commanding satellite cns: {max_range_km: 10}
aud: Target satellite     exp: 1705406400
```

**Delegation Chain**: Multi-hop task routing where each hop attenuates capabilities ($child \subseteq parent$)

**HTLC Payment**: Hash Time-Locked Contract settling during 2-15 minute ISL windows (~340ms protocol overhead)

**Proof-of-Execution**: Cryptographic proof (product hash, executor signature) releasing payment

## Protocol Flow

```
Customer -> Relay Sat -> Target Sat
   |            |            |
   | root_token |  del_1     |  Execute task
   | + payment  |  + payment |  + reveal preimage
   +----------->+----------->+
                             |
   <---------proof-----------+
```
