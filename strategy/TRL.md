# SCRAP/SISL Technology Readiness Roadmap

## Current State Assessment

**Current TRL: 2-3** - Concept formulated, analytical/theoretical validation in progress

| Component | Status | Maturity |
|-----------|--------|----------|
| SCRAP Specification | Complete draft (132KB) | TRL 3 |
| SISL Specification | Complete draft (59KB) | TRL 3 |
| Rust `scap-core` | Partial implementation (see §Gap Analysis) | TRL 2 |
| Test vectors | Generated, verified | TRL 3 |
| CDDL schemas | Complete | TRL 3 |

### scap-core Gap Analysis

**Implemented** (verified from source):
- `CapabilityToken`, `CapHeader`, `CapPayload`, `Constraints` structs
- `CapabilityTokenBuilder` with `sign()` method
- `TokenValidator` with time and signature verification
- `BoundTaskRequest` struct (payment-capability binding)
- `ExecutionProof` struct
- `DisputeMessage`, `DisputeEvidence` structs
- `TaskResponse`, `IslScapMessage`, `Heartbeat` structs
- CBOR encoding/decoding (`encode_header`, `encode_payload`, `decode_capability_token`)
- Crypto: `sign_message`, `verify_signature`, `sha256`, `derive_public_key`
- `compute_binding_hash(jti, payment_hash)`
- `compute_proof_hash(task_jti, payment_hash, output_hash, timestamp)`
- `capability_matches()` for wildcard permission checking
- `validate_capability()` format validation

**Not yet implemented**:
- `UsedTokenCache` - replay protection with persistence (critical for security)
- Delegation chain verification - walking parent chain, capability attenuation checks
- `TaskAccept` struct - invoice/negotiation response message
- PTLC adaptor signature creation and verification
- ARM cross-compilation verification
- Integration tests against full test vector suite

---

## Prioritized Development Path

**Strategy**: SCRAP-first, SISL deferred

Given current resources (Raspberry Pis, BitAxe units, RX-only SDR) and no GNU Radio experience, the optimal path is:

```
PHASE A: SCRAP Demo (6-10 weeks)          PHASE B: SISL Demo (deferred)
─────────────────────────────────        ─────────────────────────────
Sprint 2: Complete scap-core (2-4w)      Sprint 4-5: GNU Radio DSSS
Sprint 3: Build scap-node (3-4w)         Sprint 6: RF integration
    │                                         │
    ▼                                         ▼
┌─────────────────────────┐              ┌─────────────────────────┐
│ 3-4 Raspberry Pi nodes  │              │ LimeSDR + GNU Radio     │
│ TCP/UDP simulated ISL   │              │ Spread spectrum RF      │
│ Token exchange demo     │              │ Physical layer demo     │
│ Testnet PTLC settlement │              │ (requires TX-capable    │
│ BitAxe compute demo     │              │  SDR purchase)          │
└─────────────────────────┘              └─────────────────────────┘
         │                                        │
         ▼                                        ▼
    TRL 4 (SCRAP layer)                     TRL 4 (SISL layer)
```

**Why SCRAP-first**:
1. Uses hardware already available (Pis, BitAxe)
2. No SDR TX capability needed
3. No GNU Radio learning curve
4. Demonstrates payment-for-task value proposition
5. Produces demo video for partner/investor conversations
6. SISL can be added later without rework

**BitAxe Integration**: Same company, Bitcoin payment angle. Demo concept:
- Raspberry Pi runs SCRAP node
- BitAxe provides SHA256 compute service
- Customer pays for compute via SCRAP capability token + PTLC
- Demonstrates pay-per-compute business model

---

## NASA TRL Definitions Reference

| TRL | Definition | SCRAP Milestone |
|-----|------------|----------------|
| 1 | Basic principles observed | Research complete |
| 2 | Technology concept formulated | Specifications drafted |
| 3 | Analytical/experimental proof of concept | Test vectors, partial impl |
| **4** | **Component/breadboard validation in laboratory** | **Ground demo target** |
| 5 | Component/breadboard validation in relevant environment | Thermal-vac or space |
| 6 | System/subsystem prototype in relevant environment | On-orbit CubeSat |
| 7 | System prototype in operational environment | Multi-sat relay |
| 8 | System complete and qualified | Production deployment |
| 9 | System proven in operational environment | Commercial service |

**Note**: For space systems, "relevant environment" (TRL 5) means space-like conditions: thermal vacuum, radiation exposure, or actual space. Ground RF testing, even outdoors, remains TRL 4.

---

## TRL Progression Path

### TRL 3 → TRL 4: Component Validation in Laboratory

#### Demo 1: SCRAP Token Exchange (Ground Simulation)

**Devices**: 3-4 Raspberry Pi 4 or similar ARM boards

**Objective**: Prove SCRAP capability token issuance, delegation, and verification works across multiple nodes communicating via a simulated ISL (TCP/UDP over local network).

**TRL Scope**: This demo achieves **TRL 4 for SCRAP application layer only**. It does not validate SISL physical layer (RF, spread spectrum).

**What to demonstrate**:
1. Operator issues capability token to Satellite A
2. Satellite A presents token to Satellite B (simulated ISL)
3. Satellite B verifies token signature, capabilities, constraints
4. Task request/accept message exchange
5. Proof-of-execution generation and verification
6. Multi-hop delegation (A → B → C)
7. On-chain PTLC settlement on Bitcoin testnet

**Deliverables**:
- `scap-node` binary running on ARM
- Token creation CLI tool
- Message sequence captured and verified
- Latency measurements (<100ms token verification)
- Testnet transaction proving payment binding

**Hardware needed**:
- 3-4 × Raspberry Pi 4 (4GB) ~$55 each = $165-220
- Network switch or router
- Power supplies

**Success criteria**:
- Token verification completes in <100ms on ARM Cortex-A72
- 3-hop delegation chain validates correctly
- All test vectors pass on target hardware
- PTLC settles on testnet with valid adaptor signature

---

#### Demo 2: SISL Physical Layer (Spread Spectrum)

**Devices**: 2 × SDR transceivers + host computers

**Objective**: Demonstrate SISL spread spectrum functionality - DSSS code generation, spreading, despreading, and basic link operation.

**What to demonstrate**:
1. Generate ChaCha20-derived spreading codes (verify against test vectors)
2. Spread a test signal using DSSS
3. Despread and recover original data
4. Public hailing code acquisition
5. Session-derived P2P spreading code transition
6. FEC encoding/decoding (convolutional + Reed-Solomon)
7. Optional: FHSS hopping sequence generation (requires GPS timing)

**Deliverables**:
- GNU Radio flowgraph for DSSS spread/despread
- Python script generating ChaCha20 spreading codes
- Bit error rate measurements vs Eb/N0
- Processing gain demonstration (signal recovery below noise floor)

**Success criteria**:
- BER < 10^-6 at Eb/N0 = 2.5 dB (with concatenated FEC)
- Processing gain ≥30 dB demonstrated
- Session code transition completes without frame loss
- Spreading codes match SISL.md §21 test vectors

**Processing gain by channel**: SISL.md §12.2 specifies different processing gains for different channels:
- Hailing channel: 37 dB (5 Mcps / 1 kbps) - robust acquisition
- P2P channel: 17 dB (5 Mcps / 100 kbps) - higher throughput after link establishment

---

#### Demo 3: Integrated SCRAP + SISL End-to-End

**Devices**: 3 nodes, each with Raspberry Pi + SDR

**Objective**: Full protocol stack - SISL link establishment followed by SCRAP task exchange over actual RF.

**SDR Configuration**: Since recommended SDRs (HackRF, LimeSDR) have different duplex capabilities:
- **LimeSDR Mini**: Full duplex - one unit per node sufficient
- **HackRF One**: Half duplex - need 2 units per node (TX + RX), OR use time-division

**What to demonstrate**:
1. Node A hails Node B using public spreading code
2. X3DH key exchange completes
3. Session-derived spreading code activated
4. AES-256-GCM encrypted link established
5. Capability token + task request sent over RF link
6. Task execution simulation
7. Proof-of-execution returned
8. On-chain PTLC payment settlement (testnet)

**Deliverables**:
- Complete protocol trace (RF capture + decoded messages)
- Timing breakdown for each protocol phase
- Video demonstration
- Written test report

**Success criteria**:
- Full protocol completes in <5 minutes (simulating ISL contact window)
- All cryptographic operations verified (signatures, encryption, ECDH)
- Payment binding demonstrated (testnet PTLC transaction)
- Link survives ambient 2.4 GHz interference (Wi-Fi)

---

#### Demo 4: Field Test with Real RF Propagation

**Environment**: Outdoor, line-of-sight, 100m-1km separation

**TRL**: Still TRL 4 (laboratory/controlled environment, not space-relevant)

**Objective**: Validate link budget, spreading gain, and protocol timing with real path loss and multipath.

**Link Budget Analysis (2.4 GHz, hailing channel 1 kbps)**:

| Parameter | Value | Notes |
|-----------|-------|-------|
| TX Power | +10 dBm | HackRF/LimeSDR typical |
| TX Antenna Gain | 2 dBi | Rubber duck |
| Path Loss (500m) | 80 dB | Free space at 2.4 GHz |
| RX Antenna Gain | 2 dBi | Rubber duck |
| **Received Power** | **-66 dBm** | |
| Noise density (kT) | -174 dBm/Hz | 290K |
| Noise floor (5 MHz) | -107 dBm | -174 + 67 |
| SNR before despread | 41 dB | Signal well above noise |
| Processing gain | +37 dB | 5 Mcps / 1 kbps |
| **SNR after despread** | **78 dB** | Massive margin |

| Range | Path Loss | Received | SNR (despread) | Status |
|-------|-----------|----------|----------------|--------|
| 500m | 80 dB | -66 dBm | 78 dB | Excellent |
| 1 km | 86 dB | -72 dBm | 72 dB | Excellent |
| 5 km | 100 dB | -86 dBm | 58 dB | Good |

**Conclusion**: Ground demo has massive link margin. Even at 5 km with rubber duck antennas, SNR exceeds requirements by >50 dB. The challenge is software/protocol, not RF.

**What to demonstrate**:
1. Link establishment at 500m (omnidirectional antennas)
2. Link establishment at 1km (omnidirectional or directional)
3. Full protocol completion with real path loss
4. Interference rejection with Wi-Fi sources present

**Additional hardware**:
- Directional antennas (Yagi or patch, ~$50-100 each)
- Weatherproof enclosures
- Battery power
- GPS modules (required for FHSS mode)

**Success criteria**:
- Link established at 500m with omnidirectional antennas
- Protocol completes despite ambient 2.4 GHz interference
- BER measurements match indoor predictions

---

### TRL 4 → TRL 5-6: Validation in Relevant Environment

#### Demo 5: CubeSat Partner Firmware Upload

**Environment**: On-orbit via partner CubeSat

**TRL**: 5-6 (system in relevant environment)

**Objective**: Prove SCRAP protocol works in actual space environment.

**Prerequisites**:
- Partner with UHF CubeSat capability (see [ROADMAP.md](ROADMAP.md))
- Firmware compiled for target OBC (likely ARM Cortex-M or -A)
- Ground station access (partner-provided or SatNOGS)

**What to demonstrate**:
1. Firmware upload and activation
2. Token verification on-orbit
3. Task acknowledgment via UHF downlink
4. Ground-to-space-to-ground message relay
5. On-chain PTLC settlement from space-originated proof

**Note**: This demo validates SCRAP over UHF (~9.6 kbps), not the full SISL spread spectrum physical layer. SISL validation requires satellites with SDR-capable ISL.

**Success criteria**:
- Firmware operates without anomaly for 30+ days
- Token verification latency comparable to ground tests
- Successful task acknowledgment received via ground station
- On-chain settlement completes

---

### TRL 6: System Prototype Demonstration

#### Demo 6: Multi-Hop Relay Through Multiple Satellites

**Environment**: 2-3 on-orbit CubeSats with ISL capability

**What to demonstrate**:
1. Task bundle routed A → B → C via ISL
2. Each hop verifies delegation token
3. Onion decryption at each hop (if ISL bandwidth permits)
4. Acknowledgments flow backward through chain
5. On-chain PTLC settlement occurs

**Note on payment**: Early demos use **on-chain PTLCs**, not Lightning channels. Lightning PTLC support requires Bitcoin soft fork (signature aggregation) that is not yet activated. On-chain PTLCs work today with Taproot/Schnorr.

**Success criteria**:
- 3-hop task relay completes (may require multiple orbital passes)
- Adaptor signature reveals payment preimage
- On-chain settlement confirmed on mainnet

---

### TRL 6 → TRL 7: System Prototype in Operational Environment

#### Demo 7: Cross-Operator Task Execution

**Environment**: Satellites from different operators

**What to demonstrate**:
1. Operator A's satellite tasks Operator B's satellite
2. Capability token issued by Operator B, held by Operator A
3. Payment settles via on-chain PTLC (or Lightning when available)
4. Actual task execution (imaging, relay, or compute)

**Prerequisites**:
- Two cooperating operators with compatible ISL
- Trust list exchange between operators
- Legal/business agreement for payment settlement

---

## Consumer Radio Options for SISL Testing

### SDR Transceiver Comparison

| Radio | Price | TX/RX | Duplex | Bandwidth | Frequency Range | Notes |
|-------|-------|-------|--------|-----------|-----------------|-------|
| **LimeSDR Mini 2.0** | ~$200 | TX+RX | **Full** | 30.72 MHz | 10 MHz - 3.5 GHz | **Recommended** |
| **HackRF One** | ~$300 | TX+RX | **Half** | 20 MHz | 1 MHz - 6 GHz | Need 2 per node for bidir |
| **ADALM-PlutoSDR** | ~$230 | TX+RX | Full | 20 MHz | 325 MHz - 3.8 GHz | Good docs, AD9361 |
| **USRP B200mini** | ~$800 | TX+RX | Full | 56 MHz | 70 MHz - 6 GHz | Professional grade |
| **RTL-SDR v4** | ~$40 | RX only | N/A | 3.2 MHz | 500 kHz - 1.7 GHz | **Cannot do 2.4 GHz** |

**Recommended for SISL demo**: 2 × LimeSDR Mini 2.0 (full duplex, sufficient bandwidth, 2.4 GHz capable)

**HackRF limitation**: HackRF One is half-duplex (cannot TX and RX simultaneously). For bidirectional SISL links, either:
- Use 2 HackRFs per node (one TX, one RX) - expensive
- Use time-division multiplexing - changes protocol timing
- Use LimeSDR instead - recommended

### Frequency Band Options

| Band | Frequency | Regulatory Status | Accessibility | Notes |
|------|-----------|-------------------|---------------|-------|
| **ISM 2.4 GHz** | 2400-2483 MHz | License-free (Part 15.247) | **Best for demos** | See regulatory section |
| ISM 5.8 GHz | 5725-5875 MHz | License-free (Part 15.247) | Alternative | Higher path loss |
| UHF Amateur | 435-438 MHz | Amateur license required | Realistic for space | Requires ham ticket |
| S-band TT&C | 2200-2290 MHz | ITU coordinated | **Not for ground testing** | Interference risk |

### ISM 2.4 GHz Regulatory Requirements (FCC Part 15.247)

For spread spectrum systems in the 2.4 GHz ISM band:

| Requirement | DSSS | FHSS |
|-------------|------|------|
| Minimum bandwidth | 500 kHz | N/A |
| Minimum hopping channels | N/A | 50 (for 1W EIRP) |
| Maximum TX power | 1W (30 dBm) | 1W (30 dBm) |
| Maximum EIRP | 4W with directional antenna | 4W |
| Power spectral density | 8 dBm / 3 kHz | N/A |
| Dwell time (FHSS) | N/A | ≤400 ms |

**SISL compliance**: The hailing channel (5 Mcps, 10 MHz bandwidth) exceeds minimum bandwidth requirements. For demo purposes at low power (<100 mW), Part 15.247 compliance is straightforward.

### Antenna Options

| Antenna | Gain | Beamwidth | Price | Use Case |
|---------|------|-----------|-------|----------|
| Rubber duck (included) | 2 dBi | Omnidirectional | $0 | Bench testing |
| PCB patch antenna | 5-8 dBi | ~60° | $15-30 | Medium range |
| Yagi (7 element) | 10-12 dBi | ~30° | $50-80 | Field test |
| Parabolic dish | 20+ dBi | ~10° | $100+ | Maximum range |

---

## Hardware Shopping Lists

### Tier 1: Minimum Viable Demo (SCRAP-only, ground simulation)

| Item | Qty | Unit Price | Total |
|------|-----|------------|-------|
| Raspberry Pi 4 (4GB) | 4 | $55 | $220 |
| MicroSD cards (32GB) | 4 | $10 | $40 |
| USB-C power supplies | 4 | $15 | $60 |
| Ethernet cables (Cat6) | 4 | $5 | $20 |
| Network switch (8-port) | 1 | $25 | $25 |
| **Total** | | | **$365** |

**Demonstrates**: TRL 4 for **SCRAP layer only** (token exchange, verification, delegation, on-chain PTLC)

---

### Tier 2: Full Demo (SCRAP + SISL RF bench test)

| Item | Qty | Unit Price | Total |
|------|-----|------------|-------|
| Raspberry Pi 4 (4GB) | 3 | $55 | $165 |
| LimeSDR Mini 2.0 | 3 | $200 | $600 |
| 2.4 GHz SMA antennas | 6 | $15 | $90 |
| SMA cables (1m) | 6 | $10 | $60 |
| RF attenuators (30dB) | 3 | $15 | $45 |
| MicroSD cards (32GB) | 3 | $10 | $30 |
| USB-C power supplies | 3 | $15 | $45 |
| USB 3.0 hub (powered) | 3 | $25 | $75 |
| **Total** | | | **$1,110** |

**Demonstrates**: TRL 4 for complete SCRAP+SISL stack (3-node relay with RF)

---

### Tier 3: Field Test Kit (outdoor RF propagation)

| Item | Qty | Unit Price | Total |
|------|-----|------------|-------|
| Tier 2 kit | 1 | $1,110 | $1,110 |
| Yagi antenna (2.4 GHz) | 2 | $60 | $120 |
| Tripod mount | 2 | $30 | $60 |
| Weatherproof enclosure | 2 | $40 | $80 |
| 12V LiFePO4 battery | 2 | $80 | $160 |
| DC-DC converter (5V 3A) | 2 | $15 | $30 |
| GPS module (u-blox NEO-M8) | 2 | $35 | $70 |
| Pelican case (transport) | 1 | $100 | $100 |
| **Total** | | | **$1,730** |

**Demonstrates**: TRL 4 with real-world RF propagation validation

---

## Embedded Compute Platform Options

### Raspberry Pi vs Alternatives

| Platform | CPU | RAM | Price | Crypto Perf | Notes |
|----------|-----|-----|-------|-------------|-------|
| **Raspberry Pi 4** | Cortex-A72 1.5GHz | 4GB | $55 | ~25ms ECDSA | Best ecosystem |
| Raspberry Pi 5 | Cortex-A76 2.4GHz | 4GB | $60 | ~15ms ECDSA | Faster, newer |
| BeagleBone Black | Cortex-A8 1GHz | 512MB | $55 | ~80ms ECDSA | Industrial, PRUs |
| ESP32-S3 | Xtensa LX7 240MHz | 512KB | $10 | ~500ms ECDSA | Too slow for demo |
| STM32H7 | Cortex-M7 480MHz | 1MB | $25 | ~200ms ECDSA | Embedded target |

**Recommendation**: Raspberry Pi 4 for demos (ecosystem, performance). STM32H7 or similar for flight-representative testing.

### BitAxe as Demo Platform

The BitAxe miner can demonstrate **payment-for-computation** but with important limitations:

**What BitAxe provides**:
- SHA256 ASIC acceleration (BM1366/BM1370)
- ESP32-S3 controller with Wi-Fi
- Small form factor, 15-90W power
- Active open-source community

**What BitAxe does NOT provide**:
- secp256k1 / ECDSA capability (ASICs only do SHA256)
- Radiation tolerance (commercial components)
- Sufficient controller performance for SCRAP (ESP32 is slow)

**Demo concept**: BitAxe as "compute service provider"
1. Raspberry Pi runs SCRAP stack, interfaces with BitAxe via USB/UART
2. Customer requests compute task via SCRAP
3. Pi verifies token, forwards work to BitAxe ASIC
4. BitAxe returns SHA256 result
5. Pi generates proof-of-execution, settles PTLC

This demonstrates pay-per-compute but requires external SCRAP node (Pi) - BitAxe alone cannot run SCRAP.

| Model | Chip | Hashrate | Power | Price |
|-------|------|----------|-------|-------|
| BitAxe Ultra | BM1366 | 500 GH/s | 15W | ~$70 |
| BitAxe Gamma | BM1370 | 1.2 TH/s | 15W | ~$100 |

---

## Implementation Tasks

### PHASE A: SCRAP Demo (Immediate - 6-10 weeks)

#### A1: Complete scap-core (2-4 weeks)

Most structs already implemented. Remaining work:

```
[x] CapabilityToken, BoundTaskRequest, ExecutionProof structs (done)
[x] Crypto: sign, verify, binding_hash, proof_hash (done)
[x] CBOR encoding/decoding (done)
[ ] TaskAccept struct - invoice response with execution plan
[ ] UsedTokenCache with SQLite or file persistence (critical)
[ ] Delegation chain verification - verify_delegation_chain() function
    - Walk parent chain via prf field
    - Check capability attenuation (child ⊆ parent)
    - Check expiry inheritance (child.exp ≤ parent.exp)
[ ] Integration tests against test-vectors/computed.json
[ ] no_std compatibility verification (may already work)
[ ] ARM cross-compilation test (aarch64-unknown-linux-gnu)
[ ] Benchmarks on Raspberry Pi 4
```

**Exit criteria**: `cargo test` passes on x86 and ARM, benchmarks documented

#### A2: Build scap-node binary (3-4 weeks)

```
[ ] Project structure (separate crate or workspace member)
[ ] TCP listener for SCRAP messages (tokio or async-std)
[ ] UDP listener option for ISL simulation
[ ] Token verification pipeline with timing metrics
[ ] SQLite-based used-token cache
[ ] Task execution simulation framework (pluggable handlers)
[ ] Proof-of-execution generation
[ ] Structured JSON logging (tracing crate)
[ ] Configuration file support (TOML)
[ ] CLI for token creation and inspection
[ ] Testnet PTLC integration (rust-bitcoin):
    - Schnorr signature creation (BIP-340)
    - Adaptor signature generation and verification
    - PTLC transaction construction (Taproot spend paths)
    - PSBT workflow for signing
    - Testnet wallet/UTXO management
[ ] Multi-node test harness
```

**Exit criteria**: 3-node token relay works over UDP, testnet PTLC confirmed on block explorer

#### A3: BitAxe integration (1-2 weeks, parallel with A2)

```
[ ] BitAxe AxeOS API research (REST/WebSocket interface)
[ ] Work submission interface
[ ] Result retrieval and verification
[ ] Proof-of-work as proof-of-execution
[ ] Integration with scap-node task handler
```

**Exit criteria**: BitAxe responds to SCRAP compute task, proof-of-execution generated

#### A4: Demo harness and recording (1 week)

```
[ ] Docker-compose for multi-node SCRAP setup
[ ] UDP multicast ISL simulation mode
[ ] Message sequence diagram generator
[ ] Latency and throughput metrics dashboard
[ ] Demo script with narration points
[ ] Video recording setup (OBS or similar)
[ ] Record demo videos (token relay, BitAxe compute)
[ ] Test report
```

**Exit criteria**: Demo videos recorded and published

**Demo scenarios to record**:
1. **Token relay**: Node A → B → C with delegation chain verification
2. **Pay-per-compute**: Customer pays BitAxe node for SHA256 work via SCRAP
3. **Proof-of-execution**: Verifiable result hash with testnet PTLC settlement

**Phase A total: 6-10 weeks** → TRL 4 for SCRAP layer

---

### PHASE B: SISL Demo (Deferred - 14-19 weeks additional)

*Prerequisites: TX-capable SDR (~$200 LimeSDR Mini), GNU Radio learning*

#### B1: SISL GNU Radio - Spreading (3-4 weeks)

```
[ ] ChaCha20 spreading code generator (Python block)
[ ] Verify against SISL.md §21 test vectors
[ ] DSSS spreader block (multiply by code)
[ ] DSSS despreader block (correlate and integrate)
[ ] Basic TX flowgraph (data → spread → modulate)
[ ] Basic RX flowgraph (demod → despread → data)
[ ] Loopback test (file sink/source)
```

**Exit criteria**: Spreading codes match test vectors, loopback BER < 10^-6

#### B2: SISL GNU Radio - FEC and framing (3-4 weeks)

```
[ ] Convolutional encoder (rate 1/2, K=7)
[ ] Viterbi decoder (soft decision)
[ ] Reed-Solomon encoder RS(255,223)
[ ] Reed-Solomon decoder (Berlekamp-Massey)
[ ] Interleaver/deinterleaver
[ ] ASM (sync marker) insertion and detection
[ ] CRC-32C block (Castagnoli polynomial)
[ ] Frame assembly and disassembly
```

**Exit criteria**: BER < 10^-6 at Eb/N0 = 2.5 dB in AWGN simulation

#### B3: SISL GNU Radio - Encryption (2-4 weeks)

```
[ ] AES-256-GCM encryption block
[ ] AES-256-GCM decryption block
[ ] IV construction per SISL.md §6.3
[ ] X3DH key exchange (secp256k1 ECDH)
[ ] Session key derivation (HKDF)
[ ] Hail message encryption/decryption
[ ] ACK message encryption/decryption
```

**Exit criteria**: X3DH completes, encrypted frames decrypt correctly

#### B4: RF integration and testing (2-3 weeks)

```
[ ] Complete TX flowgraph with all layers
[ ] Complete RX flowgraph with all layers
[ ] LimeSDR source and sink integration
[ ] RF loopback test (TX → attenuator → RX)
[ ] Over-the-air test (short range)
[ ] BER measurement automation
[ ] Processing gain measurement
```

**Exit criteria**: Over-the-air link at 1m with 37 dB ±3 dB measured processing gain

#### B5: SCRAP+SISL integration (3-4 weeks)

```
[ ] SISL ↔ scap-node integration layer
[ ] Real RF mode with GNU Radio
[ ] 3-node relay test over RF
[ ] Bitcoin testnet PTLC settlement over RF link
[ ] Performance benchmarking
[ ] Record integrated demo video
[ ] Documentation updates
```

**Exit criteria**: Full SCRAP+SISL demo video published, test report complete

**Phase B total: 14-19 weeks** → TRL 4 for complete SCRAP+SISL stack

---

**Combined total: 20-29 weeks** (but Phase A delivers value independently)

---

## Success Metrics by TRL

| TRL | Key Metric | Target | Validation Method |
|-----|------------|--------|-------------------|
| 4 | Token verification latency | <100ms on Pi 4 | Benchmark suite |
| 4 | DSSS processing gain | 37 dB ±3 dB | RF measurement (hailing channel) |
| 4 | 3-hop delegation | Chain validates | Integration test |
| 4 | PTLC settlement | Testnet TX confirmed | Block explorer |
| 4 | Field test range | ≥500m omni antenna | RF measurement |
| 5-6 | On-orbit operation | 30+ days no anomaly | Telemetry |
| 6 | Multi-sat relay | 3-hop completes | Mission log |
| 7 | Cross-operator task | Payment settles | On-chain record |

**Note on processing gain**: Target is 37 dB per SISL.md §10.2 (5 Mcps / 1 kbps). Allow ±3 dB for implementation losses and measurement uncertainty.

---

## External Validation Activities

### Publications

| Venue | Topic | Submission Deadline | Conference |
|-------|-------|---------------------|------------|
| IEEE Aerospace Conference | SCRAP architecture | Oct 2026 | Mar 2027 |
| ACM CCS | Capability token security | Feb 2027 | Nov 2027 |
| CCSDS Technical Meeting | SCRAP Green Book draft | Ongoing | Biannual |
| arXiv | Full spec + demo results | After Demo 1 | N/A |

**Note**: IEEE Aerospace Conference: abstract ~July, full paper ~October, conference March. ACM CCS: submission ~February, conference November. Dates above target 2027 conferences to allow time for demo completion.

### Security Audit

- **Scope**: Cryptographic design, token verification, key management, X3DH implementation
- **Timing**: After Sprint 2 (scap-core complete)
- **Providers**: NCC Group, Trail of Bits, Cure53, or academic partnership
- **Estimated cost**: $30-80K depending on scope

### Interoperability Testing

- Independent implementation (Python reference)
- Cross-validation with Rust implementation using shared test vectors
- Test vector exchange with external parties
- CCSDS interoperability testing (if pursuing standardization)

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PTLC/adaptor signatures harder than expected | Medium | High | Study rust-bitcoin examples; consult Bitcoin devs; budget extra time |
| GNU Radio DSSS harder than expected | High | Medium | Use existing gr-spread; simplify initial demo; Phase B is deferred anyway |
| CubeSat partner unavailable | Medium | High | Ground demo still achieves TRL 4; pursue multiple partners |
| Lightning PTLC soft fork delayed | Medium | Low | On-chain PTLCs work today; Lightning is future optimization |
| Hardware supply issues (Pi, SDR) | Low | Medium | Order early; have backup suppliers |
| RF interference in ISM band | Medium | Low | Processing gain provides margin; can test at night |
| Timeline slippage | High | Medium | Phase deliverables; demo partial results |
| BitAxe AxeOS API undocumented | Medium | Low | Inspect source code; BitAxe community is active |

---

## References

- [ROADMAP.md](ROADMAP.md) - Strategic roadmap with funding and partnerships
- [../spec/SCRAP.md](../spec/SCRAP.md) - SCRAP protocol specification
- [../spec/SISL.md](../spec/SISL.md) - SISL link layer specification
- [FUNDING.md](FUNDING.md) - Grant opportunities
- [ACADEMIC.md](ACADEMIC.md) - Academic partnerships
- NASA Systems Engineering Handbook (SP-2007-6105 Rev 2) - TRL definitions
- FCC Part 15.247 - Spread spectrum regulations
- GNU Radio documentation - https://wiki.gnuradio.org/
