# SCRAP: Secure Capabilities and Routed Authorization Protocol

A protocol specification for trustless inter-satellite task execution combining cryptographic capability tokens (SAT-CAP) with Bitcoin Lightning payments.

SCRAP complements **SISL** (Secure Inter-Satellite Link) at the link layer.

## Status

**Current Phase**: Specification development for CubeSat testbed demonstration

**Target**: Flight demonstration on CubeSat constellation with ISL capability

**TRL**: 2-3 (Concept formulated, analytical validation in progress)

## Overview

SCRAP enables satellites to:
- **Authorize tasks** via delegated capability tokens (ECDSA-signed, CBOR-encoded)
- **Pay for services** using Bitcoin Lightning HTLCs during ISL contact windows
- **Route tasks** through multi-hop satellite constellations with capability attenuation
- **Settle payments** atomically with cryptographic proof-of-execution

---

## Repository Structure

```
scap/
├── spec/                      # Normative protocol specifications
│   ├── SCRAP.md                #   Primary protocol specification
│   ├── SISL.md                #   Secure Inter-Satellite Link protocol
│   ├── OPERATOR_API.md        #   Operator service API
│   ├── HTLC.md                #   Lightning HTLC payment protocol
│   └── PTLC-FALLBACK.md                #   PTLC upgrade path (future)
│
├── research/                  # Background research documents
│   ├── CNC_RESEARCH.md        #   Satellite C2 protocols survey
│   └── PAYMENT_RESEARCH.md    #   Bitcoin L2 technologies
│
├── future/                    # Future / illustrative extensions
│   ├── CHANNELS.md            #   Lightning channels (LN-Symmetry)
│   ├── AUCTION.md             #   Distributed auction (CBBA)
│   └── AGS.md                 #   Artificial Ground Station
│
├── strategy/                  # Strategy & funding documents
│   ├── ROADMAP.md             #   Development roadmap
│   ├── FUNDING.md             #   Grant opportunities
│   ├── STANDARDIZATION.md     #   CCSDS/ITU standards path
│   ├── REGULATORY.md          #   Spectrum/regulatory
│   └── ACADEMIC.md            #   Academic publications
│
├── presentations/             # Modular markdown presentations
│   ├── common/                #   Shared slides (01_title.md, ...)
│   ├── nasa/                  #   NASA-specific slides
│   ├── darpa/                 #   DARPA-specific slides
│   ├── commercial/            #   Investor-specific slides
│   ├── _theme.css             #   Custom styling
│   └── Makefile               #   Build with reveal-md
│
├── scap-core/                 # Rust: Core token/crypto library
├── scap-lightning/            # Rust: LDK integration for payments
├── scap-ffi/                  # Rust: C FFI bindings
│
├── schemas/                   # CDDL schemas and examples
│   ├── scap.cddl              #   Message format definitions
│   └── examples/              #   Example messages
│
├── test-vectors/              # Cryptographic test vectors
│   ├── computed.json          #   Computed test vectors
│   ├── generate.py            #   Vector generation script
│   └── verify.py              #   Verification script
│
├── user_stories/              # 12 demonstration scenarios
└── scripts/                   # Build and utility scripts
```

---

## Document Index

### Normative Specifications

| Document | Status | Description |
|----------|--------|-------------|
| [spec/SCRAP.md](spec/SCRAP.md) | **Primary** | Unified protocol specification |
| [spec/SISL.md](spec/SISL.md) | **Primary** | Secure Inter-Satellite Link protocol (X3DH, encryption) |
| [spec/OPERATOR_API.md](spec/OPERATOR_API.md) | Normative | Operator service API (token issuance, pubkey distribution) |
| [spec/HTLC.md](spec/HTLC.md) | Normative | Lightning HTLC payment protocol |
| [spec/PTLC-FALLBACK.md](spec/PTLC-FALLBACK.md) | Normative | On-chain PTLC payments (Taproot/Schnorr) |

### Background Research

| Document | Description |
|----------|-------------|
| [research/CNC_RESEARCH.md](research/CNC_RESEARCH.md) | Satellite C2 protocols survey (CCSDS, PUS, SDLS) |
| [research/PAYMENT_RESEARCH.md](research/PAYMENT_RESEARCH.md) | Bitcoin L2 technologies for space applications |

### Future / Illustrative

| Document | Description | Status |
|----------|-------------|--------|
| [future/CHANNELS.md](future/CHANNELS.md) | Lightning channel management (LN-Symmetry) | Requires LN-Symmetry activation |
| [future/AUCTION.md](future/AUCTION.md) | Distributed auction (CBBA) for task allocation | Future capability |
| [future/AGS.md](future/AGS.md) | Artificial Ground Station relay constellation | Requires ITU X-band allocation (WRC-27+) |

### Strategy & Funding

| Document | Description |
|----------|-------------|
| [strategy/ROADMAP.md](strategy/ROADMAP.md) | Development roadmap and phasing |
| [strategy/TRL.md](strategy/TRL.md) | Technology Readiness Level progression, demos, hardware |
| [strategy/FUNDING.md](strategy/FUNDING.md) | Grant opportunities (NASA, DARPA, NSF, etc.) |
| [strategy/STANDARDIZATION.md](strategy/STANDARDIZATION.md) | CCSDS/ITU standardization path |
| [strategy/REGULATORY.md](strategy/REGULATORY.md) | Spectrum and regulatory considerations |
| [strategy/ACADEMIC.md](strategy/ACADEMIC.md) | Academic publication opportunities |

### Presentations

Modular markdown slides with Mermaid diagrams, built with reveal-md:

| Directory | Contents |
|-----------|----------|
| [common/](presentations/common/) | 13 shared slides (title, problem, vision, SISL, SCRAP, etc.) |
| [nasa/](presentations/nasa/) | NASA-specific: CCSDS alignment, TRL, SBIR CTA |
| [darpa/](presentations/darpa/) | DARPA-specific: Contested environments, program alignment |
| [commercial/](presentations/commercial/) | Investor-specific: Market opportunity, funding stages |

**Build & Preview:**
```bash
cd presentations
npm install -g reveal-md    # One-time setup
make serve-nasa             # Live preview with hot reload
make all                    # Build all HTML outputs
```

---

## Rust Implementation

Three crates provide a reference implementation:

### scap-core

Core capability token library (no-std compatible):

```rust
// Token creation and verification
pub struct CapabilityToken { ... }
pub fn verify_token(token: &[u8], operator_pubkey: &PublicKey) -> Result<CapabilityToken>;
pub fn create_token(payload: TokenPayload, signing_key: &SecretKey) -> Vec<u8>;
```

**Modules**:
- `token.rs` - SAT-CAP token structure and serialization
- `crypto.rs` - secp256k1 signing and verification
- `cbor.rs` - CBOR encoding/decoding
- `types.rs` - Shared type definitions
- `error.rs` - Error types

### scap-lightning

LDK (Lightning Dev Kit) integration:

```rust
// Payment-task binding
pub struct ScapChannelManager { ... }
pub fn create_task_payment(token: &CapabilityToken, amount_msat: u64) -> PaymentHash;
pub fn verify_execution_proof(proof: &ExecutionProof) -> bool;
```

**Modules**:
- `binding.rs` - Task-payment binding via adaptor signatures
- `channel.rs` - Channel management for satellite nodes
- `payment.rs` - HTLC/PTLC payment handling
- `persister.rs` - NVM persistence for satellite storage
- `fee_estimator.rs` - Static fee estimation for space
- `broadcaster.rs` - Transaction broadcasting via ground station
- `config.rs` - Space-optimized LDK configuration

### scap-ffi

C FFI bindings for non-Rust environments:

```c
// C API
scap_token_t* scap_token_parse(const uint8_t* data, size_t len);
int scap_token_verify(const scap_token_t* token, const uint8_t* pubkey);
void scap_token_free(scap_token_t* token);
```

**Build**:
```bash
cargo build --release -p scap-ffi
# Output: target/release/libscap_ffi.a, libscap_ffi.so
```

### Building

```bash
# Build all crates
cargo build --release

# Run tests
cargo test

# Build for embedded (no-std)
cargo build --release -p scap-core --no-default-features

# Cross-compile for ARM (satellite OBC)
./scripts/cross-build.sh aarch64-unknown-linux-gnu
```

---

## Schemas

CDDL (Concise Data Definition Language) schemas define message formats:

| File | Description |
|------|-------------|
| [schemas/scap.cddl](schemas/scap.cddl) | Capability tokens, task messages, proofs |
| [schemas/examples/](schemas/examples/) | Example messages in CBOR diagnostic notation |
| [schemas/validate_examples.py](schemas/validate_examples.py) | Validation script |

### Test Vectors

Cryptographic test vectors for interoperability testing:

| File | Description |
|------|-------------|
| [test-vectors/computed.json](test-vectors/computed.json) | Computed test vectors |
| [test-vectors/generate.py](test-vectors/generate.py) | Vector generation script |
| [test-vectors/verify.py](test-vectors/verify.py) | Verification script |

---

## Cryptographic Architecture

**Default: secp256k1 only** for all operations (SISL link layer, SCRAP application layer, Lightning payments).

| Operation | Curve | Notes |
|-----------|-------|-------|
| SISL X3DH key agreement | secp256k1 | Link-layer authentication |
| Capability tokens | secp256k1 | Task authorization |
| Lightning HTLCs | secp256k1 | **Mandatory** (Bitcoin requires it) |
| Proof-of-execution | secp256k1 | Settlement signatures |

**Rationale**: Single key hierarchy simplifies provisioning and reduces attack surface. All ECC operations are infrequent enough for software implementation (libsecp256k1). No space-grade HSM supports secp256k1 natively; hardware acceleration requires FPGA soft cores.

**P-256 option**: May be used for SISL link authentication only when FIPS 140-2/3 compliance or CCSDS SDLS interoperability is contractually required. Never used for payment operations.

See [spec/SCRAP.md §11.1](spec/SCRAP.md#111-elliptic-curve-selection) for hardware options and detailed guidance.

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

See [future/CHANNELS.md §2](future/CHANNELS.md#2-architecture) for detailed channel architecture (requires LN-Symmetry).

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

**Regulatory**: UHF 435-438 MHz is amateur/experimental allocation (jurisdiction-dependent).

See [spec/SCRAP.md §14](spec/SCRAP.md#14-cubesat-testbed-demonstration) for testbed architecture.

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
| 02 | [Wildfire Hyperspectral](user_stories/02_wildfire_hyperspectral.md) | Emergency authorization, CBBA auction* | High |
| 03 | [Agricultural Multi-hop](user_stories/03_agricultural_multihop.md) | Delegation chains, orbital data center | High |
| 04 | [Volcanic Ash LIDAR](user_stories/04_lidar_cross_operator.md) | Cross-operator federation | High |
| 05 | [Ship Tracking AIS](user_stories/05_ship_tracking_ais.md) | Coordinated collection | Low |
| 06 | [Methane Detection](user_stories/06_methane_auction.md) | Two-phase auction* | Medium |
| 07 | [GNSS Radio Occultation](user_stories/07_gnss_radio_occultation.md) | Constellation coordination | Medium |
| 08 | [GEO Relay Imaging](user_stories/08_geo_relay_imaging.md) | Optical ISL, emergency response | Medium |
| 09 | [Debris Inspection RPO](user_stories/09_debris_inspection_rpo.md) | Proximity operations, constraints | High |
| 10 | [Satellite Servicing](user_stories/10_satellite_servicing_rpo.md) | Docking authorization | High |
| 11 | [Disaster Response](user_stories/11_disaster_response_multi_constellation.md) | Multi-constellation coordination* | High |
| 12 | [Orbital Data Center](user_stories/12_orbital_data_center.md) | On-orbit processing, data routing | Medium |

\* Stories marked with asterisk use CBBA auction mechanism (see [future/AUCTION.md](future/AUCTION.md)), which is illustrative and not part of core SCRAP.

**CubeSat Testbed Candidates**: Stories 01, 05, 07 (single-operator, manageable ISL geometry)

---

## Key Concepts

**Capability Token (SAT-CAP)**: Operator-signed authorization granting specific commands to a satellite
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

| Component | Status | Location |
|-----------|--------|----------|
| Capability token spec | Draft | spec/SCRAP.md §2 |
| Operator API spec | Draft | spec/OPERATOR_API.md |
| HTLC payment protocol | Draft | spec/HTLC.md |
| Channel management | Draft | future/CHANNELS.md |
| SISL link protocol | Draft | spec/SISL.md |
| Timeout-default arbiter | Draft | spec/SCRAP.md §6.3-6.6 |
| CubeSat testbed design | Draft | spec/SCRAP.md §14 |
| Space security model | Draft | spec/SCRAP.md §11.2 |
| CDDL message schemas | Complete | schemas/scap.cddl |
| Test vectors | Complete | test-vectors/computed.json |
| Rust core library | In Progress | scap-core/ |
| Rust LDK integration | In Progress | scap-lightning/ |
| Rust FFI bindings | In Progress | scap-ffi/ |

---

## External Dependencies

This repository includes Git submodules for Lightning implementations:

| Directory | Repository | Purpose |
|-----------|------------|---------|
| `rust-lightning/` | [lightningdevkit/rust-lightning](https://github.com/lightningdevkit/rust-lightning) | LDK reference |
| `lnd/` | [lightningnetwork/lnd](https://github.com/lightningnetwork/lnd) | LND reference |
| `cln/` | [ElementsProject/lightning](https://github.com/ElementsProject/lightning) | CLN reference |

These are reference implementations for API compatibility; SCRAP uses LDK via `scap-lightning`.

---

## References

### Standards
- CCSDS 133.0-B-2 Space Packet Protocol
- CCSDS 355.0-B-2 Space Data Link Security
- BOLT 2/3/4/11 Lightning Network Specifications

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/) - Recommended for embedded
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)

### Related Efforts
- [STAPI (Sensor Tasking API)](https://github.com/stapi-spec/stapi-spec) - Satellite tasking standard (potential alignment)
- [OGC API](https://ogcapi.ogc.org/) - Geospatial API standards

### Academic
- Choi et al., "Consensus-Based Decentralized Auctions for Robust Task Allocation" (MIT)
- UCAN Specification: https://ucan.xyz/

---

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.
