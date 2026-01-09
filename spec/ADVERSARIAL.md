# SCRAP Adversarial Environment Considerations

## Scope

This document extends the SCRAP security analysis for deployment in contested
and adversarial environments, including military and dual-use applications.
It addresses threats beyond the standard commercial threat model.

For the base protocol specification, see [SCRAP.md](SCRAP.md).
For link-layer security, see [SISL.md](SISL.md).

---

## 1. Threat Model

### 1.1 Adversary Capabilities

| Capability Level | Description | Examples |
|------------------|-------------|----------|
| **Tier 1: Passive** | Observe traffic, no modification | Signal intelligence, traffic analysis |
| **Tier 2: Active Network** | Inject, drop, delay, replay messages | Man-in-the-middle, jamming |
| **Tier 3: Timing** | Manipulate time perception | GPS spoofing, NTP attacks |
| **Tier 4: Physical** | Access to hardware | Ground station compromise, satellite capture |
| **Tier 5: Supply Chain** | Compromise before deployment | Backdoored firmware, malicious components |

### 1.2 Assumed Adversary

For this analysis, we assume a **state-level adversary** with:
- Tier 1-3 capabilities against space segment
- Potential Tier 4 capabilities against ground segment
- Tier 5 out of scope (handled by procurement/security processes)

### 1.3 Security Goals Under Adversarial Conditions

| Goal | Description |
|------|-------------|
| **Fund Safety** | Adversary cannot steal locked funds |
| **Availability** | Degraded service acceptable; total denial requires physical destruction |
| **Integrity** | Adversary cannot forge task completion or authorization |
| **Confidentiality** | Task content protected; metadata exposure acceptable |

---

## 2. Clock Security

### 2.1 Timing Attack Surface

SCRAP uses Bitcoin timelocks (CLTV) for:
- HTLC/PTLC expiration
- Channel dispute windows
- Recovery path activation

An adversary who can shift a satellite's perceived time can:
- Trigger premature timeouts (steal funds via early refund)
- Prevent legitimate claims (funds locked past true expiration)
- Desynchronize channel state

### 2.2 Timing Sources

| Source | Accuracy | Spoofing Resistance | Availability |
|--------|----------|---------------------|--------------|
| **GPS L1 C/A** | <100ns | Low (civilian, unencrypted) | High |
| **GPS L1/L2 P(Y)** | <100ns | Medium (encrypted, requires key) | Military only |
| **GPS M-code** | <100ns | High (anti-jam, anti-spoof) | Military only |
| **Galileo PRS** | <100ns | High (encrypted) | EU government |
| **Ground NTP** | ~1s | Medium (authenticated NTP) | During contact |
| **Onboard RTC** | ~10ppm drift | High (no external input) | Always |
| **Crosslink sync** | ~1us | Medium (requires trusted peer) | During ISL |

### 2.3 Multi-Source Timing Architecture

```
+------------------------------------------------------------------+
|                    TIMING SUBSYSTEM                               |
+------------------------------------------------------------------+
|                                                                   |
|   +-------+   +-------+   +-------+   +-------+                   |
|   | GPS 1 |   | GPS 2 |   | Ground|   | Xlink |                   |
|   | (L1)  |   | (M-code)|  | NTP   |   | Sync  |                   |
|   +---+---+   +---+---+   +---+---+   +---+---+                   |
|       |           |           |           |                       |
|       v           v           v           v                       |
|   +--------------------------------------------------+            |
|   |              TIME ARBITRATION                     |            |
|   |                                                   |            |
|   |  1. Collect all available sources                 |            |
|   |  2. Reject outliers (>threshold from median)      |            |
|   |  3. Weight by source reliability                  |            |
|   |  4. Compute weighted average                      |            |
|   |  5. Compare to RTC for sanity check               |            |
|   |                                                   |            |
|   +--------------------------------------------------+            |
|                          |                                        |
|                          v                                        |
|                  +---------------+                                |
|                  | SYSTEM TIME   |                                |
|                  | (for timelocks)|                               |
|                  +---------------+                                |
|                                                                   |
+------------------------------------------------------------------+
```

### 2.4 Spoofing Detection

**Indicators of GPS spoofing:**
- Sudden time jump (>1s without known cause)
- Position jump inconsistent with orbital mechanics
- Signal strength anomalies
- Doppler shift mismatch
- Disagreement between GPS units

**Response to detected spoofing:**
1. Fall back to ground NTP + RTC
2. Increase timeout margins (conservative)
3. Alert ground station
4. Log for forensic analysis

### 2.5 Timeout Margins

| Environment | Base Margin | Rationale |
|-------------|-------------|-----------|
| **Benign** | +3 hours | MTP lag + propagation |
| **Contested** | +6 hours | Timing uncertainty |
| **Denied GPS** | +24 hours | RTC drift accumulation |
| **Deep space** | +48 hours | Long propagation, no GPS |

---

## 3. Ground Denial Scenarios

### 3.1 Denial Modes

| Mode | Duration | Cause | Impact |
|------|----------|-------|--------|
| **Transient** | Minutes | Weather, interference | Minimal |
| **Extended** | Hours | Jamming, infrastructure failure | Degraded settlement |
| **Persistent** | Days+ | Kinetic attack, occupation | Store-and-forward only |

### 3.2 Operations Under Ground Denial

**What still works:**
- S2S direct payments (satellite-to-satellite channels)
- Task execution and acknowledgment
- Store-and-forward of settlement data
- Capability token verification (pre-distributed)

**What degrades:**
- On-chain settlement (requires ground for broadcast)
- Watchtower function (requires ground monitoring)
- New channel opening (requires funding tx broadcast)
- Liquidity rebalancing

**What fails:**
- Cross-operator settlement (requires ground relay)
- New capability token issuance (requires operator)

### 3.3 Resilience Architecture

```
+------------------------------------------------------------------+
|              GROUND DENIAL RESILIENCE                             |
+------------------------------------------------------------------+
|                                                                   |
|   NORMAL OPERATION:                                               |
|   ================                                                |
|   Satellite <--ISL--> Satellite <--ISL--> Satellite               |
|       |                   |                   |                   |
|       v                   v                   v                   |
|   Ground A            Ground B            Ground C                |
|       |                   |                   |                   |
|       +----- Lightning Network ---------------+                   |
|                                                                   |
|   GROUND DENIED (Station B):                                      |
|   ==========================                                      |
|   Satellite <--ISL--> Satellite <--ISL--> Satellite               |
|       |                   |                   |                   |
|       v                   X                   v                   |
|   Ground A            [DENIED]            Ground C                |
|       |                                       |                   |
|       +-------- Lightning Network ------------+                   |
|                                                                   |
|   - Middle satellite stores settlement data                       |
|   - Forwards to next available ground contact                     |
|   - Timeout margins extended automatically                        |
|                                                                   |
+------------------------------------------------------------------+
```

### 3.4 Pre-Positioned Resources

For extended ground denial, satellites should pre-position:
- Sufficient channel capacity for expected operations
- Long-lived capability tokens (weeks, not hours)
- Multiple operator relationships for redundancy
- Cached routing tables and peer information

---

## 4. Jamming and Interference

### 4.1 ISL Jamming

| ISL Type | Jamming Resistance | Notes |
|----------|-------------------|-------|
| **Optical** | High | Narrow beam, hard to intercept/jam |
| **RF (directional)** | Medium | Requires approximate LOS to jam |
| **RF (omni)** | Low | Vulnerable to broadband jamming |

### 4.2 Impact of ISL Jamming

Jamming an ISL causes link disconnect. Protocol behavior:
- In-flight HTLCs remain locked
- Settlement deferred to next contact window
- No fund loss (timeout refunds if no alternative path)

**Jamming cannot:**
- Steal funds (requires private keys)
- Forge messages (requires signatures)
- Corrupt channel state (requires valid signatures)

**Jamming can:**
- Delay payments (denial of service)
- Force on-chain settlement (expensive)
- Prevent specific task execution (targeted denial)

### 4.3 Anti-Jam Techniques

| Technique | Applicability | Notes |
|-----------|---------------|-------|
| **Frequency hopping** | RF ISL | Requires pre-shared hopping sequence |
| **Spread spectrum** | RF ISL | Reduces jam margin |
| **Optical fallback** | Multi-mode ISL | Switch to optical if RF jammed |
| **Mesh routing** | Constellation | Route around jammed links |
| **Burst transmission** | All | Minimize jam window |

---

## 5. Coalition Operations

### 5.1 Multi-Party Authorization with FROST/ROAST

For coalition operations requiring m-of-n authorization, SCRAP uses
[FROST](https://eprint.iacr.org/2020/852) (Flexible Round-Optimized Schnorr
Threshold signatures) or [ROAST](https://eprint.iacr.org/2022/550) (Robust
Asynchronous Schnorr Threshold signatures).

**FROST properties:**
- t-of-n threshold Schnorr signatures
- Produces standard BIP-340 signatures (indistinguishable from single-signer)
- Requires synchronized signing rounds

**ROAST properties:**
- Wrapper around FROST for robustness
- Handles malicious/unresponsive signers
- Guaranteed termination if t honest parties exist

### 5.2 Coalition Capability Token

```
CoalitionCapabilityToken:
  v: 1
  iss: <threshold_pubkey>           # FROST aggregate key
  iss_threshold: "2-of-3"           # Human-readable policy
  iss_parties: [pubkey_A, pubkey_B, pubkey_C]  # For verification
  sub: "coalition-satellite-id"
  aud: "executor-satellite-id"
  cap: ["cmd:relay:priority"]
  sig: <frost_aggregate_signature>  # Standard Schnorr sig
```

**Issuance:**
1. Coalition partners run FROST key generation (once)
2. Aggregate public key is the token issuer
3. Token issuance requires t-of-n signing session
4. Resulting signature is standard Schnorr (verifier unaware of threshold)

### 5.3 Coalition Payment Channels

For coalition-controlled channel funds:

```
Funding output:
  <frost_aggregate_key> CHECKSIG

Update/Settlement:
  Signed with FROST/ROAST by coalition threshold
```

This allows m-of-n control over channel funds without revealing threshold
structure on-chain.

### 5.4 Cross-Domain Authorization

| Domain | Trust Relationship | Implementation |
|--------|-------------------|----------------|
| **Same coalition** | Full trust | Shared FROST key |
| **Allied coalition** | Limited trust | Capability delegation with attenuation |
| **Neutral party** | No trust | Standard commercial SCRAP |
| **Adversary** | Hostile | No interaction |

---

## 6. Physical Security Considerations

### 6.1 Satellite Compromise

If an adversary gains physical access to a satellite:

**Keys at risk:**
- Satellite signing key (can forge signatures as that satellite)
- Channel keys (can sign channel updates)
- Pre-stored capability tokens (can execute authorized tasks)

**Keys NOT at risk (if properly isolated):**
- Other satellites' keys
- Operator root keys (ground-based)
- Other channels' keys

**Mitigations:**
- Hardware security modules (HSM) for key storage
- Tamper-evident/tamper-resistant enclosures
- Key zeroization on tamper detection
- Limited channel capacity per satellite

### 6.2 Ground Station Compromise

If an adversary compromises a ground station:

**At risk:**
- Watchtower data (can enable old-state attacks)
- Pending transactions (can delay/censor)
- Operator keys (if stored at station)

**Mitigations:**
- Watchtower data encryption (satellite holds key)
- Multiple redundant ground stations
- Operator keys in separate secure facility
- Transaction broadcast via multiple paths

### 6.3 Recovery from Compromise

| Asset Compromised | Recovery Action |
|-------------------|-----------------|
| Single satellite key | Revoke capability tokens, close channels |
| Ground station | Rotate watchtower keys, switch stations |
| Operator signing key | Full key rotation, re-issue all tokens |
| FROST share (< threshold) | Proactive share refresh |

---

## 7. Cryptographic Considerations

### 7.1 Algorithm Selection

| Function | Algorithm | Security Level | Notes |
|----------|-----------|----------------|-------|
| Signatures | BIP-340 Schnorr | 128-bit | secp256k1 curve |
| Hashing | SHA-256 | 128-bit | Bitcoin standard |
| Symmetric | ChaCha20-Poly1305 | 256-bit | BOLT 8 transport |
| Key exchange | X25519 | 128-bit | BOLT 8 handshake |
| Threshold | FROST/ROAST | 128-bit | Standard Schnorr output |

### 7.2 Post-Quantum Considerations

Current SCRAP cryptography is not post-quantum secure. Quantum computers
capable of breaking secp256k1 would compromise:
- All Schnorr signatures
- FROST threshold signatures
- ECDH key exchange

**Migration path:**
- Bitcoin community will address PQ before SCRAP needs to
- Monitor NIST PQC standardization
- SPHINCS+ for signatures, Kyber for key exchange likely candidates
- SCRAP protocol is algorithm-agnostic; swap primitives when Bitcoin does

### 7.3 Side-Channel Resistance

Space environment introduces unique side-channel concerns:
- Power analysis (limited by radiation-hardened designs)
- EM emanations (ISL transmission is intentional)
- Timing attacks (GPS provides precise timing reference)

**Mitigations:**
- Constant-time implementations for signing
- Power filtering on crypto operations
- Randomized execution timing where feasible

---

## 8. Operational Security

### 8.1 Key Hierarchy

```
+------------------------------------------------------------------+
|                    KEY HIERARCHY                                  |
+------------------------------------------------------------------+
|                                                                   |
|  OPERATOR ROOT (offline, air-gapped)                              |
|       |                                                           |
|       +-- Operator Signing Key (issues capability tokens)         |
|       |                                                           |
|       +-- FROST Share (if coalition member)                       |
|                                                                   |
|  SATELLITE KEYS (on-board HSM)                                    |
|       |                                                           |
|       +-- Identity Key (BIP-32 derived, path m/7227'/...)         |
|       |                                                           |
|       +-- Channel Keys (per-channel, derived)                     |
|       |                                                           |
|       +-- Ephemeral Keys (per-session, not persisted)             |
|                                                                   |
|  GROUND STATION (secure facility)                                 |
|       |                                                           |
|       +-- Watchtower Keys (for penalty transactions)              |
|       |                                                           |
|       +-- Broadcast Keys (for transaction submission)             |
|                                                                   |
+------------------------------------------------------------------+
```

### 8.2 Key Rotation

| Key Type | Rotation Frequency | Trigger |
|----------|-------------------|---------|
| Ephemeral | Per session | Automatic |
| Channel | Channel close/open | As needed |
| Satellite identity | Mission lifetime | Compromise only |
| Operator signing | Annual | Policy or compromise |
| FROST shares | Proactive refresh | Quarterly or compromise |

### 8.3 Incident Response

| Incident | Immediate Action | Recovery |
|----------|-----------------|----------|
| Suspected key compromise | Revoke tokens, close channels | Rotate keys, re-establish |
| Ground station attack | Switch to backup station | Forensics, secure, restore |
| Satellite anomaly | Isolate from network | Diagnose, recover or decommission |
| Coordinated attack | Activate contingency channels | Coalition coordination |

---

## 9. Regulatory Considerations

### 9.1 Cryptographic Export Controls

| Jurisdiction | Regulation | SCRAP Status |
|--------------|------------|--------------|
| **USA** | EAR Category 5 Part 2 | Open source exception likely applies |
| **EU** | Dual-Use Regulation | Similar to USA |
| **ITAR** | Applies to defense articles | Implementation in defense satellite may be controlled |

**Key points:**
- Protocol specification is not controlled (publicly available)
- Implementation in specific satellite may be controlled
- Operators responsible for their own export compliance

### 9.2 Spectrum Considerations

ISL frequencies must be coordinated:
- ITU Radio Regulations apply
- National spectrum authorities for ground links
- SCRAP is frequency-agnostic (uses whatever ISL provides)

---

## 10. References

### Standards
- [NIST SP 800-57: Key Management](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
- [CNSSP-15: National Information Assurance Policy](https://www.cnss.gov/CNSS/issuances/Policies.cfm)

### Cryptographic Primitives
- [FROST: Flexible Round-Optimized Schnorr Threshold Signatures](https://eprint.iacr.org/2020/852)
- [ROAST: Robust Asynchronous Schnorr Threshold Signatures](https://eprint.iacr.org/2022/550)
- [BIP-340: Schnorr Signatures for secp256k1](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki)

### Space Security
- [CCSDS 350.0-G-3: Security Guide](https://public.ccsds.org/Pubs/350x0g3.pdf)
- [NIST IR 8270: Space Cybersecurity](https://csrc.nist.gov/publications/detail/nistir/8270/draft)

### SCRAP Specifications
- [SCRAP.md](SCRAP.md) - Primary protocol specification
- [SISL.md](SISL.md) - Secure Inter-Satellite Link (CCSDS integration)
- [BIP-SCRAP.md](BIP-SCRAP.md) - Informational BIP
