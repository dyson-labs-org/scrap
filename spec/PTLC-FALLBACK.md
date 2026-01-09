# SCRAP On-Chain PTLC Fallback Mode

## Status

This document describes an **on-chain fallback mode** for SCRAP that works without
BIP-118 (ANYPREVOUT). It creates individual PTLC outputs on-chain rather than
using ln-symmetry payment channels.

**Use this mode when:**
- BIP-118 is not yet activated
- Per-task on-chain fees are acceptable
- Channel infrastructure is not available
- High-value, infrequent tasks justify on-chain settlement

**Prefer the primary SCRAP specification ([SCRAP.md](SCRAP.md)) when:**
- BIP-118 is activated
- High transaction volume requires amortized fees
- Channel-based settlement is available

## Abstract

This document specifies an on-chain payment protocol for autonomous agent task
execution using Point Time-Locked Contracts (PTLCs) with adaptor signatures.
The gateway creates a single on-chain transaction with separate PTLC outputs
for each agent in the task chain. Each agent claims their payment by broadcasting
an on-chain transaction when the adaptor secret is revealed.

This approach trades higher per-task on-chain costs for simplicity: no channel
management, no ln-symmetry state machine, no watchtower requirements beyond
standard blockchain monitoring. Payment proofs remain cryptographically bound
to task acknowledgment via adaptor signatures.

**Protocol Requirement**: Bidirectional communication during task handoff. Each
hop requires a brief two-way exchange (task delivery + acknowledgment).

---

## Entity Definitions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GLOSSARY OF ENTITIES                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  This glossary defines the key entities referenced throughout this          │
│  document and ../future/CHANNELS.md.                                         │
│                                                                             │
│  CUSTOMER:                                                                  │
│  ─────────                                                                  │
│    The entity requesting and paying for a satellite task.                   │
│    - Initiates task request through gateway                                 │
│    - Provides Lightning HTLC payment                                        │
│    - Receives task output (data, imagery, etc.)                             │
│    - Does NOT operate satellites or ground stations                         │
│    - Cannot be the receiving ground station (prevents collusion)            │
│                                                                             │
│  SATELLITE:                                                                 │
│  ──────────                                                                 │
│    A spacecraft executing tasks in the payment chain.                       │
│    - Receives task packets via ISL or ground uplink                         │
│    - Executes computational tasks (imaging, relay, processing)              │
│    - Forwards results to next hop                                           │
│    - Holds payment keys derived from HSM root key                           │
│    - Does NOT make payment decisions autonomously                           │
│    - Revenue goes to its operator                                           │
│                                                                             │
│  OPERATOR:                                                                  │
│    A ground-based entity that owns/operates one or more satellites.         │
│    - Operates ground station(s) for satellite contact                       │
│    - Manages satellite keys and nonce pools                                 │
│    - Receives PTLC payments on behalf of satellites                         │
│    - Handles fee management and UTXO operations                             │
│    - Has contractual relationship with gateway                              │
│                                                                             │
│    FIRST OPERATOR:                                                          │
│      - Operates the first satellite in the task chain                       │
│      - Receives s_last from last operator (ground-to-ground)                │
│      - Publishes adaptor secret t to enable all payments                    │
│      - Has satellite in payment chain (skin in game)                        │
│                                                                             │
│    LAST OPERATOR:                                                           │
│      - Operates the last satellite in the task chain                        │
│      - Receives final task output at ground station                         │
│      - Signs delivery acknowledgment (generating s_last)                    │
│      - Sends s_last to first operator                                       │
│      - Has satellite in payment chain (skin in game)                        │
│                                                                             │
│    INTERMEDIATE OPERATOR:                                                   │
│      - Operates satellites between first and last                           │
│      - Receives PTLC payment like first/last operators                      │
│      - Doesn't participate in secret delivery                               │
│                                                                             │
│  GATEWAY:                                                                   │
│  ────────                                                                   │
│    The interface between Lightning Network and satellite task system.       │
│    - Accepts customer payments via Lightning HTLC                           │
│    - Creates Tx_1 with PTLC outputs for all satellites                      │
│    - Coordinates with operators to construct task chain                     │
│    - Manages nonce pre-commitments from satellites                          │
│    - Claims Lightning HTLC when adaptor secret t is revealed                │
│    - May be operated by first operator or independent entity                │
│                                                                             │
│    GATEWAY ≠ OPERATOR (necessarily):                                        │
│      Gateway may be independent, or may be operated by first operator.      │
│      Gateway has incentive alignment: receives Lightning payment only       │
│      after successful task completion (when t is revealed).                 │
│                                                                             │
│  GROUND STATION:                                                            │
│  ───────────────                                                            │
│    Physical infrastructure for satellite communication.                     │
│    - Uplinks task packets to satellites                                     │
│    - Downlinks task outputs and satellite data                              │
│    - Operated by satellite operators                                        │
│    - Limited contact windows based on orbital mechanics                     │
│                                                                             │
│  WATCHTOWER:                                                                │
│  ───────────                                                                │
│    Ground-based service monitoring blockchain for channel disputes.         │
│    - Monitors for old channel state broadcasts                              │
│    - Responds with latest state (LN-Symmetry rebinding)                     │
│    - Operated by operators for their satellites                             │
│    - See ../future/CHANNELS.md Section 7 for details                         │
│                                                                             │
│  ENTITY RELATIONSHIPS:                                                      │
│  ─────────────────────                                                      │
│                                                                             │
│    Customer ────pays────► Gateway ────creates────► Tx_1 (PTLCs)             │
│                             │                                               │
│                      coordinates                                            │
│                             │                                               │
│                             ▼                                               │
│    Operator ◄──────────► Operator ◄──────────► Operator                     │
│       │                     │                     │                         │
│    operates              operates              operates                     │
│       │                     │                     │                         │
│       ▼                     ▼                     ▼                         │
│    Sat_B ────[task]────► Sat_C ────[task]────► Sat_D                        │
│     (first)           (intermediate)           (last)                       │
│                                                                             │
│  TRUST BOUNDARIES:                                                          │
│  ─────────────────                                                          │
│    □ Customer trusts: Gateway (to forward payment)                          │
│    □ Gateway trusts: Operators (to have functioning satellites)             │
│    □ Operators trust: Each other (to complete task chain)                   │
│    □ Satellites trust: Their operator (for key management)                  │
│    □ NO entity trusts: Customer (customer has no privileged position)       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Motivation and Justifications

### 1.1 Why Not Standard Lightning Channels?

| Issue | Problem for Satellites | Our Solution |
|-------|------------------------|--------------|
| **Penalty mechanism** | Stale state = total fund loss | Individual UTXOs, no channel state |
| **Persistent connections** | ISL windows are 2-15 minutes | Pre-signed transactions, settle later |
| **Block height dependency** | Offline satellites can't verify chain state | Timestamp-based timelocks + GPS |
| **Channel rebalancing** | Complex with intermittent connectivity | Fungible UTXO pool |

### 1.2 Why Not eCash/Fedimint?

| Aspect | eCash | Our PTLC Approach |
|--------|-------|-------------------|
| Trust model | Trust federated mint | Trustless (Bitcoin script) |
| Proof of payment | Token transfer | Cryptographic (adaptor signature) |
| Task binding | None (bearer token) | Payment claim = task proof |
| Offline operation | Excellent | Excellent |
| Bitcoin integration | Requires mint | Native via Lightning gateway |

### 1.3 Why PTLCs Instead of HTLCs?

| Feature | HTLC | PTLC |
|---------|------|------|
| Lock mechanism | Hash preimage | Adaptor signature |
| On-chain footprint | Script with HASH160 | Keyspend (Taproot) |
| Proof of payment | Arbitrary preimage | **Signature on task receipt** |
| Task binding | Separate attestation needed | **Atomic with payment** |
| Privacy | Correlatable hash | Uncorrelatable adaptor points |

**Key advantage**: With PTLCs, the adaptor secret that unlocks payment IS an acknowledgment signature proving task receipt. Payment and proof are atomic.

---

## 2. Assumptions

### 2.1 Network Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ASSUMPTION: Bidirectional ISL during task handoff                           │
│                                                                             │
│ LEO satellite pass: 2-15 minute contact windows                             │
│ ISL latency: 1-50ms depending on distance                                   │
│ Protocol overhead per hop: ~100ms (delivery + ack)                          │
│ Available for task: 95%+ of contact window                                  │
│                                                                             │
│ Required exchange per hop:                                                  │
│   A ──[task packet]──► B     (~1-10KB, varies by task)                     │
│   A ◄──[ack signature]── B   (64 bytes)                                    │
│                                                                             │
│ Total per-hop overhead: <1 second for typical tasks                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Key Custody Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ASSUMPTION: Satellites hold exclusive custody of payment keys               │
│                                                                             │
│ - Private keys generated on satellite, never exported                       │
│ - Operators cannot spend satellite funds unilaterally                       │
│ - Eliminates operator double-spend risk                                     │
│ - Recovery via timelocked refund path (configurable, default 6 months)      │
│                                                                             │
│ Trust: Satellite software integrity (auditable, attested at manufacture)    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Time Synchronization

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ASSUMPTION: GPS-disciplined clocks with <1 second accuracy                  │
│                                                                             │
│ - Timelocks use Unix timestamps (not block heights)                         │
│ - CHECKLOCKTIMEVERIFY with value >= 500,000,000 = timestamp mode            │
│ - Bitcoin Median Time Past (MTP) can lag real time by ~2 hours              │
│ - All timelocks include 3-hour safety margin beyond MTP lag                 │
│ - Minimum timeout: 6 hours (accounts for MTP + safety + settlement)         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 Ground Station Availability

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ASSUMPTION: Ground stations provide eventual settlement, not real-time      │
│                                                                             │
│ - Satellites may operate for hours/days without ground contact              │
│ - Acknowledgment signatures (adaptor secrets) cached on satellite           │
│ - On-chain settlement happens when ground contact available                 │
│ - Ground stations bridge to Lightning for customer payments                 │
│                                                                             │
│ Ground contact requirements:                                                │
│ - Task initiation: Ground uploads task packet                               │
│ - Settlement: Satellites report ack signatures when convenient              │
│ - NOT required: During inter-satellite task execution                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Use Case: Time-Sensitive Event Response

### 3.1 Scenario: Emergency Imaging Request

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    DISASTER RESPONSE IMAGING CHAIN                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  EVENT: Earthquake detected in remote region                                │
│  REQUIREMENT: Imagery within 2 hours                                        │
│  CHALLENGE: No direct ground contact with imaging satellite                 │
│                                                                             │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐          │
│  │ Customer │     │ Relay    │     │ Imaging  │     │ Downlink │          │
│  │ Ground   │────►│ Sat (B)  │────►│ Sat (C)  │────►│ Sat (D)  │────┐     │
│  │ Station  │     │          │     │          │     │          │    │     │
│  └──────────┘     └──────────┘     └──────────┘     └──────────┘    │     │
│       │                                                              │     │
│       │◄─────────────────────────────────────────────────────────────┘     │
│       │                          Imagery delivered                         │
│                                                                             │
│  TIME BUDGET:                                                               │
│  - Ground to B upload: 30 seconds                                           │
│  - B to C relay + ack: 5 seconds                                            │
│  - C imaging setup: 30 seconds                                              │
│  - C to D handoff + ack: 10 seconds                                         │
│  - D to Ground downlink: 2 minutes                                          │
│  - Total execution: < 5 minutes                                             │
│                                                                             │
│  PAYMENT: Lightning (fast), not on-chain (slow)                             │
│  SETTLEMENT: Async, within timeout window                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Requirements Derived from Use Case

| Requirement | Rationale |
|-------------|-----------|
| **Sub-second payment setup** | Can't wait for block confirmations during task |
| **Multi-hop task routing** | Satellites not directly reachable from ground |
| **Payment per hop** | Each satellite earns for their contribution |
| **Offline settlement** | Ground contact not guaranteed during execution |
| **Lightning integration** | Customers pay from existing wallets |
| **Proof of delivery** | Cryptographic proof each hop completed |

---

## 4. Protocol Overview

### 4.1 Participants and Roles

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROTOCOL PARTICIPANTS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CUSTOMER                                                                   │
│    - Initiates task request via gateway                                     │
│    - Pays via Lightning HTLC                                                │
│    - Receives task output from last operator (after payment settles)        │
│                                                                             │
│  GATEWAY                                                                    │
│    - Bridges Lightning ↔ Satellite payments                                 │
│    - Maintains UTXO pool for satellite payments                             │
│    - Creates pre-signed PTLC transaction chains                             │
│    - Coordinates between first and last operators                           │
│    - May be same entity as first operator                                   │
│                                                                             │
│  FIRST OPERATOR                                                             │
│    - Operates first satellite in task chain (e.g., satellite B)             │
│    - Has ground station that uploads task to their satellite                │
│    - Receives delivery confirmation from last operator (ground-to-ground)   │
│    - Releases adaptor secret to enable all payments                         │
│    - Has skin in game: their satellite B is in the payment chain            │
│                                                                             │
│  LAST OPERATOR                                                              │
│    - Operates last satellite in task chain (e.g., satellite D)              │
│    - Has ground station that receives task output                           │
│    - Generates acknowledgment signature upon valid delivery                 │
│    - Sends ack signature to first operator (ground-to-ground link)          │
│    - Has skin in game: their satellite D is in the payment chain            │
│                                                                             │
│  INTERMEDIATE SATELLITES (C, ...)                                           │
│    - Execute assigned tasks (relay, image, process)                         │
│    - Forward task to next hop                                               │
│    - Claim PTLCs using revealed adaptor secret                              │
│    - Hold exclusive custody of payment keys                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Structural Requirement: Operator-Terminated Chains

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHAIN TERMINATION REQUIREMENT                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  REQUIREMENT: Task chains MUST terminate at operator ground stations        │
│                                                                             │
│  ┌───────────────────┐                              ┌───────────────────┐  │
│  │  First Operator   │                              │   Last Operator   │  │
│  │  Ground Station   │◄──── Ground Link ───────────│   Ground Station  │  │
│  │  (task upload)    │      (internet/dedicated)    │   (receives data) │  │
│  └─────────┬─────────┘                              └─────────┬─────────┘  │
│            │                                                  ▲            │
│            ▼                                                  │            │
│       ┌─────────┐      ┌─────────┐      ┌─────────┐         │            │
│       │  Sat B  │─────►│  Sat C  │─────►│  Sat D  │─────────┘            │
│       │ (first) │ ISL  │  (mid)  │ ISL  │ (last)  │  downlink            │
│       └─────────┘      └─────────┘      └─────────┘                       │
│            │                                 │                             │
│            └─────────────────────────────────┘                             │
│              Both operated by entities with satellites in chain            │
│                                                                             │
│  WHY THIS MATTERS:                                                          │
│    - First operator has satellite B in chain → wants payment to succeed    │
│    - Last operator has satellite D in chain → wants payment to succeed     │
│    - Neither can steal without also losing their own satellite's payment   │
│    - Customer does NOT operate receiving ground station                    │
│    - Customer receives data FROM last operator after payment settles       │
│                                                                             │
│  CUSTOMER DATA FLOW:                                                        │
│    Customer ──pay──► Gateway ──task──► [B → C → D] ──► Last Operator       │
│                                                              │              │
│    Customer ◄─────────────── data (after payment) ──────────┘              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           END-TO-END FLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1: SETUP (Ground)                                                    │
│  ─────────────────────────                                                  │
│  1. Customer requests task, pays Lightning invoice to gateway               │
│  2. Gateway coordinates with first operator and last operator               │
│  3. Last operator pre-commits nonce R_last for delivery acknowledgment      │
│  4. Gateway computes adaptor point T from last operator's commitment        │
│  5. Gateway creates pre-signed PTLC chain, ALL locked to same T             │
│  6. First operator uploads task to satellite B during ground pass           │
│                                                                             │
│  PHASE 2: EXECUTION (Satellite Network)                                     │
│  ───────────────────────────────────────                                    │
│  7. Task propagates forward: B → C → D (via ISL)                            │
│  8. Each hop verifies task, executes, forwards to next                      │
│  9. Satellite D delivers output to last operator's ground station           │
│                                                                             │
│  PHASE 3: ACKNOWLEDGMENT (Ground-to-Ground)                                 │
│  ───────────────────────────────────────────                                │
│  10. Last operator verifies delivery, signs ack: s_last = k + e·x_last      │
│  11. Last operator sends s_last to first operator (ground network)          │
│  12. First operator verifies s_last is valid signature                      │
│                                                                             │
│  PHASE 4: SETTLEMENT                                                        │
│  ───────────────────                                                        │
│  13. First operator (or gateway) publishes t = s_last                       │
│  14. All satellites claim PTLCs using t (same secret for all)               │
│  15. Gateway claims customer HTLC using t                                   │
│  16. Last operator releases data to customer                                │
│                                                                             │
│  ATOMIC PROPERTY:                                                           │
│    - Either s_last exists (delivery succeeded) → everyone gets paid         │
│    - Or s_last doesn't exist (delivery failed) → everyone times out         │
│    - No partial completion: all-or-nothing settlement                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Cryptographic Constructions

### 5.1 Schnorr Signatures (BIP 340)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SCHNORR SIGNATURE BASICS                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Key pair:                                                                  │
│    Private key: x ∈ Z_n (256-bit scalar)                                   │
│    Public key:  P = x·G (curve point, x-coordinate only per BIP 340)        │
│                                                                             │
│  Signing (message m):                                                       │
│    k = H_nonce(x || m) mod n     (deterministic nonce, RFC 6979 style)      │
│    R = k·G                                                                  │
│    e = H_challenge(R || P || m) mod n                                       │
│    s = k + e·x mod n                                                        │
│    Signature: (R, s) or just (r, s) where r = R.x                           │
│                                                                             │
│  Verification:                                                              │
│    e = H_challenge(R || P || m)                                             │
│    Check: s·G == R + e·P                                                    │
│                                                                             │
│  Hash functions (BIP 340 tagged hashes):                                    │
│    H_nonce = SHA256(SHA256("BIP0340/nonce") || SHA256("BIP0340/nonce") || .)│
│    H_challenge = SHA256(SHA256("BIP0340/challenge") || ... )                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Adaptor Signatures

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ADAPTOR SIGNATURE SCHEME                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Adaptor point: T = t·G  (t is the adaptor secret, a scalar)                │
│                                                                             │
│  Creating adaptor signature (signer has x, knows T but not t):              │
│  ──────────────────────────────────────────────────────────────             │
│    k = random nonce                                                         │
│    R = k·G                                                                  │
│    R' = R + T                      ← tweaked nonce point                    │
│    e = H_challenge(R' || P || m)   ← challenge uses R', not R               │
│    s' = k + e·x mod n              ← adaptor signature scalar               │
│                                                                             │
│    Output: (R, s', T)                                                       │
│                                                                             │
│  Verifying adaptor signature (verifier has P, T, m):                        │
│  ─────────────────────────────────────────────────────                      │
│    R' = R + T                                                               │
│    e = H_challenge(R' || P || m)                                            │
│    Check: s'·G == R + e·P          ← note: R not R'                         │
│                                                                             │
│  Completing adaptor signature (completer knows t):                          │
│  ─────────────────────────────────────────────────                          │
│    s = s' + t mod n                                                         │
│    Valid signature: (R', s)                                                 │
│                                                                             │
│  Extracting adaptor secret (from completed signature):                      │
│  ────────────────────────────────────────────────────                       │
│    Given (R, s') and valid (R', s):                                         │
│    t = s - s' mod n                                                         │
│                                                                             │
│  CRITICAL PROPERTY:                                                         │
│    Publishing a valid signature (R', s) reveals the adaptor secret t.       │
│    Anyone who knows the adaptor signature (R, s') can compute t = s - s'.   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Nonce Pre-Commitment Protocol

For acknowledgment signatures to serve as adaptor secrets, the acknowledging party must commit to their nonce BEFORE the task begins. This enables the gateway to construct the correct adaptor points.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NONCE PRE-COMMITMENT PROTOCOL                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SETUP PHASE (before task chain created):                                   │
│  ─────────────────────────────────────────                                  │
│                                                                             │
│  For each satellite S_i that will acknowledge (i.e., receive a task):       │
│                                                                             │
│    1. S_i generates nonce commitment:                                       │
│         k_i = random scalar (kept secret)                                   │
│         R_i = k_i·G (public nonce point)                                    │
│                                                                             │
│    2. S_i sends R_i to gateway (during routine ground contact)              │
│                                                                             │
│    3. Gateway stores {S_i → R_i} for task construction                      │
│                                                                             │
│  NONCE POOL:                                                                │
│  ───────────                                                                │
│    Satellites maintain pool of pre-committed nonces:                        │
│      - Generate batch of N nonces during ground contact                     │
│      - Upload all R_i values to gateway                                     │
│      - Track which nonces are used vs available                             │
│      - Replenish pool during subsequent ground passes                       │
│                                                                             │
│    Recommended pool size: 100+ nonces per satellite                         │
│    Rationale: Covers multiple task chains between ground contacts           │
│                                                                             │
│  SECURITY REQUIREMENTS:                                                     │
│  ──────────────────────                                                     │
│    - Nonce k_i MUST be used exactly once (reuse = key recovery attack)      │
│    - Satellite MUST track used nonces persistently                          │
│    - If nonce pool exhausted, satellite cannot participate until refresh    │
│                                                                             │
│  NONCE INDEX:                                                               │
│  ────────────                                                               │
│    Task packet includes nonce_index for each hop                            │
│    Satellite looks up k_{nonce_index} to sign acknowledgment                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.4 Acknowledgment as Adaptor Secret

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ACKNOWLEDGMENT = ADAPTOR SECRET                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Scenario: B delivers task to C. B's payment unlocks when C acknowledges.   │
│                                                                             │
│  SETUP (Gateway constructs):                                                │
│  ──────────────────────────                                                 │
│    Inputs:                                                                  │
│      - C's public key: P_C                                                  │
│      - C's pre-committed nonce: R_C (from nonce pool)                       │
│      - Acknowledgment message format: m = "ack:" || task_id || payload_hash │
│                                                                             │
│    Compute adaptor point for B's payment:                                   │
│      e_C = H_challenge(R_C || P_C || m)                                     │
│      T_B = R_C + e_C·P_C                                                    │
│                                                                             │
│    T_B is the adaptor point. The adaptor secret is:                         │
│      t_B = k_C + e_C·c_C  (which is exactly C's signature scalar!)          │
│                                                                             │
│  EXECUTION:                                                                 │
│  ──────────                                                                 │
│    1. B delivers task packet to C                                           │
│                                                                             │
│    2. C verifies packet, creates acknowledgment signature:                  │
│         m = "ack:" || task_id || H(payload)                                 │
│         e_C = H_challenge(R_C || P_C || m)                                  │
│         s_C = k_C + e_C·c_C mod n                                           │
│         Signature: (R_C, s_C)                                               │
│                                                                             │
│    3. C sends (R_C, s_C) back to B                                          │
│                                                                             │
│    4. B verifies signature is valid for C's public key                      │
│                                                                             │
│    5. B now has adaptor secret: t_B = s_C                                   │
│         (The signature scalar IS the adaptor secret!)                       │
│                                                                             │
│  WHY THIS WORKS:                                                            │
│  ───────────────                                                            │
│    T_B = R_C + e_C·P_C                                                      │
│        = k_C·G + e_C·c_C·G                                                  │
│        = (k_C + e_C·c_C)·G                                                  │
│        = s_C·G                                                              │
│                                                                             │
│    So t_B (discrete log of T_B) = s_C (C's signature scalar)                │
│                                                                             │
│  RESULT:                                                                    │
│    - C's acknowledgment signature unlocks B's payment                       │
│    - Single value serves both purposes                                      │
│    - Atomic binding: can't have payment without acknowledgment              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.5 Atomic PTLC Binding (Single Adaptor Secret)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ATOMIC PTLC BINDING VIA LAST OPERATOR                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PROBLEM:                                                                   │
│    Customer pays single Lightning HTLC with hash H.                         │
│    Multiple satellites (B, C, D) each have separate PTLCs.                  │
│    Need atomic settlement: all-or-nothing, no partial completion.           │
│                                                                             │
│  SOLUTION: Single adaptor secret from last operator's acknowledgment        │
│  ────────────────────────────────────────────────────────────────           │
│                                                                             │
│  For chain: First Operator → B → C → D → Last Operator                      │
│                                                                             │
│  SETUP:                                                                     │
│    1. Last operator pre-commits nonce R_last for acknowledgment             │
│    2. Expected ack message: m = "delivered:" || task_id || H(output_spec)   │
│    3. Compute adaptor point:                                                │
│         e = H_challenge(R_last || P_last || m)                              │
│         T = R_last + e·P_last                                               │
│    4. ALL PTLCs in chain locked to SAME adaptor point T                     │
│         - PTLC_B locked to T                                                │
│         - PTLC_C locked to T                                                │
│         - PTLC_D locked to T                                                │
│    5. Lightning HTLC: preimage = t (the adaptor secret = s_last)            │
│         H = SHA256(t), customer's HTLC locked to H                          │
│                                                                             │
│  EXECUTION:                                                                 │
│    1. Task propagates: B → C → D → Last operator's ground station           │
│    2. Last operator receives output, verifies validity                      │
│    3. Last operator signs: s_last = k_last + e·x_last                       │
│    4. s_last IS the adaptor secret t (discrete log of T)                    │
│                                                                             │
│  SETTLEMENT:                                                                │
│    5. Last operator sends s_last to first operator (ground-to-ground)       │
│    6. First operator/gateway publishes t = s_last                           │
│    7. ALL satellites claim PTLCs using same t                               │
│    8. Gateway claims customer HTLC using t as preimage                      │
│                                                                             │
│  ATOMIC PROPERTY:                                                           │
│  ────────────────                                                           │
│    SUCCESS PATH:                                                            │
│      D delivers → Last operator acks (s_last exists) → Everyone claims      │
│                                                                             │
│    FAILURE PATH:                                                            │
│      Delivery fails → No s_last → Nobody claims → All timeout refund        │
│                                                                             │
│    NO PARTIAL COMPLETION:                                                   │
│      - Cannot have B paid but C unpaid                                      │
│      - All PTLCs share same adaptor secret                                  │
│      - Either all unlock or none unlock                                     │
│                                                                             │
│  TRUST ANALYSIS:                                                            │
│  ───────────────                                                            │
│    Last operator could: Receive delivery, refuse to sign s_last             │
│    BUT: Last operator's satellite D is in the chain                         │
│         If s_last not released, D doesn't get paid either                   │
│         Last operator has no incentive to withhold                          │
│                                                                             │
│    First operator could: Receive s_last, refuse to publish                  │
│    BUT: First operator's satellite B is in the chain                        │
│         If t not published, B doesn't get paid either                       │
│         First operator has no incentive to withhold                         │
│                                                                             │
│    Collusion attack: Last operator + Customer collude                       │
│    PREVENTED BY: Customer does NOT operate receiving ground station         │
│                  Last operator is satellite operator with skin in game      │
│                                                                             │
│  GROUND-TO-GROUND LINK:                                                     │
│  ──────────────────────                                                     │
│    s_last travels: Last operator ground → First operator ground             │
│    This is terrestrial (internet, dedicated link), NOT via satellite        │
│    Satellite chain only goes forward due to orbital mechanics               │
│                                                                             │
│  AUTHENTICATED SECRET DELIVERY:                                             │
│  ──────────────────────────────                                             │
│    The s_last transmission MUST be authenticated to prevent:                │
│      - Man-in-the-middle substitution attacks                               │
│      - Replay attacks from previous tasks                                   │
│      - Impersonation of last operator                                       │
│                                                                             │
│    DELIVERY MESSAGE FORMAT:                                                 │
│    {                                                                        │
│      "task_id": <16 bytes>,                                                 │
│      "adaptor_secret": s_last,                        // 32 bytes           │
│      "delivery_hash": H(output_data),                 // 32 bytes           │
│      "timestamp": <unix_timestamp>,                   // 8 bytes            │
│      "auth_signature": sig_last                       // 64 bytes           │
│    }                                                                        │
│                                                                             │
│    auth_signature = Schnorr_sign(P_last_ground, m_auth)                     │
│    m_auth = "secret_delivery:" || task_id || s_last || delivery_hash || ts  │
│                                                                             │
│    P_last_ground is the last operator's ground station identity key,        │
│    distinct from the nonce key used for the adaptor point.                  │
│                                                                             │
│    FIRST OPERATOR VERIFICATION:                                             │
│      1. Verify auth_signature against known P_last_ground                   │
│      2. Verify task_id matches expected in-flight task                      │
│      3. Verify timestamp is recent (within replay window)                   │
│      4. Verify s_last·G == T (adaptor point from task setup)                │
│      5. Store delivery_hash for customer data release verification          │
│                                                                             │
│    REPLAY PREVENTION:                                                       │
│      - task_id is unique per task                                           │
│      - timestamp prevents replay of old deliveries                          │
│      - First operator tracks delivered task_ids                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.6 Adaptor Point Derivation Summary

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ADAPTOR POINT CONSTRUCTION (ATOMIC)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  For chain: First Operator → B → C → D → Last Operator                      │
│                                                                             │
│  SINGLE ADAPTOR POINT FOR ALL HOPS:                                         │
│  ───────────────────────────────────                                        │
│    All PTLCs in chain use the SAME adaptor point T, derived from            │
│    the last operator's delivery acknowledgment.                             │
│                                                                             │
│  ┌────────┬─────────────────────────┬───────────────────────────────────┐  │
│  │  Hop   │ Adaptor point           │ Adaptor secret                    │  │
│  ├────────┼─────────────────────────┼───────────────────────────────────┤  │
│  │   B    │ T = R_last + e·P_last   │ t = s_last (last operator's sig)  │  │
│  │   C    │ T = R_last + e·P_last   │ t = s_last (same for all)         │  │
│  │   D    │ T = R_last + e·P_last   │ t = s_last (same for all)         │  │
│  └────────┴─────────────────────────┴───────────────────────────────────┘  │
│                                                                             │
│  DERIVATION:                                                                │
│  ───────────                                                                │
│    R_last = last operator's pre-committed nonce                             │
│    P_last = last operator's ground station public key                       │
│    m = "delivered:" || task_id || H(expected_output)                        │
│    e = H_challenge(R_last || P_last || m)                                   │
│    T = R_last + e·P_last                                                    │
│                                                                             │
│    When last operator signs delivery acknowledgment:                        │
│      s_last = k_last + e·x_last                                             │
│      t = s_last (this is the adaptor secret, discrete log of T)             │
│                                                                             │
│  ATOMIC PROPERTY:                                                           │
│  ────────────────                                                           │
│    - All PTLCs unlock with same t                                           │
│    - t only exists if last operator acknowledges delivery                   │
│    - Either all satellites can claim, or none can                           │
│    - No partial completion possible                                         │
│                                                                             │
│  LIGHTNING BINDING:                                                         │
│  ──────────────────                                                         │
│    Customer HTLC uses same secret:                                          │
│      preimage = t = s_last                                                  │
│      H = SHA256(preimage)                                                   │
│    Gateway can claim customer HTLC using same t that unlocks PTLCs          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Transaction Structure

### 6.1 PTLC Output Script (Taproot)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PTLC TAPROOT STRUCTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Each PTLC output uses Taproot (P2TR) with the following structure:         │
│                                                                             │
│  INTERNAL KEY (for key path spend):                                         │
│  ─────────────────────────────────                                          │
│    MuSig2 key aggregation (BIP 327):                                        │
│                                                                             │
│      L = H_agg(P_gateway || P_satellite)    (lexicographic order)           │
│      a_gw = H_agg_coef(L || P_gateway)                                      │
│      a_sat = H_agg_coef(L || P_satellite)                                   │
│      P_internal = a_gw·P_gateway + a_sat·P_satellite                        │
│                                                                             │
│    The coefficient multiplication prevents rogue key attacks where one      │
│    party chooses their key as P' = P_target - P_other to control output.    │
│                                                                             │
│    This is a 2-of-2 MuSig2 aggregate key.                                   │
│    Key path spend requires cooperation of both parties.                     │
│                                                                             │
│  SCRIPT TREE:                                                               │
│  ────────────                                                               │
│    Leaf 0 (Satellite claim with adaptor):                                   │
│      <P_satellite> OP_CHECKSIG                                              │
│                                                                             │
│      Satellite's own key. Satellite creates adaptor signature locked to T.  │
│      Satellite completes signature when they learn t = s_last.              │
│      This is the UNIFIED adaptor convention (same as payment channels).     │
│                                                                             │
│    Leaf 1 (Gateway timeout refund - CSV):                                   │
│      <timeout_blocks> OP_CHECKSEQUENCEVERIFY OP_DROP <P_gateway> OP_CHECKSIG│
│                                                                             │
│      Uses CSV (relative timelock) instead of CLTV (absolute).               │
│      Timeout is relative to Tx_1 confirmation, not wall clock.              │
│      Example: <36> means 36 blocks (~6 hours) after PTLC output created.    │
│                                                                             │
│  TAPROOT OUTPUT:                                                            │
│  ───────────────                                                            │
│    Q = P_internal + H_taptweak(P_internal || merkle_root)·G                 │
│                                                                             │
│  SPENDING PATHS:                                                            │
│  ───────────────                                                            │
│                                                                             │
│    Path A: Cooperative close (key path)                                     │
│      - Gateway and satellite cooperate via MuSig2                           │
│      - Single aggregate signature                                           │
│      - Most private, smallest on-chain footprint                            │
│      - Used for routine settlement when both parties online                 │
│                                                                             │
│    Path B: Satellite claim with adaptor (script path, leaf 0)               │
│      - Gateway provides adaptor point T in task packet                      │
│      - Satellite creates adaptor signature using own key P_satellite:       │
│          k = nonce from pool                                                │
│          R = k·G                                                            │
│          R' = R + T                                                         │
│          e = H_challenge(R' || P_satellite || claim_tx)                     │
│          s' = k + e·x_satellite                                             │
│          adaptor_sig = (R, s')                                              │
│      - Satellite stores adaptor_sig locally                                 │
│      - When task completes, satellite learns t = s_last                     │
│      - Satellite completes: s = s' + t, R' = R + T                          │
│      - Satellite broadcasts claim_tx with signature (R', s)                 │
│      - Signature verifies: s·G = R' + e·P_satellite ✓                       │
│      - Anyone can extract: t = s - s' (adaptor secret revealed)             │
│                                                                             │
│      SECURITY: Satellite uses own key, controls own claim.                  │
│      Gateway cannot claim (doesn't have satellite's private key).           │
│      Satellite cannot claim without t (adaptor sig incomplete).             │
│                                                                             │
│    Path C: Gateway timeout refund (script path, leaf 1)                     │
│      - After timeout_blocks have passed since Tx_1 confirmed                │
│      - CSV ensures full execution window regardless of Tx_1 timing          │
│      - Gateway signs with P_gateway                                         │
│      - Used if task fails (no t released) - gateway reclaims all PTLCs      │
│                                                                             │
│  UNIFIED ADAPTOR CONVENTION:                                                │
│  ───────────────────────────                                                │
│    This script structure is IDENTICAL to payment channel PTLCs              │
│    (see ../future/CHANNELS.md). The unified convention:                      │
│      □ Receiver (satellite) creates adaptor signature                       │
│      □ Receiver uses own key in claim script                                │
│      □ Adaptor point T provided by protocol (task or channel)               │
│      □ Receiver completes sig when t learned                                │
│      □ Observer extracts t from completed signature                         │
│                                                                             │
│    This enables smooth upgrade from on-chain PTLCs to payment channels.     │
│    Same HSM operations, same signature flow, same script structure.         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Pre-Signed Transaction Chain

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FUNDING TRANSACTION (Tx_1)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Tx_1 creates all PTLC outputs in a single v3 transaction with ephemeral    │
│  anchor, enabling decentralized fee bumping by any operator in the chain.   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Tx_1 (v3, zero fee):                                                │   │
│  │                                                                     │   │
│  │   nVersion: 3                                                       │   │
│  │   nLocktime: 0                                                      │   │
│  │                                                                     │   │
│  │   Inputs:                                                           │   │
│  │     [0] Gateway funding UTXO (10,000 sats)                          │   │
│  │                                                                     │   │
│  │   Outputs:                                                          │   │
│  │     [0] PTLC_B: 1,000 sats (satellite B's payment)                  │   │
│  │     [1] PTLC_C: 5,000 sats (satellite C's payment)                  │   │
│  │     [2] PTLC_D: 2,000 sats (satellite D's payment)                  │   │
│  │     [3] Gateway change: 2,000 sats                                  │   │
│  │     [4] Ephemeral anchor: 0 sats, scriptPubKey = OP_TRUE            │   │
│  │                                                                     │   │
│  │   Fee: 0 sats (paid via CPFP on ephemeral anchor)                   │   │
│  │   Signed by: Gateway (complete signature)                           │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  EPHEMERAL ANCHOR PROPERTIES:                                               │
│  ────────────────────────────                                               │
│    - Zero-value output with OP_TRUE script (anyone can spend)               │
│    - Enables CPFP fee bumping by ANY party with economic interest           │
│    - V3 transaction rules prevent pinning attacks                           │
│    - Must be spent in same block (ephemeral = not stored in UTXO set)       │
│                                                                             │
│  WHO CAN FEE-BUMP Tx_1:                                                     │
│  ──────────────────────                                                     │
│    Any operator with:                                                       │
│      □ Tx_1 transaction data (included in task packet)                      │
│      □ A fee UTXO to fund the CPFP child                                    │
│      □ Ground station to broadcast                                          │
│                                                                             │
│    Parties with incentive to bump:                                          │
│      • Gateway (wants customer HTLC payment)                                │
│      • First operator (satellite B's payment depends on confirmation)       │
│      • Last operator (satellite D's payment depends on confirmation)        │
│      • Any intermediate operator (their satellite's payment)                │
│                                                                             │
│  CPFP CHILD (created by any operator at broadcast time):                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │   Inputs:                                                           │   │
│  │     [0] Ephemeral anchor from Tx_1 (output 4, 0 sats)               │   │
│  │     [1] Operator's fee UTXO                                         │   │
│  │                                                                     │   │
│  │   Outputs:                                                          │   │
│  │     [0] Operator's change address                                   │   │
│  │                                                                     │   │
│  │   Fee: Calculated for current mempool (pays for Tx_1 + child)       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  FEE BUMPING SCENARIOS:                                                     │
│  ──────────────────────                                                     │
│    Normal: Gateway broadcasts Tx_1 + CPFP child, confirms                   │
│    Gateway slow: First operator creates CPFP child, broadcasts              │
│    Fee spike: Any operator RBFs existing child with higher fee              │
│                                                                             │
│    V3 rule: Only one child in mempool at a time                             │
│    Higher-fee child replaces lower-fee child (RBF)                          │
│    All operators want same outcome → competition only helps                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2.1 Adaptor Signatures (Atomic Model)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ADAPTOR SIGNATURES FOR PTLC CLAIMS                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  All PTLCs share the SAME adaptor point T, derived from last operator's     │
│  delivery acknowledgment (atomic model - see Section 5.5).                  │
│                                                                             │
│  ADAPTOR POINT (same for all):                                              │
│  ─────────────────────────────                                              │
│    T = R_last + e·P_last                                                    │
│    where:                                                                   │
│      R_last = last operator's pre-committed nonce                           │
│      P_last = last operator's ground station public key                     │
│      e = H_challenge(R_last || P_last || delivery_message)                  │
│                                                                             │
│  ADAPTOR SIGNATURES (SATELLITE creates, not gateway):                       │
│  ─────────────────────────────────────────────────────                      │
│    Each satellite creates their OWN adaptor signature locked to T.          │
│    This is the UNIFIED convention shared with payment channels.             │
│                                                                             │
│    Satellite B creates: AdaptorSig_B for ClaimTx_B, locked to T             │
│    Satellite C creates: AdaptorSig_C for ClaimTx_C, locked to T             │
│    Satellite D creates: AdaptorSig_D for ClaimTx_D, locked to T             │
│                                                                             │
│    All locked to SAME T → all unlocked by same t = s_last                   │
│                                                                             │
│  WHAT GATEWAY PROVIDES (in task packet):                                    │
│  ───────────────────────────────────────                                    │
│    All satellites receive:                                                  │
│      □ Tx_1 (full transaction for fee-bump capability)                      │
│      □ Adaptor point T (same for all)                                       │
│      □ Last operator's pubkey P_last and nonce R_last (for T verification)  │
│      □ Their PTLC output index in Tx_1                                      │
│      □ Claim address (where funds go)                                       │
│      □ Timeout value (CSV blocks)                                           │
│                                                                             │
│    Gateway does NOT provide adaptor signatures - satellites create them.    │
│                                                                             │
│  WHAT SATELLITE DOES (on receiving task packet):                            │
│  ───────────────────────────────────────────────                            │
│    1. Verify Tx_1 creates valid PTLC output for this satellite              │
│    2. Verify T = R_last + e·P_last (adaptor point correctly derived)        │
│    3. Construct claim_tx: spends PTLC output to satellite's address         │
│    4. Create adaptor signature for claim_tx locked to T:                    │
│         k = nonce from unified pool                                         │
│         R = k·G                                                             │
│         R' = R + T                                                          │
│         e = H_challenge(R' || P_satellite || claim_tx)                      │
│         s' = k + e·x_satellite                                              │
│         adaptor_sig = (R, s')                                               │
│    5. Store (adaptor_sig, claim_tx, T) for later claim                      │
│                                                                             │
│  CLAIM PROCESS (when t learned):                                            │
│  ───────────────────────────────                                            │
│    1. Satellite learns t = s_last (from task completion)                    │
│    2. Complete signature: s = s' + t, R' = R + T                            │
│    3. Broadcast claim_tx with signature (R', s)                             │
│    4. Anyone can extract t = s - s' from on-chain signature                 │
│                                                                             │
│  BENEFITS OF SATELLITE-CREATES-ADAPTOR:                                     │
│  ──────────────────────────────────────                                     │
│    □ Satellite uses own key (cleaner trust model)                           │
│    □ Gateway cannot redirect funds (doesn't have satellite's key)           │
│    □ Same convention as payment channels (unified upgrade path)             │
│    □ Simpler task packet (no adaptor signatures to include)                 │
│    □ Same HSM operations for both on-chain and channel PTLCs                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2.2 Tx_1 Broadcast Timing

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TX_1 BROADCAST TIMING REQUIREMENTS                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CRITICAL ISSUE:                                                            │
│  ───────────────                                                            │
│    If gateway broadcasts task to satellite B before Tx_1 confirms:          │
│      - Gateway could double-spend the funding UTXO                          │
│      - Satellites execute task but PTLC outputs never exist                 │
│      - Satellites did work but cannot claim payment                         │
│                                                                             │
│  SOLUTION: Mempool verification + confirmation requirements                 │
│  ──────────────────────────────────────────────────────────                 │
│                                                                             │
│  GATEWAY BROADCAST SEQUENCE:                                                │
│  ──────────────────────────                                                 │
│    1. Gateway creates Tx_1 + CPFP child                                     │
│    2. Gateway broadcasts Tx_1 package to Bitcoin network                    │
│    3. Gateway waits for mempool acceptance (not confirmation)               │
│    4. Gateway verifies Tx_1 accepted into mempool                           │
│    5. Gateway may now upload task to first satellite (B)                    │
│                                                                             │
│  MEMPOOL VERIFICATION:                                                      │
│  ─────────────────────                                                      │
│    Gateway queries its own Bitcoin full node:                               │
│      - Verify Tx_1 accepted into local mempool                              │
│      - Check no conflicting transactions (same inputs)                      │
│      - Confirm fee rate sufficient for expected confirmation time           │
│                                                                             │
│    One mempool check is sufficient because:                                 │
│      - Gateway controls broadcast timing                                    │
│      - Double-spend requires gateway malfeasance (self-harming)             │
│      - Operators can independently verify before upload (fallback)          │
│                                                                             │
│  CONFIRMATION REQUIREMENT (OPTIONAL STRICTER MODE):                         │
│  ─────────────────────────────────────────────────                          │
│    For high-value tasks, gateway MAY wait for confirmation:                 │
│      - 1 confirmation: Basic security                                       │
│      - 3 confirmations: Strong security against reorg                       │
│                                                                             │
│    Trade-off: Confirmation waiting adds 10-60 minutes latency               │
│               Most tasks can proceed with mempool-only verification         │
│                                                                             │
│  SATELLITE VERIFICATION:                                                    │
│  ───────────────────────                                                    │
│    Satellite B cannot verify mempool/blockchain (offline).                  │
│    Satellite trusts that gateway followed broadcast protocol.               │
│    Satellite's protection: Adaptor signature binds payment to task.         │
│                                                                             │
│    If Tx_1 never confirms:                                                  │
│      - Task completes, s_last generated                                     │
│      - Satellites try to claim PTLCs                                        │
│      - Claims fail (PTLC outputs don't exist)                               │
│      - Satellites report claim failure during next ground contact           │
│      - Gateway flagged/blacklisted by operators                             │
│                                                                             │
│  OPERATOR FALLBACK:                                                         │
│  ──────────────────                                                         │
│    Any operator receiving task packet can independently verify Tx_1:        │
│      - First operator checks Tx_1 in mempool before uploading to B          │
│      - If not in mempool, refuses to upload task                            │
│      - Task aborts cleanly before any satellite work                        │
│                                                                             │
│    This provides redundant verification beyond gateway.                     │
│                                                                             │
│  DOUBLE-SPEND DETECTION:                                                    │
│  ───────────────────────                                                    │
│    If gateway's funding UTXO appears in conflicting transaction:            │
│      - Operators detect via mempool monitoring                              │
│      - Task upload blocked/aborted                                          │
│      - Gateway blacklisted for attempted fraud                              │
│                                                                             │
│  TIMING DIAGRAM:                                                            │
│  ───────────────                                                            │
│                                                                             │
│    T+0:     Gateway creates Tx_1                                            │
│    T+0:     Gateway broadcasts Tx_1 + CPFP child                            │
│    T+2s:    Gateway verifies mempool acceptance                             │
│    T+5s:    First operator verifies mempool (optional)                      │
│    T+10s:   Task uploaded to satellite B                                    │
│    T+10min: Tx_1 confirms (typical)                                         │
│    T+1h:    Task completes, s_last available                                │
│    T+1.5h:  PTLC claims broadcast                                           │
│                                                                             │
│    Note: Task upload does NOT wait for Tx_1 confirmation.                   │
│    CSV timeout ensures claim window is relative to confirmation.            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Unified Timeout Structure (CSV)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED TIMEOUT (ATOMIC MODEL)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ATOMIC MODEL = SINGLE TIMEOUT:                                             │
│  ───────────────────────────────                                            │
│    All PTLCs share the same adaptor secret t = s_last.                      │
│    Either ALL claims succeed (t released) or ALL timeout (no t).            │
│    No cascading timeouts needed - all PTLCs have SAME timeout.              │
│                                                                             │
│  TIMEOUT STRUCTURE:                                                         │
│  ──────────────────                                                         │
│                                                                             │
│    ┌────────────────────────────────────────────────────────────────────┐  │
│    │  PTLC_B timeout: N + 36 blocks   (CSV, relative to Tx_1 confirm)   │  │
│    │  PTLC_C timeout: N + 36 blocks   (same)                            │  │
│    │  PTLC_D timeout: N + 36 blocks   (same)                            │  │
│    │                                                                    │  │
│    │  Customer HTLC:  T_now + 8 hours (CLTV, absolute - Lightning req)  │  │
│    └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│    ONLY CONSTRAINT: PTLC timeout < HTLC timeout                             │
│    Gateway must reclaim PTLCs before customer HTLC expires.                 │
│                                                                             │
│  WHY CSV (RELATIVE) INSTEAD OF CLTV (ABSOLUTE):                             │
│  ──────────────────────────────────────────────                             │
│                                                                             │
│    For short tasks (< 1 hour execution), absolute timeouts are problematic: │
│                                                                             │
│    PROBLEM WITH CLTV:                                                       │
│      - Task created at T+0, timeout set to T+6h (absolute)                  │
│      - Tx_1 delayed by fee spike, confirms at T+2h                          │
│      - Effective execution window: 4 hours (lost 2 hours)                   │
│      - MTP lag can consume another 2-3 hours                                │
│      - Risk: timeout expires before task completes                          │
│                                                                             │
│    SOLUTION WITH CSV:                                                       │
│      - Timeout = 36 blocks after Tx_1 confirms                              │
│      - Tx_1 confirms at T+2h (block N)                                      │
│      - Timeout at block N+36 (~T+8h)                                        │
│      - Full 6-hour window preserved regardless of Tx_1 timing               │
│      - No MTP vulnerability (CSV uses block height, not wall clock)         │
│                                                                             │
│  EXAMPLE CONFIGURATIONS:                                                    │
│  ───────────────────────                                                    │
│                                                                             │
│    FAST TASK (< 1 hour execution):                                          │
│    ┌───────────────┬────────────────────────────────────────────────────┐  │
│    │ Component     │ Value                                              │  │
│    ├───────────────┼────────────────────────────────────────────────────┤  │
│    │ Execution     │ ~30-60 minutes                                     │  │
│    │ PTLC timeout  │ 36 blocks (~6 hours from Tx_1 confirm)             │  │
│    │ HTLC timeout  │ task_start + 8 hours (absolute)                    │  │
│    │ Buffer        │ ~2 hours between PTLC timeout and HTLC timeout     │  │
│    └───────────────┴────────────────────────────────────────────────────┘  │
│                                                                             │
│    STANDARD TASK (longer execution, more buffer):                           │
│    ┌───────────────┬────────────────────────────────────────────────────┐  │
│    │ Component     │ Value                                              │  │
│    ├───────────────┼────────────────────────────────────────────────────┤  │
│    │ Execution     │ ~1-4 hours                                         │  │
│    │ PTLC timeout  │ 144 blocks (~24 hours from Tx_1 confirm)           │  │
│    │ HTLC timeout  │ task_start + 36 hours (absolute)                   │  │
│    │ Buffer        │ ~12 hours between PTLC timeout and HTLC timeout    │  │
│    └───────────────┴────────────────────────────────────────────────────┘  │
│                                                                             │
│  SUCCESS PATH:                                                              │
│  ─────────────                                                              │
│    Task completes → s_last released → t available                           │
│    All satellites claim simultaneously using same t                         │
│    No timeout ordering matters - claims don't depend on each other          │
│                                                                             │
│  FAILURE PATH:                                                              │
│  ─────────────                                                              │
│    Task fails → no s_last → no t available                                  │
│    All PTLCs timeout at same block (N + timeout_blocks)                     │
│    Gateway reclaims all PTLCs in single batched transaction                 │
│    Customer HTLC times out → refund to customer                             │
│                                                                             │
│  GATEWAY TIMING VALIDATION:                                                 │
│  ──────────────────────────                                                 │
│    Before initiating task, gateway verifies:                                │
│      1. Tx_1 is in mempool or confirmed                                     │
│      2. Expected Tx_1 confirm time + PTLC CSV < HTLC timeout                │
│      3. Sufficient buffer for settlement                                    │
│                                                                             │
│    If timing doesn't work (e.g., fee spike delaying Tx_1):                  │
│      - Gateway waits or aborts before uploading task                        │
│      - Never uploads task if PTLC timeout would exceed HTLC timeout         │
│                                                                             │
│  CAPITAL EFFICIENCY:                                                        │
│  ───────────────────                                                        │
│    Unified timeout enables batched refund on failure:                       │
│      - Single transaction reclaims all PTLCs                                │
│      - One fee payment instead of multiple                                  │
│      - Simpler state management for gateway                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Minimum Payments and Dust Limits

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MINIMUM PAYMENT ANALYSIS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DUST THRESHOLD:                                                            │
│  ───────────────                                                            │
│    P2TR outputs: 330 satoshis (at default dust relay fee)                   │
│    Outputs below this are non-standard and won't relay.                     │
│                                                                             │
│  ECONOMIC MINIMUM:                                                          │
│  ─────────────────                                                          │
│    Beyond dust, payments must cover claim transaction costs:                │
│                                                                             │
│    PTLC claim transaction (script path):                                    │
│      - Input: ~57 vbytes (P2TR script path spend)                           │
│      - Output: ~43 vbytes (P2TR output to satellite address)                │
│      - Witness: ~65 vbytes (signature + control block)                      │
│      - Total: ~165 vbytes                                                   │
│                                                                             │
│    At various fee rates:                                                    │
│      ┌───────────────┬────────────────┬─────────────────────┐              │
│      │ Fee Rate      │ Claim Cost     │ Minimum Viable PTLC │              │
│      ├───────────────┼────────────────┼─────────────────────┤              │
│      │ 1 sat/vB      │ 165 sats       │ ~500 sats           │              │
│      │ 5 sat/vB      │ 825 sats       │ ~1,500 sats         │              │
│      │ 20 sat/vB     │ 3,300 sats     │ ~5,000 sats         │              │
│      │ 50 sat/vB     │ 8,250 sats     │ ~12,000 sats        │              │
│      └───────────────┴────────────────┴─────────────────────┘              │
│                                                                             │
│    "Minimum Viable" = claim cost + reasonable profit margin (~2x cost)      │
│                                                                             │
│  BATCHING FOR SMALL PAYMENTS:                                               │
│  ────────────────────────────                                               │
│    For payments below economic minimum, satellites can:                     │
│                                                                             │
│    1. Accumulate multiple PTLCs before claiming                             │
│       - Wait for N tasks to complete                                        │
│       - Claim all PTLCs in single transaction                               │
│       - Amortize per-input cost across multiple claims                      │
│                                                                             │
│    2. Use cooperative settlement (key path)                                 │
│       - Gateway batches multiple satellite payments                         │
│       - Single transaction settles many PTLCs                               │
│       - Requires gateway cooperation but much cheaper                       │
│                                                                             │
│    3. Aggregate via Lightning (future extension)                            │
│       - Satellites open channels with gateway                               │
│       - PTLCs update channel balance instead of on-chain                    │
│       - Periodic on-chain settlement                                        │
│                                                                             │
│  RECOMMENDED MINIMUMS:                                                      │
│  ─────────────────────                                                      │
│    Conservative (always profitable): 2,000 sats per hop                     │
│    With batching assumed: 500 sats per hop                                  │
│    Absolute floor (dust limit): 330 sats per hop                            │
│                                                                             │
│  GATEWAY RESPONSIBILITY:                                                    │
│  ───────────────────────                                                    │
│    Gateway should reject task requests where:                               │
│      - Any hop payment < dust threshold (330 sats)                          │
│      - Total fees exceed 50% of hop payment                                 │
│    Gateway should warn customers when:                                      │
│      - Hop payments are in "batching required" range (330-2000 sats)        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.5 Ground-Based Fee Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    GROUND-BASED FEE MANAGEMENT                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DESIGN PRINCIPLE:                                                          │
│  ─────────────────                                                          │
│    Satellites are frequently disconnected and cannot monitor mempool        │
│    fee rates. ALL fee management is handled by ground stations.             │
│    Satellites are passive recipients of funds.                              │
│                                                                             │
│  BROADCAST RESPONSIBILITY:                                                  │
│  ─────────────────────────                                                  │
│                                                                             │
│    Satellite Claim Transactions:                                            │
│      → Gateway/First Operator broadcasts on behalf of satellites            │
│      → Ground station sets fee at broadcast time via CPFP                   │
│      → Satellites receive funds passively                                   │
│                                                                             │
│    Timeout Refund Transactions:                                             │
│      → Gateway broadcasts after timeout expires                             │
│      → Gateway sets fee via CPFP based on current mempool                   │
│                                                                             │
│    Customer HTLC Claim:                                                     │
│      → Gateway claims on Lightning Network                                  │
│      → Standard Lightning fee handling                                      │
│                                                                             │
│  WHY GATEWAY CAN BROADCAST SATELLITE CLAIMS:                                │
│  ───────────────────────────────────────────                                │
│    Gateway has all components needed:                                       │
│      - Pre-created adaptor signature (R, s') for each PTLC                  │
│      - Adaptor secret t = s_last (received from last operator)              │
│      - Completed signature: s = s' + t (gateway computes this)              │
│      - Transaction template (pre-signed)                                    │
│                                                                             │
│    The completed signature is valid regardless of who broadcasts.           │
│    Transaction pays to satellite's address (verified at task setup).        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.6 Anchor Output Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ANCHOR OUTPUT FOR CPFP FEE BUMPING                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Each pre-signed claim transaction includes a gateway-controlled anchor     │
│  output enabling CPFP fee adjustment at broadcast time.                     │
│                                                                             │
│  CLAIM TRANSACTION STRUCTURE:                                               │
│  ────────────────────────────                                               │
│                                                                             │
│    PRE-SIGNED CLAIM TX (zero fee):                                          │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │  Version: 2                                                         │  │
│    │  Locktime: 0                                                        │  │
│    │                                                                     │  │
│    │  Inputs:                                                            │  │
│    │    [0] PTLC output                                                  │  │
│    │        scriptSig: (empty for P2TR)                                  │  │
│    │        witness: <completed_adaptor_sig> <script> <control_block>    │  │
│    │                                                                     │  │
│    │  Outputs:                                                           │  │
│    │    [0] Satellite payment: PTLC_value - 330 sats                     │  │
│    │        scriptPubKey: P2TR(satellite_address)                        │  │
│    │                                                                     │  │
│    │    [1] Gateway anchor: 330 sats                                     │  │
│    │        scriptPubKey: P2TR(P_gateway_anchor)                         │  │
│    │        Purpose: CPFP fee bumping                                    │  │
│    │                                                                     │  │
│    │  Fee: 0 sats (paid by CPFP child)                                   │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│    CPFP CHILD TX (created at broadcast time):                               │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │  Inputs:                                                            │  │
│    │    [0] Anchor output from claim tx (330 sats)                       │  │
│    │    [1] Gateway fee UTXO (provides fee funds)                        │  │
│    │                                                                     │  │
│    │  Outputs:                                                           │  │
│    │    [0] Gateway change address                                       │  │
│    │                                                                     │  │
│    │  Fee: Calculated for current mempool conditions                     │  │
│    │       Pays for BOTH claim tx and this child tx                      │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  FEE CALCULATION EXAMPLE:                                                   │
│  ────────────────────────                                                   │
│    Claim tx size: ~150 vbytes                                               │
│    CPFP child size: ~120 vbytes                                             │
│    Total package: ~270 vbytes                                               │
│                                                                             │
│    At 20 sat/vB: 270 × 20 = 5,400 sats total fee                           │
│    Anchor provides: 330 sats                                                │
│    Gateway fee UTXO provides: 5,070+ sats                                   │
│                                                                             │
│  TIMEOUT REFUND TRANSACTION (CSV):                                          │
│  ─────────────────────────────────                                          │
│    Same structure, but paying to gateway refund address.                    │
│    Uses CSV (relative timelock) - spendable N blocks after Tx_1 confirms.   │
│                                                                             │
│    PRE-SIGNED TIMEOUT TX (zero fee):                                        │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │  Version: 2 (required for CSV)                                      │  │
│    │  Locktime: 0                                                        │  │
│    │                                                                     │  │
│    │  Inputs:                                                            │  │
│    │    [0] PTLC output (script path: timeout leaf)                      │  │
│    │        nSequence: 36 (CSV: 36 blocks relative delay)                │  │
│    │        witness: <gateway_sig> <csv_timeout_script> <control_block>  │  │
│    │        script: <36> OP_CSV OP_DROP <P_gateway> OP_CHECKSIG          │  │
│    │                                                                     │  │
│    │  Outputs:                                                           │  │
│    │    [0] Gateway refund: PTLC_value - 330 sats                        │  │
│    │    [1] Gateway anchor: 330 sats                                     │  │
│    │                                                                     │  │
│    │  Fee: 0 sats (paid by CPFP child)                                   │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│    NOTE: nSequence encodes the CSV delay. Transaction can only be mined     │
│    once the input UTXO (PTLC output) is at least 36 blocks deep.            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.7 Settlement Flow with Fee Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SETTLEMENT FLOW (GROUND-CONTROLLED)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1: Task completes, adaptor secret available                          │
│  ─────────────────────────────────────────────────                          │
│    Last operator → First operator: s_last (ground-to-ground)                │
│    First operator → Gateway: s_last (or first operator IS gateway)          │
│    Gateway computes: t = s_last for all PTLCs                               │
│                                                                             │
│  PHASE 2: Gateway determines broadcast strategy                             │
│  ──────────────────────────────────────────────                             │
│                                                                             │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │                     BROADCAST DECISION TREE                         │  │
│    ├─────────────────────────────────────────────────────────────────────┤  │
│    │                                                                     │  │
│    │  Satellite has ground contact within 2 hours?                       │  │
│    │    │                                                                │  │
│    │    ├─YES─► WAIT for cooperative settlement (optimal fees)           │  │
│    │    │       MuSig key path, fee set at signing time                  │  │
│    │    │                                                                │  │
│    │    └─NO──► Check current mempool fee rate                           │  │
│    │              │                                                      │  │
│    │              ├─LOW (<10 sat/vB)─► Broadcast now with CPFP           │  │
│    │              │                                                      │  │
│    │              ├─MEDIUM (10-50)───► Check timeout deadline            │  │
│    │              │                      │                               │  │
│    │              │                      ├─SOON (<6h)─► Broadcast now    │  │
│    │              │                      └─LATER─────► Wait for lower    │  │
│    │              │                                                      │  │
│    │              └─HIGH (>50 sat/vB)─► Wait unless timeout imminent     │  │
│    │                                                                     │  │
│    └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  PHASE 3A: Cooperative settlement (preferred)                               │
│  ─────────────────────────────────────────────                              │
│    During satellite ground contact:                                         │
│      1. Gateway queries current fee estimates                               │
│      2. Gateway proposes settlement tx (key path spend)                     │
│      3. MuSig2 signing session:                                             │
│         - Gateway and satellite exchange nonces                             │
│         - Both produce partial signatures                                   │
│         - Aggregate into final signature                                    │
│      4. Gateway broadcasts with optimal fee                                 │
│                                                                             │
│    Advantages:                                                              │
│      - Smallest on-chain footprint (key path, no script reveal)             │
│      - No anchor overhead (330 sats saved)                                  │
│      - Optimal fee (set at broadcast time)                                  │
│      - Most private                                                         │
│                                                                             │
│  PHASE 3B: Unilateral broadcast (fallback)                                  │
│  ─────────────────────────────────────────                                  │
│    Without satellite involvement:                                           │
│      1. Gateway completes adaptor signature: s = s' + t                     │
│      2. Gateway finalizes pre-signed claim transaction                      │
│      3. Gateway creates CPFP child with current fee rate                    │
│      4. Gateway broadcasts package (claim tx + CPFP child)                  │
│      5. Satellite receives funds (passive)                                  │
│                                                                             │
│  PHASE 4: Confirmation and fee bumping                                      │
│  ─────────────────────────────────────                                      │
│    Gateway monitors mempool:                                                │
│      - If tx confirming normally: done                                      │
│      - If tx stuck (fee too low): RBF the CPFP child with higher fee        │
│      - If major fee spike: create replacement CPFP child                    │
│                                                                             │
│    RBF CPFP CHILD:                                                          │
│      Same inputs as original CPFP child                                     │
│      Higher fee (must be > original + min relay fee increment)              │
│      Replaces original in mempool                                           │
│                                                                             │
│  BATCHING OPTIMIZATION:                                                     │
│  ──────────────────────                                                     │
│    When multiple claims pending, gateway can batch at CPFP level:           │
│                                                                             │
│    BATCHED CPFP CHILD:                                                      │
│      Inputs:                                                                │
│        [0] Anchor from claim_tx_1                                           │
│        [1] Anchor from claim_tx_2                                           │
│        [2] Anchor from claim_tx_3                                           │
│        [3] Gateway fee UTXO                                                 │
│      Outputs:                                                               │
│        [0] Gateway change                                                   │
│                                                                             │
│    Single CPFP child pays for multiple parent claim transactions.           │
│    Reduces per-claim overhead significantly.                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.8 Satellite Role in Fee Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SATELLITE RESPONSIBILITIES (MINIMAL)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites have MINIMAL role in fee management:                            │
│                                                                             │
│  AT TASK SETUP (verification only):                                         │
│  ──────────────────────────────────                                         │
│    □ Verify pre-signed claim tx pays to satellite's address                 │
│    □ Verify anchor output is present (330 sats)                             │
│    □ Verify satellite payment = PTLC_value - 330 sats                       │
│    □ Accept task if all checks pass                                         │
│                                                                             │
│  DURING TASK EXECUTION:                                                     │
│  ──────────────────────                                                     │
│    □ Execute assigned task                                                  │
│    □ Forward to next hop                                                    │
│    □ No fee-related actions                                                 │
│                                                                             │
│  DURING GROUND CONTACT (optional optimization):                             │
│  ──────────────────────────────────────────────                             │
│    □ Participate in MuSig2 signing for cooperative settlement               │
│    □ This enables key path spend (most efficient)                           │
│    □ If unavailable, gateway uses unilateral broadcast instead              │
│                                                                             │
│  RECEIVING FUNDS:                                                           │
│  ────────────────                                                           │
│    □ Completely passive                                                     │
│    □ Gateway broadcasts, funds arrive at satellite's address                │
│    □ Satellite monitors blockchain for confirmed payments                   │
│    □ No action required from satellite                                      │
│                                                                             │
│  UTXO CONSOLIDATION (during ground contact):                                │
│  ───────────────────────────────────────────                                │
│    □ Optional: Satellite can consolidate received UTXOs                     │
│    □ Sign consolidation tx during ground pass                               │
│    □ Gateway broadcasts with appropriate fee                                │
│    □ Reduces future on-chain costs                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Task Packet Structure

### 7.1 Onion Packet Format

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ONION TASK PACKET                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  OUTER ENVELOPE (unencrypted):                                              │
│  ─────────────────────────────                                              │
│    {                                                                        │
│      "version": 1,                                                          │
│      "packet_id": <32 bytes, random>,                                       │
│      "created_at": <unix timestamp>,                                        │
│      "first_hop": <satellite_id>,                                           │
│      "ephemeral_pubkey": <32 bytes, x-only BIP-340 format for ECDH>         │
│    }                                                                        │
│                                                                             │
│  FUNDING TRANSACTION (included once, shared by all hops):                   │
│  ─────────────────────────────────────────────────────────                  │
│    {                                                                        │
│      "tx1_raw": <full serialized Tx_1, v3 with ephemeral anchor>,           │
│      "tx1_txid": <txid for verification>,                                   │
│      "ephemeral_anchor_index": 4,  // output index of OP_TRUE anchor        │
│      "ptlc_outputs": [                                                      │
│        {"index": 0, "satellite": "B", "value": 1000},                       │
│        {"index": 1, "satellite": "C", "value": 5000},                       │
│        {"index": 2, "satellite": "D", "value": 2000}                        │
│      ]                                                                      │
│    }                                                                        │
│                                                                             │
│    NOTE: Full Tx_1 included so any operator can create CPFP child           │
│    to fee-bump if gateway is slow or offline.                               │
│                                                                             │
│  PER-HOP PAYLOAD (encrypted, one layer per hop):                            │
│  ───────────────────────────────────────────────                            │
│    {                                                                        │
│      "routing": {                                                           │
│        "next_hop": <satellite_id or "ground">,                              │
│        "next_hop_hint": <ISL address hint, optional>                        │
│      },                                                                     │
│      "task": {                                                              │
│        "type": "relay" | "image" | "process" | "downlink",                  │
│        "params": { <task-specific parameters> }                             │
│      },                                                                     │
│      "payment": {                                                           │
│        "amount_sats": 1000,                                                 │
│        "adaptor_point": <32 bytes, T, x-only>,  // SAME T for all hops      │
│        "ptlc_output_index": 0,  // which Tx_1 output is this hop's PTLC     │
│        "claim_address": <satellite's claim address>,                        │
│        "timeout_blocks": 36     // CSV: blocks after Tx_1 confirms          │
│        // NOTE: NO adaptor_signature - satellite creates it locally         │
│      },                                                                     │
│      "adaptor_verification": {                                              │
│        // Fields to verify T is correctly derived from last operator        │
│        "last_operator_pubkey": <32 bytes, P_last, x-only>,                  │
│        "last_operator_nonce": <32 bytes, R_last, pre-committed>,            │
│        "delivery_message": <expected message last operator will sign>       │
│      },                                                                     │
│      "inner_packet": <encrypted blob for next hop, or null if final>        │
│    }                                                                        │
│                                                                             │
│  SATELLITE CREATES ADAPTOR SIGNATURE:                                       │
│  ─────────────────────────────────────                                      │
│    Gateway provides adaptor_point T but NOT the adaptor signature.          │
│    Satellite creates its own adaptor signature using own key P_satellite:   │
│                                                                             │
│    On receiving task packet:                                                │
│      1. Construct claim_tx from Tx_1[ptlc_output_index] → claim_address     │
│      2. Create adaptor sig: adaptor_create(P_satellite, claim_tx, T)        │
│      3. Store adaptor_sig locally for later claim                           │
│                                                                             │
│    This UNIFIED convention matches payment channels (../future/CHANNELS.md)  │
│    and enables smooth upgrade from on-chain PTLCs to channel PTLCs.         │
│                                                                             │
│  ENCRYPTION:                                                                │
│  ───────────                                                                │
│    Each layer encrypted with ChaCha20-Poly1305                              │
│    Key derived: K_i = HKDF(ECDH(ephemeral_privkey, P_satellite_i))          │
│    Ephemeral key rotated per hop (standard onion construction)              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Acknowledgment Protocol

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TWO-WAY ACKNOWLEDGMENT PROTOCOL                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STEP 1: Task Delivery (A → B)                                              │
│  ─────────────────────────────                                              │
│    A sends to B:                                                            │
│      - Encrypted task packet (B's layer)                                    │
│      - All ancestor transactions (Tx_1, Tx_2, ... needed to verify PTLC)    │
│                                                                             │
│  STEP 2: Verification (B)                                                   │
│  ────────────────────────                                                   │
│    B verifies:                                                              │
│      □ Packet decrypts successfully                                         │
│      □ Task type is supported                                               │
│      □ Task parameters are valid                                            │
│      □ Tx_1 is valid and creates PTLC output for this satellite             │
│      □ PTLC amount matches expected payment                                 │
│      □ Adaptor point T is correctly constructed (CRITICAL - see below)      │
│      □ Timeout is acceptable (enough time to complete + settle)             │
│      □ Packet ID not seen before (replay protection)                        │
│      □ Nonce available for creating adaptor signature                       │
│                                                                             │
│    ADAPTOR POINT VERIFICATION (prevents malicious gateway attack):          │
│    ───────────────────────────────────────────────────────────────          │
│      In the ATOMIC model, all PTLCs use the same adaptor point T derived    │
│      from the last operator's acknowledgment commitment.                    │
│                                                                             │
│      Task packet must include:                                              │
│        - last_operator_pubkey: P_last (last operator's ground station key)  │
│        - last_operator_nonce: R_last (pre-committed nonce)                  │
│        - expected_delivery_msg: m = "delivered:" || task_id || H(output)    │
│                                                                             │
│      B computes expected adaptor point:                                     │
│        e = H_challenge(R_last || P_last || m)                               │
│        T_expected = R_last + e·P_last                                       │
│                                                                             │
│      B checks: T == T_expected                                              │
│                                                                             │
│      If mismatch: REJECT (gateway provided wrong adaptor point)             │
│                                                                             │
│      WHY THIS MATTERS:                                                      │
│        Without this check, gateway could provide T' ≠ T_expected.           │
│        Task completes, last operator signs valid s_last.                    │
│        But s_last doesn't unlock the adaptor signatures (wrong T).          │
│        Satellites did the work but cannot claim payment.                    │
│                                                                             │
│  STEP 3: Acknowledgment (B → A)                                             │
│  ──────────────────────────────                                             │
│    If all checks pass:                                                      │
│      m = "ack:" || task_id || H(full_payload)                               │
│      k = nonce_pool[nonce_index]  // retrieve pre-committed nonce           │
│      R = k·G                                                                │
│      e = H_challenge(R || P_B || m)                                         │
│      s = k + e·b mod n            // b = B's private key                    │
│                                                                             │
│      B sends to A: { "ack": true, "signature": (R, s) }                     │
│      B marks nonce as USED (critical: never reuse!)                         │
│                                                                             │
│    If any check fails:                                                      │
│      B sends to A: { "ack": false, "reason": "<error code>" }               │
│                                                                             │
│  STEP 4: Confirmation (A)                                                   │
│  ────────────────────────                                                   │
│    A receives ack signature (R, s)                                          │
│    A verifies: signature valid for B's public key on expected message       │
│    A stores: s as adaptor secret t_A (enables A to claim PTLC_A)            │
│                                                                             │
│  TIMING:                                                                    │
│  ───────                                                                    │
│    Delivery: ~10-100ms (depends on packet size and ISL bandwidth)           │
│    Verification: ~10ms                                                      │
│    Ack transmission: ~5ms (64 bytes)                                        │
│    Total per hop: <200ms typical                                            │
│                                                                             │
│  RETRY SEMANTICS (ISL drops after ack signed but before received):          │
│  ─────────────────────────────────────────────────────────────────          │
│                                                                             │
│    Scenario: B signs ack, sends to A, ISL drops, A never receives ack.      │
│                                                                             │
│    Problem: B has already used nonce k. If A retries with same nonce_index, │
│    B cannot re-sign (nonce reuse = catastrophic key compromise).            │
│                                                                             │
│    Solution: B MUST cache the ack signature after signing:                  │
│                                                                             │
│    On receiving task packet:                                                │
│      1. Check if (task_id, nonce_index) already in ack_cache                │
│         If yes: Return cached signature (idempotent retry)                  │
│         If no: Continue to step 2                                           │
│      2. Verify packet (all checks from STEP 2)                              │
│      3. Mark nonce as USED                                                  │
│      4. Sign acknowledgment                                                 │
│      5. Store in ack_cache: (task_id, nonce_index) → signature              │
│      6. Send signature to A                                                 │
│                                                                             │
│    Ack cache eviction: After timeout expiry + grace period.                 │
│    This matches packet ID cache eviction timing.                            │
│                                                                             │
│    IMPORTANT: A can retry with SAME nonce_index (gets cached ack).          │
│    A cannot retry with DIFFERENT nonce_index (would need new task packet    │
│    from gateway with different adaptor point).                              │
│                                                                             │
│    If B loses ack_cache (crash, reboot):                                    │
│      - B cannot re-sign (nonce marked used in persistent storage)           │
│      - A's retry fails                                                      │
│      - Task times out, gateway refunds                                      │
│      - This is a fail-safe: better to timeout than risk nonce reuse         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Complete Task Execution Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FULL PROTOCOL SEQUENCE (ATOMIC MODEL)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│            First                                          Last              │
│  Customer  Operator  Gateway    Sat_B    Sat_C    Sat_D   Operator          │
│      │        │         │         │        │        │        │              │
│      │        │         │         │        │        │        │              │
│  ════════════════════════════════════════════════════════════════════════   │
│                         PHASE 1: SETUP (Ground)                             │
│  ════════════════════════════════════════════════════════════════════════   │
│      │        │         │         │        │        │        │              │
│      │  1. Request task │         │        │        │        │              │
│      │────────┼────────►│         │        │        │        │              │
│      │        │         │         │        │        │        │              │
│      │        │         │ 2. Coordinate with operators       │              │
│      │        │◄────────│────────────────────────────────────►│ (get R_last)│
│      │        │         │         │        │        │        │              │
│      │        │         │ 3. Compute T = R_last + e·P_last   │              │
│      │        │         │    Create PTLC chain (all use T)   │              │
│      │        │         │         │        │        │        │              │
│      │  4. Invoice (H = SHA256(t), t = future s_last)        │              │
│      │◄───────┼─────────│         │        │        │        │              │
│      │        │         │         │        │        │        │              │
│      │  5. Pay HTLC     │         │        │        │        │              │
│      │────────┼────────►│         │        │        │        │              │
│      │        │         │         │        │        │        │              │
│      │        │ 6. Upload task    │        │        │        │              │
│      │        │ (ground contact)  │        │        │        │              │
│      │        │────────►│────────►│        │        │        │              │
│      │        │         │         │        │        │        │              │
│  ════════════════════════════════════════════════════════════════════════   │
│                    PHASE 2: EXECUTION (Satellite Network)                   │
│  ════════════════════════════════════════════════════════════════════════   │
│      │        │         │         │        │        │        │              │
│      │        │         │         │──task─►│        │        │              │
│      │        │         │         │        │──task─►│        │              │
│      │        │         │         │        │        │───────►│ 7. Delivery  │
│      │        │         │         │        │        │        │    (downlink)│
│      │        │         │         │        │        │        │              │
│  ════════════════════════════════════════════════════════════════════════   │
│                   PHASE 3: ACKNOWLEDGMENT (Ground-to-Ground)                │
│  ════════════════════════════════════════════════════════════════════════   │
│      │        │         │         │        │        │        │              │
│      │        │         │         │        │        │        │ 8. Verify    │
│      │        │         │         │        │        │        │    output    │
│      │        │         │         │        │        │        │              │
│      │        │ 9. s_last (ground network, e.g. internet)    │              │
│      │        │◄─────────────────────────────────────────────│ Sign ack     │
│      │        │         │         │        │        │        │              │
│      │        │ 10. Verify s_last, publish t = s_last        │              │
│      │        │────────►│         │        │        │        │              │
│      │        │         │         │        │        │        │              │
│  ════════════════════════════════════════════════════════════════════════   │
│                         PHASE 4: SETTLEMENT                                 │
│  ════════════════════════════════════════════════════════════════════════   │
│      │        │         │         │        │        │        │              │
│      │        │         │ 11. Claim customer HTLC using t    │              │
│      │◄───────┼─────────│ (payment complete)                 │              │
│      │        │         │         │        │        │        │              │
│      │        │         │ 12. Publish t (or revealed on-chain)              │
│      │        │         │         │        │        │        │              │
│      │        │         │         │──claim PTLC_B (using t)  │              │
│      │        │         │         │        │──claim PTLC_C   │              │
│      │        │         │         │        │        │──claim PTLC_D         │
│      │        │         │         │        │        │        │              │
│      │        │         │ 13. Release data to customer       │              │
│      │◄───────┼─────────┼─────────┼────────┼────────┼────────│              │
│      │        │         │         │        │        │        │              │
│  ════════════════════════════════════════════════════════════════════════   │
│                                                                             │
│  KEY POINTS:                                                                │
│    - ALL PTLCs use same adaptor secret t = s_last                           │
│    - s_last travels ground-to-ground (not via satellite)                    │
│    - Either everyone claims (delivery succeeded) or nobody (timeout)        │
│    - No partial completion possible                                         │
│    - Customer receives data AFTER payment settles                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Failure Handling

### 8.1 Failure Scenarios (Atomic Model)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FAILURE SCENARIOS (ATOMIC MODEL)                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  KEY PRINCIPLE: No partial completion                                       │
│  ────────────────────────────────────                                       │
│    All PTLCs share the same adaptor secret t = s_last.                      │
│    Either t exists (delivery succeeded) → all satellites claim              │
│    Or t doesn't exist (delivery failed) → all PTLCs timeout                 │
│                                                                             │
│                                                                             │
│  SCENARIO 1: Intermediate hop fails to forward                              │
│  ─────────────────────────────────────────────                              │
│                                                                             │
│    B ──✓──► C ──✗──► D ──?──► Last Operator                                │
│                                                                             │
│    What happened:                                                           │
│      - B forwarded to C successfully                                        │
│      - C failed to forward to D (ISL lost, C malfunction, etc.)             │
│      - Task never reaches last operator                                     │
│                                                                             │
│    Result (ATOMIC):                                                         │
│      - No s_last exists (last operator never received delivery)             │
│      - B cannot claim PTLC_B (no t)                                         │
│      - C cannot claim PTLC_C (no t)                                         │
│      - D cannot claim PTLC_D (no t)                                         │
│      - All PTLCs timeout → refund to gateway                                │
│      - Customer's HTLC times out → refund to customer                       │
│                                                                             │
│    Settlement:                                                              │
│      - Nobody gets paid                                                     │
│      - Customer refunded                                                    │
│      - Gateway whole (funded PTLCs, got them back via timeout)              │
│      - Satellites bear risk of wasted work                                  │
│                                                                             │
│                                                                             │
│  SCENARIO 2: Last operator receives but refuses to ack                      │
│  ─────────────────────────────────────────────────────                      │
│                                                                             │
│    B ──✓──► C ──✓──► D ──✓──► Last Operator (refuses s_last)               │
│                                                                             │
│    What happened:                                                           │
│      - Task completed successfully                                          │
│      - Last operator received valid output                                  │
│      - Last operator refuses to sign s_last                                 │
│                                                                             │
│    Result:                                                                  │
│      - No t = s_last released                                               │
│      - Nobody claims PTLCs (including last operator's satellite D!)         │
│      - All timeout refund                                                   │
│                                                                             │
│    Why this attack fails:                                                   │
│      - Last operator's satellite D is in the chain                          │
│      - If last operator withholds s_last, D doesn't get paid                │
│      - Last operator has no economic incentive to withhold                  │
│                                                                             │
│                                                                             │
│  SCENARIO 3: First operator receives s_last but refuses to publish          │
│  ────────────────────────────────────────────────────────────────           │
│                                                                             │
│    Last operator sends s_last → First operator (withholds)                  │
│                                                                             │
│    What happened:                                                           │
│      - Delivery succeeded                                                   │
│      - Last operator signed and sent s_last                                 │
│      - First operator refuses to publish t                                  │
│                                                                             │
│    Result:                                                                  │
│      - Satellites cannot claim PTLCs (don't have t)                         │
│      - First operator's satellite B also cannot claim!                      │
│      - All timeout refund                                                   │
│                                                                             │
│    Why this attack fails:                                                   │
│      - First operator's satellite B is in the chain                         │
│      - If first operator withholds t, B doesn't get paid                    │
│      - First operator has no economic incentive to withhold                 │
│                                                                             │
│    Note: Last operator can claim directly if they broadcast on-chain,       │
│    revealing t. Then all satellites can extract t and claim.                │
│                                                                             │
│                                                                             │
│  SCENARIO 4: Ground-to-ground link failure                                  │
│  ─────────────────────────────────────────                                  │
│                                                                             │
│    Last operator has s_last but cannot reach first operator                 │
│                                                                             │
│    Options:                                                                 │
│      a) Retry via alternative ground network path                           │
│      b) Last operator broadcasts claim tx directly (reveals t on-chain)     │
│      c) Wait and retry before timeout                                       │
│                                                                             │
│    Fallback (b) always works: on-chain claim reveals t to everyone          │
│                                                                             │
│                                                                             │
│  SCENARIO 5: Satellite goes permanently offline after task                  │
│  ──────────────────────────────────────────────────────────                 │
│                                                                             │
│    Task succeeded, t published, but satellite C never claims                │
│                                                                             │
│    C's unclaimed PTLC:                                                      │
│      - C has t (published/on-chain) but satellite offline                   │
│      - PTLC sits until either:                                              │
│        a) C comes back online and claims, OR                                │
│        b) Timeout expires, gateway reclaims                                 │
│                                                                             │
│    C's operator can claim via satellite recovery path (6 months)            │
│    if satellite has funds but is permanently dead.                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Recovery Mechanisms

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RECOVERY MECHANISMS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SATELLITE RECOVERY UTXO:                                                   │
│  ────────────────────────                                                   │
│    When satellite claims PTLC, output goes to recovery-enabled address:     │
│                                                                             │
│    Taproot structure:                                                       │
│      Internal key: P_satellite (satellite can spend immediately)            │
│      Script leaf: <6_months> OP_CLTV OP_DROP <P_operator> OP_CHECKSIG       │
│                                                                             │
│    Normal operation:                                                        │
│      - Satellite spends via key path                                        │
│      - Funds remain under satellite control                                 │
│                                                                             │
│    Satellite failure:                                                       │
│      - After 6 months, operator can spend via script path                   │
│      - Recovers stranded funds                                              │
│                                                                             │
│  NONCE POOL EXHAUSTION:                                                     │
│  ──────────────────────                                                     │
│    If satellite runs out of pre-committed nonces:                           │
│      - Cannot participate in new tasks                                      │
│      - Must wait for ground contact to upload new nonces                    │
│      - Existing in-progress tasks unaffected (already have nonce assigned)  │
│                                                                             │
│    Prevention:                                                              │
│      - Large nonce pool (100+ per satellite)                                │
│      - Proactive refresh during routine ground contacts                     │
│      - Alert threshold (e.g., <20 nonces remaining)                         │
│                                                                             │
│  KEY COMPROMISE:                                                            │
│  ──────────────                                                             │
│    If satellite key is compromised:                                         │
│      - Attacker can claim any PTLCs to that satellite                       │
│      - Attacker can forge acknowledgment signatures                         │
│                                                                             │
│    Mitigation:                                                              │
│      - Limit UTXO value per satellite                                       │
│      - HSM/secure enclave for key storage                                   │
│      - Key rotation capability (see Section 11)                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Ground Station Gateway

### 9.1 Gateway Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GATEWAY ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                           GATEWAY NODE                                │ │
│  │                                                                       │ │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐   │ │
│  │  │   Lightning     │    │    Payment      │    │   Satellite     │   │ │
│  │  │     Node        │◄──►│     Bridge      │◄──►│    Uplink       │   │ │
│  │  │                 │    │                 │    │                 │   │ │
│  │  │  - Channels     │    │  - HTLC↔PTLC    │    │  - Task upload  │   │ │
│  │  │  - Invoices     │    │  - Tx construct │    │  - Ack receive  │   │ │
│  │  │  - Routing      │    │  - Secret mgmt  │    │  - Status track │   │ │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘   │ │
│  │           │                      │                      │             │ │
│  │           ▼                      ▼                      ▼             │ │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐   │ │
│  │  │   Channel       │    │     UTXO        │    │     Nonce       │   │ │
│  │  │   Manager       │    │     Pool        │    │     Pool        │   │ │
│  │  │                 │    │                 │    │                 │   │ │
│  │  │  - Liquidity    │    │  - Allocation   │    │  - Per-satellite│   │ │
│  │  │  - Rebalancing  │    │  - Tracking     │    │  - Refresh mgmt │   │ │
│  │  │  - Peer mgmt    │    │  - Recycling    │    │  - Usage track  │   │ │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘   │ │
│  │                                                                       │ │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐   │ │
│  │  │     Task        │    │    Secret       │    │   Reputation    │   │ │
│  │  │    Router       │    │   Publisher     │    │    System       │   │ │
│  │  │                 │    │                 │    │                 │   │ │
│  │  │  - Ephemeris    │    │  - Ack collect  │    │  - Sat scoring  │   │ │
│  │  │  - Path finding │    │  - Publication  │    │  - Blacklisting │   │ │
│  │  │  - Load balance │    │  - Verification │    │  - Deposits     │   │ │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘   │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.2 UTXO Pool Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         UTXO POOL MANAGEMENT                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  POOL STRUCTURE:                                                            │
│  ───────────────                                                            │
│    UTXOs organized by denomination for efficient allocation:                │
│                                                                             │
│    ┌────────────────────────────────────────────────────────────────────┐  │
│    │  Pool Contents:                                                    │  │
│    │    Small  (10,000 sats):   20 UTXOs  [for small tasks]            │  │
│    │    Medium (50,000 sats):   10 UTXOs  [for typical tasks]          │  │
│    │    Large  (200,000 sats):   5 UTXOs  [for complex chains]         │  │
│    │                                                                    │  │
│    │  Status tracking per UTXO:                                        │  │
│    │    - Available: ready for new task                                │  │
│    │    - Committed: assigned to in-progress task                      │  │
│    │    - Spent: claimed by satellites                                 │  │
│    │    - Pending: awaiting confirmation                               │  │
│    └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ALLOCATION ALGORITHM:                                                      │
│  ─────────────────────                                                      │
│    On new task request:                                                     │
│                                                                             │
│    1. Calculate total: Σ(hop_payments) + Σ(fees) + buffer                   │
│    2. Find smallest available UTXO >= total                                 │
│    3. If found:                                                             │
│         Mark as COMMITTED                                                   │
│         Record: task_id, timeout, expected_payments                         │
│    4. If not found:                                                         │
│         Reject task (insufficient funds)                                    │
│         OR combine multiple UTXOs (higher fee)                              │
│                                                                             │
│  CONCURRENT TASK LIMITS:                                                    │
│  ───────────────────────                                                    │
│    Max concurrent tasks = available_utxos × utilization_factor              │
│                                                                             │
│    Example:                                                                 │
│      35 UTXOs total, 80% utilization target                                 │
│      Max concurrent = 35 × 0.8 = 28 tasks                                   │
│                                                                             │
│    Buffer UTXOs reserved for:                                               │
│      - High-priority tasks                                                  │
│      - Retry/reroute of failed tasks                                        │
│      - Unexpected demand spikes                                             │
│                                                                             │
│  RECYCLING:                                                                 │
│  ──────────                                                                 │
│    On task completion:                                                      │
│      - Change output returns to pool (new UTXO)                             │
│      - Update pool statistics                                               │
│                                                                             │
│    On task timeout:                                                         │
│      - Full UTXO refunded to gateway after timeout                          │
│      - Returns to pool once confirmed                                       │
│                                                                             │
│  REPLENISHMENT:                                                             │
│  ─────────────                                                              │
│    Sources:                                                                 │
│      - Lightning channel closes → on-chain funds                            │
│      - On-chain deposits                                                    │
│      - Task completion change outputs                                       │
│                                                                             │
│    Trigger replenishment when:                                              │
│      - Available UTXOs < threshold (e.g., 20%)                              │
│      - Specific denomination depleted                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.3 Secret Collection and Publication

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SECRET COLLECTION AND PUBLICATION                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SECRET COLLECTION:                                                         │
│  ──────────────────                                                         │
│    Gateway collects ack signatures from satellites during ground contacts:  │
│                                                                             │
│    1. Satellite reports:                                                    │
│         {                                                                   │
│           "task_id": <16 bytes>,                                            │
│           "hop_index": 2,                                                   │
│           "ack_received": {                                                 │
│             "from_satellite": <satellite_id>,                               │
│             "signature": (R, s),                                            │
│             "message": <ack message that was signed>                        │
│           }                                                                 │
│         }                                                                   │
│                                                                             │
│    2. Gateway verifies:                                                     │
│         □ Signature valid for reported satellite's public key               │
│         □ Message matches expected ack format                               │
│         □ Task ID corresponds to known in-progress task                     │
│                                                                             │
│    3. Gateway stores:                                                       │
│         ack_secrets[task_id][hop_index] = signature.s  (adaptor secret)     │
│                                                                             │
│  PUBLICATION METHODS:                                                       │
│  ────────────────────                                                       │
│                                                                             │
│    METHOD A: Direct notification (preferred)                                │
│      - Gateway notifies each satellite of their ack secrets                 │
│      - Via ground contact or relay                                          │
│      - Satellite can claim PTLC immediately                                 │
│                                                                             │
│    METHOD B: Bulletin board                                                 │
│      - Gateway publishes secrets to known endpoint                          │
│      - Satellites query periodically                                        │
│      - More robust to connectivity issues                                   │
│                                                                             │
│    METHOD C: On-chain (fallback)                                            │
│      - If satellite claims PTLC, adaptor secret visible on-chain            │
│      - Other parties can extract secret from completed signature            │
│      - No explicit publication needed                                       │
│                                                                             │
│  PUBLICATION FORMAT:                                                        │
│  ───────────────────                                                        │
│    {                                                                        │
│      "task_id": <16 bytes>,                                                 │
│      "secrets": [                                                           │
│        { "hop": 0, "adaptor_secret": <32 bytes> },                          │
│        { "hop": 1, "adaptor_secret": <32 bytes> },                          │
│        ...                                                                  │
│      ],                                                                     │
│      "gateway_signature": <64 bytes>  // proves authenticity                │
│    }                                                                        │
│                                                                             │
│  TIMING:                                                                    │
│  ───────                                                                    │
│    Secrets published as soon as collected                                   │
│    No benefit to withholding (satellites can claim on-chain anyway)         │
│    Earlier publication → faster settlement → better capital efficiency      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.4 Nonce Pool Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NONCE POOL MANAGEMENT                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STRUCTURE:                                                                 │
│  ──────────                                                                 │
│    Gateway maintains nonce pools per satellite:                             │
│                                                                             │
│    nonce_pools = {                                                          │
│      satellite_A: {                                                         │
│        nonces: [(index: 0, R: <point>, status: used),                       │
│                 (index: 1, R: <point>, status: used),                       │
│                 (index: 2, R: <point>, status: available),                  │
│                 ...],                                                       │
│        next_available: 2,                                                   │
│        total: 100,                                                          │
│        used: 2,                                                             │
│        last_refresh: <timestamp>                                            │
│      },                                                                     │
│      satellite_B: { ... },                                                  │
│      ...                                                                    │
│    }                                                                        │
│                                                                             │
│  REFRESH PROTOCOL:                                                          │
│  ─────────────────                                                          │
│    During ground contact:                                                   │
│                                                                             │
│    1. Satellite generates new nonces:                                       │
│         for i in range(batch_size):                                         │
│           k_i = random_scalar()                                             │
│           R_i = k_i * G                                                     │
│           store_locally(index=next_index+i, k=k_i)                          │
│                                                                             │
│    2. Satellite uploads to gateway:                                         │
│         {                                                                   │
│           "satellite_id": <id>,                                             │
│           "nonces": [                                                       │
│             { "index": 100, "R": <point> },                                 │
│             { "index": 101, "R": <point> },                                 │
│             ...                                                             │
│           ],                                                                │
│           "signature": <proves satellite generated these>                   │
│         }                                                                   │
│                                                                             │
│    3. Gateway stores nonces, marks as available                             │
│                                                                             │
│  ALLOCATION:                                                                │
│  ───────────                                                                │
│    When creating task that requires satellite S to acknowledge:             │
│                                                                             │
│    1. Get next available nonce for S:                                       │
│         nonce = nonce_pools[S].get_next_available()                         │
│         if nonce is None:                                                   │
│           return Error("Satellite S has no available nonces")               │
│                                                                             │
│    2. Mark nonce as committed:                                              │
│         nonce.status = "committed"                                          │
│         nonce.task_id = task_id                                             │
│                                                                             │
│    3. Include nonce index in task packet:                                   │
│         packet.payment.nonce_index = nonce.index                            │
│                                                                             │
│  SYNCHRONIZATION:                                                           │
│  ────────────────                                                           │
│    Gateway and satellite must agree on nonce usage:                         │
│                                                                             │
│    - Gateway tracks: which nonces assigned to which tasks                   │
│    - Satellite tracks: which nonces used for acknowledgments                │
│                                                                             │
│    Consistency check during ground contact:                                 │
│      - Satellite reports used nonce indices                                 │
│      - Gateway verifies matches expected usage                              │
│      - Discrepancies flagged for investigation                              │
│                                                                             │
│  FAILURE HANDLING:                                                          │
│  ─────────────────                                                          │
│    If task times out before ack:                                            │
│      - Gateway marks nonce as "expired" (not reusable)                      │
│      - Satellite may or may not have used it (unknown)                      │
│      - Conservative: treat as used to prevent reuse                         │
│                                                                             │
│    If satellite loses nonce state:                                          │
│      - Satellite must regenerate ALL nonces                                 │
│      - Upload new pool to gateway                                           │
│      - Old pool entirely invalidated                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 9.5 Trust Model (Atomic Design)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TRUST MODEL (FIRST/LAST OPERATOR)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  The atomic design distributes trust across multiple parties, each with     │
│  skin in the game. No single party can steal without also losing.           │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                           GATEWAY TRUST                                     │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  WHAT GATEWAY CAN DO:                                                       │
│  ────────────────────                                                       │
│    ✗ Steal customer funds                                                   │
│        (can't claim HTLC without t = s_last from last operator)             │
│                                                                             │
│    ✗ Steal satellite funds                                                  │
│        (satellites hold exclusive keys)                                     │
│                                                                             │
│    ✗ Forge task completion                                                  │
│        (requires last operator's signature s_last)                          │
│                                                                             │
│    ✓ Delay task initiation                                                  │
│        (customer can timeout and try different gateway)                     │
│                                                                             │
│    ✓ Censor specific customers                                              │
│        (mitigated by multiple competing gateways)                           │
│                                                                             │
│    ✓ Create invalid adaptor point T                                         │
│        (satellites verify T = R_last + e·P_last before executing)           │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                        FIRST OPERATOR TRUST                                 │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  First operator receives s_last and publishes t. What can they do?          │
│                                                                             │
│    ✗ Steal by withholding t                                                 │
│        First operator's satellite B is in the chain.                        │
│        If t not published, B doesn't get paid.                              │
│        NO ECONOMIC INCENTIVE TO WITHHOLD.                                   │
│                                                                             │
│    ✗ Steal customer funds                                                   │
│        Customer's HTLC is with gateway, not first operator.                 │
│        First operator can't claim customer HTLC.                            │
│                                                                             │
│    ✓ Delay publishing t                                                     │
│        Slows settlement but doesn't steal (all satellites affected equally) │
│        Last operator can bypass by claiming on-chain directly               │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                         LAST OPERATOR TRUST                                 │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  Last operator receives delivery and generates s_last. What can they do?    │
│                                                                             │
│    ✗ Steal by withholding s_last                                            │
│        Last operator's satellite D is in the chain.                         │
│        If s_last not released, D doesn't get paid.                          │
│        NO ECONOMIC INCENTIVE TO WITHHOLD.                                   │
│                                                                             │
│    ✗ Receive data and not pay                                               │
│        Customer receives data FROM last operator AFTER payment settles.     │
│        Last operator can't get paid without releasing s_last.               │
│        Payment and data release are sequenced correctly.                    │
│                                                                             │
│    ✓ Refuse to ack invalid delivery                                         │
│        This is correct behavior - invalid output should not be paid.        │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                         COLLUSION ANALYSIS                                  │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  CUSTOMER + LAST OPERATOR COLLUDE:                                          │
│    Attack: Customer asks last operator to withhold s_last after delivery    │
│    Result: Nobody gets paid (including last operator's satellite D)         │
│    Last operator loses D's payment to help customer save payment            │
│    NOT RATIONAL unless customer bribes > D's payment                        │
│                                                                             │
│  CUSTOMER + GATEWAY COLLUDE:                                                │
│    Attack: Gateway doesn't initiate task after customer pays                │
│    Result: Customer's HTLC times out, customer refunded                     │
│    No theft possible - customer gets money back                             │
│                                                                             │
│  FIRST + LAST OPERATOR COLLUDE:                                             │
│    Attack: Complete task but don't release s_last/t                         │
│    Result: Neither B nor D get paid, customer refunded                      │
│    They harmed themselves and gave customer free refund                     │
│    NOT RATIONAL                                                             │
│                                                                             │
│  ═══════════════════════════════════════════════════════════════════════    │
│                      STRUCTURAL REQUIREMENT                                 │
│  ═══════════════════════════════════════════════════════════════════════    │
│                                                                             │
│  CRITICAL: Customer must NOT operate the receiving ground station.          │
│                                                                             │
│  If customer = last operator:                                               │
│    - Customer receives data directly                                        │
│    - Customer can withhold s_last (they have no satellite in chain!)        │
│    - Customer gets free service                                             │
│    - THIS BREAKS THE TRUST MODEL                                            │
│                                                                             │
│  Solution: Last operator MUST be a satellite operator with satellite D      │
│  in the payment chain. Customer receives data from last operator after      │
│  payment settles.                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Security Analysis

### 10.1 Threat Model and Mitigations

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    THREAT ANALYSIS                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  THREAT: Customer pays, task not executed                                   │
│  ─────────────────────────────────────────                                  │
│    Attack: Gateway takes payment, doesn't initiate task                     │
│    Mitigation: HTLC timeout refunds customer automatically                  │
│    Customer loss: Time (timeout duration), no funds lost                    │
│                                                                             │
│  THREAT: Satellite claims payment without completing task                   │
│  ────────────────────────────────────────────────────────                   │
│    Attack: B claims PTLC_B without task actually completing                 │
│    Mitigation (ATOMIC MODEL):                                               │
│      - ALL PTLCs share same adaptor secret t = s_last                       │
│      - t only exists if last operator acknowledges delivery                 │
│      - Last operator only acks after receiving valid output                 │
│      - B cannot claim without end-to-end completion                         │
│    Result: Attack impossible - no partial claims                            │
│                                                                             │
│  THREAT: Operator double-spends funding UTXO                                │
│  ───────────────────────────────────────────                                │
│    Attack: Gateway spends UTXO to different address before satellite claims │
│    Mitigation: UTXO immediately spent into pre-signed tx chain              │
│                Tx_1 is valid and broadcast-ready                            │
│                Satellite can broadcast Tx_1 immediately                     │
│    Result: Race condition, satellite has equal opportunity                  │
│    Additional: Satellite holds exclusive keys, so gateway can't create      │
│                alternate spend anyway                                       │
│                                                                             │
│  THREAT: Replay of old task packets                                         │
│  ───────────────────────────────────                                        │
│    Attack: Attacker replays old packet to claim payment twice               │
│    Mitigation: Satellites track processed packet IDs                        │
│                Reject packets with seen IDs                                 │
│    Storage: Packet ID cache with TTL = max_timeout + buffer                 │
│    Cache size: packet_id (32 bytes) × max_packets ≈ 1MB for 30,000 packets │
│                                                                             │
│  THREAT: Nonce reuse (catastrophic for Schnorr)                             │
│  ──────────────────────────────────────────────                             │
│    Attack: If satellite reuses nonce k, attacker can recover private key    │
│    Mitigation: Persistent nonce tracking, never reuse                       │
│                Index-based nonces (k derived from index + seed)             │
│                Satellite marks nonce USED before signing                    │
│    Critical: This is the most important security invariant                  │
│                                                                             │
│  THREAT: Man-in-the-middle on ISL                                           │
│  ────────────────────────────────────                                       │
│    Attack: Attacker intercepts task, forwards modified version              │
│    Mitigation: Onion encryption to recipient's public key                   │
│                Ack message includes hash of received payload                │
│                Modification detected via hash mismatch                      │
│                                                                             │
│  THREAT: Satellite key compromise                                           │
│  ────────────────────────────────                                           │
│    Attack: Attacker obtains satellite's private key                         │
│    Impact: Can claim any PTLCs sent to that satellite                       │
│             Can forge acknowledgment signatures                             │
│    Mitigation: HSM/secure enclave for key storage                           │
│                Limited funds at risk per satellite                          │
│                Key rotation capability                                      │
│                Monitoring for unexpected claims                             │
│                                                                             │
│  THREAT: First/last operator withholds adaptor secret                       │
│  ────────────────────────────────────────────────────                       │
│    Attack: Last operator has s_last but doesn't release it                  │
│            OR first operator receives s_last but doesn't publish            │
│    Mitigation (ATOMIC MODEL):                                               │
│      - Last operator's satellite D is in the payment chain                  │
│      - First operator's satellite B is in the payment chain                 │
│      - Withholding means their own satellites don't get paid                │
│      - NO ECONOMIC INCENTIVE to withhold                                    │
│    Fallback: Last operator can claim on-chain directly, revealing t         │
│              Other satellites extract t from on-chain signature             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Replay Protection Details

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    REPLAY PROTECTION IMPLEMENTATION                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PACKET ID CACHE:                                                           │
│  ────────────────                                                           │
│    Structure: Hash table or bloom filter                                    │
│      Key: packet_id (32 bytes)                                              │
│      Value: (first_seen_timestamp, status)                                  │
│                                                                             │
│  CACHE OPERATIONS:                                                          │
│  ─────────────────                                                          │
│    On packet receive:                                                       │
│      1. Check if packet_id in cache                                         │
│      2. If found: REJECT (replay detected)                                  │
│      3. If not found:                                                       │
│           - Add to cache with current timestamp                             │
│           - Process packet                                                  │
│                                                                             │
│  EVICTION POLICY:                                                           │
│  ────────────────                                                           │
│    Entries evicted when:                                                    │
│      age > max_timeout + grace_period                                       │
│                                                                             │
│    Example:                                                                 │
│      max_timeout = 72 hours                                                 │
│      grace_period = 24 hours                                                │
│      eviction_age = 96 hours                                                │
│                                                                             │
│    Rationale: After timeout + grace, any replay attempt would fail          │
│               anyway due to expired timeouts in PTLC                        │
│                                                                             │
│  MEMORY BUDGET:                                                             │
│  ─────────────                                                              │
│    Per entry: 32 (packet_id) + 8 (timestamp) + 1 (status) = 41 bytes        │
│    Overhead: ~50% for hash table                                            │
│    Per entry with overhead: ~62 bytes                                       │
│                                                                             │
│    Budget: 1 MB cache                                                       │
│    Capacity: 1,000,000 / 62 ≈ 16,000 entries                               │
│                                                                             │
│    At 100 tasks/day: 16,000 / 100 = 160 days of history                    │
│    Well above 4-day eviction window → safe                                  │
│                                                                             │
│  BLOOM FILTER ALTERNATIVE:                                                  │
│  ─────────────────────────                                                  │
│    For higher throughput / lower memory:                                    │
│      - Bloom filter for fast rejection of known IDs                         │
│      - False positive rate: tunable (e.g., 0.1%)                            │
│      - False positives = reject legitimate packet (retry with new ID)       │
│      - No false negatives (replay always detected)                          │
│                                                                             │
│  TIMESTAMP VALIDATION:                                                      │
│  ─────────────────────                                                      │
│    Additional check: packet.created_at within acceptable window             │
│      - Reject if created_at > now + 1 minute (future)                       │
│      - Reject if created_at < now - max_timeout (too old)                   │
│    Prevents replays of packets created for previous timeout windows         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Key Management

### 11.1 Key Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SATELLITE KEY HIERARCHY                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ROOT KEY (generated at manufacture, stored in HSM):                        │
│  ───────────────────────────────────────────────────                        │
│    k_root = random 256 bits                                                 │
│    Never exported, used only for derivation                                 │
│                                                                             │
│  DERIVED KEYS:                                                              │
│  ─────────────                                                              │
│    Payment key:                                                             │
│      k_payment = HKDF(k_root, "payment" || satellite_id || version)         │
│      P_payment = k_payment * G                                              │
│      Used for: PTLC claims, ack signatures                                  │
│                                                                             │
│    Identity key:                                                            │
│      k_identity = HKDF(k_root, "identity" || satellite_id)                  │
│      P_identity = k_identity * G                                            │
│      Used for: ISL authentication, onion decryption                         │
│                                                                             │
│    Nonce derivation key:                                                    │
│      k_nonce = HKDF(k_root, "nonce" || satellite_id || epoch)               │
│      Used for: Deterministic nonce generation                               │
│                                                                             │
│  KEY DERIVATION:                                                            │
│  ───────────────                                                            │
│    Using HKDF-SHA256 (RFC 5869):                                            │
│      HKDF-Extract: PRK = HMAC-SHA256(salt=k_root, IKM=context)              │
│      HKDF-Expand: key = HMAC-SHA256(PRK, info || 0x01)                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 Key Rotation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KEY ROTATION PROTOCOL                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ROTATION TRIGGERS:                                                         │
│  ──────────────────                                                         │
│    - Scheduled: Every N months (e.g., 12 months)                            │
│    - Emergency: Suspected compromise                                        │
│    - Operational: Satellite ownership transfer                              │
│                                                                             │
│  ROTATION PROCEDURE:                                                        │
│  ───────────────────                                                        │
│                                                                             │
│    1. Generate new key version:                                             │
│         version_new = version_current + 1                                   │
│         k_payment_new = HKDF(k_root, "payment" || id || version_new)        │
│         P_payment_new = k_payment_new * G                                   │
│                                                                             │
│    2. Announce new key to gateway:                                          │
│         {                                                                   │
│           "satellite_id": <id>,                                             │
│           "key_rotation": {                                                 │
│             "old_version": 1,                                               │
│             "new_version": 2,                                               │
│             "new_pubkey": P_payment_new,                                    │
│             "effective_at": <timestamp>,                                    │
│             "signature": Sign(k_payment_old, message)                       │
│           }                                                                 │
│         }                                                                   │
│                                                                             │
│    3. Transition period:                                                    │
│         - Complete in-progress tasks with old key                           │
│         - New tasks use new key after effective_at                          │
│         - Duration: max_timeout of any pending task                         │
│                                                                             │
│    4. Old key retirement:                                                   │
│         - After transition, old key no longer used                          │
│         - Old key retained for signature verification only                  │
│                                                                             │
│  EMERGENCY ROTATION (suspected compromise):                                 │
│  ──────────────────────────────────────────                                 │
│    1. Immediately stop accepting new tasks                                  │
│    2. Complete in-progress tasks (attacker could claim anyway)              │
│    3. Generate new key, announce immediately                                │
│    4. Drain any remaining UTXOs to new key                                  │
│    5. Investigate and remediate compromise                                  │
│                                                                             │
│  KEY REVOCATION:                                                            │
│  ───────────────                                                            │
│    Revoked keys published to revocation list:                               │
│      - Gateway maintains list                                               │
│      - Satellites check before accepting tasks involving revoked keys       │
│      - Revocation signed by satellite's newer key (proves authority)        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. Integration with SCRAP

### 12.1 Capability Token Binding

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PAYMENT + AUTHORIZATION BINDING                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Each hop's onion layer includes both payment and authorization:            │
│                                                                             │
│  {                                                                          │
│    "payment": {                                                             │
│      "adaptor_point": T_i,                                                  │
│      "amount_sats": 1000,                                                   │
│      "timeout": <timestamp>,                                                │
│      ...                                                                    │
│    },                                                                       │
│    "authorization": {                                                       │
│      "capability_token": <CBOR-encoded SAT-CAP>,                            │
│      "delegation_chain": [root_token, del_1, ...],                          │
│      "commander_signature": Sign(cmd_key, task_hash)                        │
│    },                                                                       │
│    "task": { ... }                                                          │
│  }                                                                          │
│                                                                             │
│  VERIFICATION AT EACH HOP:                                                  │
│  ─────────────────────────                                                  │
│    Before acknowledging, satellite verifies:                                │
│                                                                             │
│    □ Capability token chain valid (per SCRAP spec)                           │
│    □ Token grants permission for requested task type                        │
│    □ Token not expired                                                      │
│    □ Payment amount meets token's payment_terms                             │
│    □ Adaptor signature valid                                                │
│                                                                             │
│  REJECT if authorization OR payment invalid.                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.2 Task-Payment Atomicity

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ATOMIC TASK-PAYMENT BINDING                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  The acknowledgment signature serves three purposes simultaneously:         │
│                                                                             │
│  1. PROOF OF RECEIPT                                                        │
│       C signs: "ack:" || task_id || H(payload)                              │
│       This proves C received the specific payload                           │
│                                                                             │
│  2. ADAPTOR SECRET                                                          │
│       The signature scalar s_C = adaptor secret t_B                         │
│       Enables B to claim their PTLC payment                                 │
│                                                                             │
│  3. NON-REPUDIABLE RECORD                                                   │
│       Signature can be verified by anyone with C's public key               │
│       Creates audit trail of task execution                                 │
│                                                                             │
│  STRONGER THAN SELF-ATTESTATION:                                            │
│  ───────────────────────────────                                            │
│    SCRAP's ProofOfExecution is self-attested (satellite signs own work)      │
│    Our ack signature is attested by NEXT hop                                │
│    "B completed delivery" proven by C's signature, not B's                  │
│                                                                             │
│  FINAL HOP BINDING:                                                         │
│  ──────────────────                                                         │
│    For final delivery to ground:                                            │
│      m = "delivered:" || task_id || H(output_data)                          │
│      Ground signs m, provides signature to satellite D                      │
│      This signature = D's adaptor secret                                    │
│                                                                             │
│    Customer receives:                                                       │
│      - Output data                                                          │
│      - Ground station's signature on H(output_data)                         │
│      - Proof that specific data was delivered                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Implementation

### 13.1 Recommended Libraries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    IMPLEMENTATION LIBRARIES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  GATEWAY (Ground Station):                                                  │
│  ─────────────────────────                                                  │
│    Lightning node: LDK (Lightning Dev Kit)                                  │
│      - Rust, production-ready                                               │
│      - Embeddable, modular architecture                                     │
│      - https://lightningdevkit.org/                                         │
│                                                                             │
│    Bitcoin: rust-bitcoin + rust-miniscript                                  │
│      - Transaction construction                                             │
│      - Taproot/Tapscript support                                            │
│                                                                             │
│    Adaptor signatures: secp256k1-zkp                                        │
│      - C library with Rust bindings                                         │
│      - Includes adaptor signature module                                    │
│      - https://github.com/BlockstreamResearch/secp256k1-zkp                 │
│                                                                             │
│    Alternative: LDK's built-in adaptor signature support (in development)   │
│                                                                             │
│  SATELLITE:                                                                 │
│  ──────────                                                                 │
│    Cryptography: libsecp256k1 (C) or k256 (Rust, no_std)                   │
│      - Schnorr signatures (BIP 340)                                         │
│      - ECDH for onion decryption                                            │
│                                                                             │
│    Symmetric crypto: ChaCha20-Poly1305                                      │
│      - Onion layer decryption                                               │
│      - chacha20poly1305 crate (Rust, no_std)                               │
│                                                                             │
│    Transaction parsing: rust-bitcoin (no_std compatible subset)             │
│      - Verify pre-signed transactions                                       │
│      - Construct claim transactions                                         │
│                                                                             │
│  RESOURCE REQUIREMENTS (Satellite):                                         │
│  ──────────────────────────────────                                         │
│    CPU: ARM Cortex-M4 or better (hardware crypto acceleration helpful)      │
│    RAM: 256 KB minimum (512 KB recommended)                                 │
│    Storage: 64 KB (keys, nonce tracking, packet ID cache)                   │
│    RNG: Hardware TRNG required (for nonce generation)                       │
│                                                                             │
│    Crypto operation timing (Cortex-M4 @ 168 MHz):                           │
│      - Schnorr sign: ~15ms                                                  │
│      - Schnorr verify: ~20ms                                                │
│      - ECDH: ~15ms                                                          │
│      - ChaCha20-Poly1305 (1KB): ~1ms                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Satellite Software Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SATELLITE SOFTWARE STACK                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      APPLICATION LAYER                                │ │
│  │                                                                       │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │ │
│  │  │    Task     │    │   Payment   │    │    ISL      │               │ │
│  │  │  Executor   │    │   Handler   │    │  Protocol   │               │ │
│  │  └─────────────┘    └─────────────┘    └─────────────┘               │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      PROTOCOL LAYER                                   │ │
│  │                                                                       │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │ │
│  │  │   Onion     │    │    Ack      │    │   PTLC      │               │ │
│  │  │  Processor  │    │  Generator  │    │  Verifier   │               │ │
│  │  └─────────────┘    └─────────────┘    └─────────────┘               │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      CRYPTO LAYER                                     │ │
│  │                                                                       │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │ │
│  │  │  Schnorr    │    │    ECDH     │    │   Nonce     │               │ │
│  │  │   Signer    │    │   Engine    │    │   Manager   │               │ │
│  │  └─────────────┘    └─────────────┘    └─────────────┘               │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                               │                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                      STORAGE LAYER                                    │ │
│  │                                                                       │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │ │
│  │  │    Key      │    │   Nonce     │    │  Packet ID  │               │ │
│  │  │   Store     │    │   Store     │    │   Cache     │               │ │
│  │  │   (HSM)     │    │  (persist)  │    │   (RAM)     │               │ │
│  │  └─────────────┘    └─────────────┘    └─────────────┘               │ │
│  │                                                                       │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 14. Unified Infrastructure (Shared with Payment Channels)

This section documents components shared between on-chain PTLCs (this document) and payment channels (../future/CHANNELS.md). Implementing these uniformly enables smooth upgrade from Phase 1 (on-chain) to Phase 2 (channels).

### 14.1 Unified Adaptor Signature Convention

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED ADAPTOR CONVENTION                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CONVENTION: Receiver creates adaptor signature using own key               │
│  ───────────────────────────────────────────────────────────                │
│                                                                             │
│    Script:  <P_receiver> OP_CHECKSIG                                        │
│    Adaptor: Receiver creates, locked to adaptor point T                     │
│    Claim:   Receiver completes signature when t learned                     │
│    Extract: Observer computes t = s - s' from completed signature           │
│                                                                             │
│  USED BY BOTH:                                                              │
│    □ On-chain PTLCs (this document): Satellite creates adaptor for claim    │
│    □ Payment channels (../future/CHANNELS.md): Receiver creates adaptor      │
│                                                                             │
│  ADAPTOR POINT SOURCE:                                                      │
│    On-chain: T = R_last + e·P_last (signature-as-secret from delivery ack)  │
│    Channels: T = T_base + tweak·G (privacy tweaks over base secret)         │
│                                                                             │
│    In both cases, t ultimately derives from an acknowledgment signature.    │
│    Channel PTLCs can use T_base directly (matching on-chain) or add tweaks. │
│                                                                             │
│  BENEFITS:                                                                  │
│    □ Same HSM operations for both                                           │
│    □ Same script structure                                                  │
│    □ Same claim flow                                                        │
│    □ Upgrade is adding capabilities, not changing existing ones             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.2 Unified Key Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED KEY DERIVATION                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ROOT KEY (HSM, never exported):                                            │
│    k_root = generated at manufacture                                        │
│                                                                             │
│  DERIVATION TREE:                                                           │
│                                                                             │
│    k_root                                                                   │
│      │                                                                      │
│      ├─► "identity" ──► k_identity                                          │
│      │     Used for: Satellite identity, operator communication             │
│      │                                                                      │
│      ├─► "task" || <32-byte task_id> ──► k_task                             │
│      │     Used for: On-chain PTLC claims (Phase 1)                         │
│      │     Satellite creates adaptor sig with this key                      │
│      │                                                                      │
│      ├─► "channel" || <32-byte channel_id> ──► k_channel                    │
│      │     │   Used for: Channel identity (Phase 2)                         │
│      │     │                                                                │
│      │     ├─► "update" ──► k_update                                        │
│      │     │     Used for: LN-Symmetry update signatures (APO)              │
│      │     │                                                                │
│      │     ├─► "settle" ──► k_settle                                        │
│      │     │     Used for: Settlement transaction signatures                │
│      │     │                                                                │
│      │     └─► "ptlc" || <8-byte ptlc_id> ──► k_ptlc                        │
│      │           Used for: Channel PTLC adaptor signatures                  │
│      │                                                                      │
│      └─► "nonce" || <nonce_id> ──► k_nonce                                  │
│            Used for: Unified nonce pool (see below)                         │
│                                                                             │
│  FIELD ENCODING:                                                            │
│    All IDs are fixed-width to prevent collision:                            │
│      task_id: 32 bytes (from task packet)                                   │
│      channel_id: 32 bytes (SHA256 of funding outpoint)                      │
│      ptlc_id: 8 bytes (uint64 big-endian)                                   │
│      nonce_id: 41 bytes (see nonce pool section)                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.3 Unified Nonce Pool

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED NONCE MANAGEMENT                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  NONCE ID FORMAT:                                                           │
│    nonce_id = <purpose:1> || <context:32> || <index:8>                      │
│                                                                             │
│    purpose byte:                                                            │
│      0x01 = Task acknowledgment (on-chain PTLC)                             │
│      0x02 = Task claim (on-chain PTLC adaptor sig)                          │
│      0x03 = Channel update (LN-Symmetry)                                    │
│      0x04 = Channel PTLC (channel adaptor sig)                              │
│                                                                             │
│    context:                                                                 │
│      For 0x01, 0x02: task_id (32 bytes)                                     │
│      For 0x03, 0x04: channel_id (32 bytes)                                  │
│                                                                             │
│    index:                                                                   │
│      Monotonic counter within context (uint64 big-endian)                   │
│                                                                             │
│  DERIVATION:                                                                │
│    k_nonce = HKDF(k_root, "nonce" || nonce_id)                              │
│    R_nonce = k_nonce · G                                                    │
│                                                                             │
│  CONSUMPTION TRACKING:                                                      │
│    □ Single persistent bitmap tracks ALL consumed nonces                    │
│    □ Mark consumed BEFORE signing (crash safety)                            │
│    □ Never reuse (nonce reuse = key recovery attack)                        │
│                                                                             │
│  PRE-COMMITMENT (for task acknowledgments):                                 │
│    Satellites pre-generate nonce pool, upload R values to gateway           │
│    Gateway uses R values to compute adaptor points                          │
│    Same infrastructure used for both task acks and channel nonces           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.4 Unified HSM Interface

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED HSM OPERATIONS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1 OPERATIONS (required now):                                         │
│  ──────────────────────────────────                                         │
│    derive_pubkey(path) → pubkey                                             │
│    schnorr_sign(key_path, message) → (R, s)                                 │
│    schnorr_verify(pubkey, message, sig) → bool                              │
│                                                                             │
│    // Adaptor signatures (UNIFIED for on-chain and channels)                │
│    adaptor_create(key_path, message, adaptor_point_T) → (R, s')             │
│    adaptor_verify(pubkey, message, T, adaptor_sig) → bool                   │
│    adaptor_complete(adaptor_sig, secret_t) → (R', s)                        │
│    adaptor_extract(adaptor_sig, completed_sig) → t                          │
│                                                                             │
│    // Nonce management                                                      │
│    nonce_generate(nonce_id) → (k, R)                                        │
│    nonce_get_public(nonce_id) → R                                           │
│    nonce_mark_consumed(nonce_id) → void                                     │
│    nonce_is_available(nonce_id) → bool                                      │
│                                                                             │
│  PHASE 2 ADDITIONS (when BIP 118 ready):                                    │
│  ─────────────────────────────────────────                                  │
│    // MuSig2 for channel funding/cooperative close                          │
│    musig2_nonce_gen(session_id) → (secnonce, pubnonce)                      │
│    musig2_partial_sign(key_path, session, message) → partial_sig            │
│    musig2_partial_verify(pubnonce, partial_sig, message) → bool             │
│    musig2_aggregate(partial_sigs) → final_sig                               │
│                                                                             │
│    // SIGHASH_ANYPREVOUT for LN-Symmetry                                    │
│    schnorr_sign_apo(key_path, message, sighash_flags) → sig                 │
│                                                                             │
│  CAPABILITY REPORTING:                                                      │
│    hsm_get_capabilities() → {                                               │
│      "schnorr": true,      // Always available                              │
│      "adaptor": true,      // Always available                              │
│      "musig2": bool,       // Phase 2 firmware                              │
│      "apo": bool           // Phase 2 firmware + BIP 118 active             │
│    }                                                                        │
│                                                                             │
│  UPGRADE PATH:                                                              │
│    Phase 1 satellites can receive firmware upgrade adding Phase 2 ops.      │
│    Existing operations unchanged - only additions.                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 14.5 Unified Protocol Messages

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    UNIFIED MESSAGE FORMAT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BASE HEADER (all messages):                                                │
│    struct MessageHeader {                                                   │
│      version: u16,         // Protocol version                              │
│      msg_type: u16,        // Message type (see below)                      │
│      msg_id: [u8; 16],     // Unique message ID                             │
│      timestamp: u64,       // Unix timestamp                                │
│      payload_len: u32,     // Length of payload                             │
│    }                                                                        │
│                                                                             │
│  MESSAGE TYPES:                                                             │
│    0x01xx: Task messages (Phase 1 on-chain)                                 │
│      0x0100: TASK_PACKET                                                    │
│      0x0101: TASK_ACK                                                       │
│      0x0102: TASK_FAIL                                                      │
│      0x0103: TASK_CLAIM_READY                                               │
│                                                                             │
│    0x02xx: Channel messages (Phase 2)                                       │
│      0x0200: CHANNEL_UPDATE                                                 │
│      0x0201: CHANNEL_UPDATE_ACK                                             │
│      0x0202: PTLC_OFFER                                                     │
│      0x0203: PTLC_ACCEPT                                                    │
│      0x0204: PTLC_FULFILL                                                   │
│      0x0205: PTLC_FAIL                                                      │
│                                                                             │
│    0x03xx: Task-via-channel messages (Phase 2 extension)                    │
│      0x0300: TASK_VIA_CHANNEL                                               │
│                                                                             │
│  UNIFIED PTLC STATE:                                                        │
│    struct PtlcState {                                                       │
│      ptlc_id: [u8; 8],                                                      │
│      ptlc_type: u8,           // 0x01=task, 0x02=channel                    │
│      amount_sat: u64,                                                       │
│      adaptor_point: [u8; 32], // T                                          │
│      adaptor_nonce: [u8; 32], // R from adaptor sig                         │
│      adaptor_scalar: [u8; 32], // s' from adaptor sig                       │
│      timeout_type: u8,        // 0x01=CSV, 0x02=CLTV                        │
│      timeout_value: u32,                                                    │
│      status: u8,              // pending, claimable, claimed, timeout       │
│      // Optional fields                                                     │
│      task_id: Option<[u8; 16]>,    // For task PTLCs                        │
│      channel_id: Option<[u8; 32]>, // For channel PTLCs                     │
│      tweak: Option<[u8; 32]>,      // Privacy tweak if used                 │
│    }                                                                        │
│                                                                             │
│  VERSION NEGOTIATION:                                                       │
│    version = 1: Task messages only (Phase 1 - on-chain PTLCs)               │
│    version = 2: Task + Channel messages (Phase 2 - payment channels)        │
│      Note: Task-via-channel (0x03xx) included in version 2                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 15. Payment Architecture

### 15.1 Two Orthogonal Concerns

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PAYMENT ARCHITECTURE                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Two independent dimensions determine payment behavior:                     │
│                                                                             │
│  DIMENSION 1: FUNDING MECHANISM                                             │
│  ─────────────────────────────────                                          │
│    On-Chain UTXOs:  Fresh transaction per payment (or batch)                │
│    Channels:        Pre-funded, off-chain state updates                     │
│                                                                             │
│  DIMENSION 2: PAYMENT INITIATOR                                             │
│  ─────────────────────────────────                                          │
│    Gateway-initiated (Task payments):                                       │
│      - Customer requests task via gateway                                   │
│      - Gateway coordinates payment to satellites                            │
│      - Delivery proof via signature-as-secret (t = s_last)                  │
│      - Atomic: all-or-nothing settlement                                    │
│                                                                             │
│    Satellite-initiated (Autonomous payments):                               │
│      - Satellite requests service from another satellite                    │
│      - No external coordination needed                                      │
│      - No delivery proof (just payment for service)                         │
│      - Per-hop settlement                                                   │
│                                                                             │
│  PAYMENT MATRIX:                                                            │
│  ───────────────                                                            │
│                                                                             │
│                      Gateway-Initiated         Satellite-Initiated          │
│                      (Task payments)           (Autonomous)                 │
│                      ──────────────────        ────────────────────         │
│                                                                             │
│  On-Chain            ✓ PRIMARY USE CASE        ⚠ Possible but awkward       │
│  UTXOs               T = R_last + e·P_last     T = z·G (receiver)           │
│                      Delivery proof            No delivery proof            │
│                      (this document)           Delayed settlement           │
│                                                                             │
│  Payment             ✓ Better economics        ✓ Natural fit                │
│  Channels            T = R_last + e·P_last     T = z·G (receiver)           │
│                      Delivery proof            No delivery proof            │
│                      Instant settlement        Instant settlement           │
│                      (../future/CHANNELS.md)    (../future/CHANNELS.md)       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 15.2 Autonomous On-Chain Payments

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS ON-CHAIN PAYMENTS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  While this document focuses on gateway-initiated task payments,            │
│  autonomous satellite-to-satellite payments ARE possible on-chain.          │
│                                                                             │
│  MECHANISM:                                                                 │
│  ──────────                                                                 │
│    1. Operator pre-funds Sat A with spendable UTXO during ground contact    │
│       Operator creates: tx paying to P_A (satellite A's key)                │
│                                                                             │
│    2. In space, A wants to pay B for a service:                             │
│       - B provides adaptor point T = z·G (B generates secret z)             │
│       - A creates payment tx: UTXO → P_B                                    │
│       - A creates adaptor signature locked to T                             │
│       - B provides service                                                  │
│       - B reveals z, A completes signature                                  │
│       - B stores signed tx                                                  │
│                                                                             │
│    3. During ground contact, B (or operator) broadcasts tx                  │
│       Payment settles on-chain                                              │
│                                                                             │
│  LIMITATIONS:                                                               │
│  ────────────                                                               │
│    □ Delayed settlement: Must wait for ground contact to broadcast          │
│    □ Single-use: One payment per pre-funded UTXO                            │
│    □ Trust: B cannot verify UTXO exists (offline from blockchain)           │
│    □ Capital inefficient: Must pre-fund many UTXOs for flexibility          │
│    □ On-chain fee per payment                                               │
│    □ Unidirectional: A can pay B, but B cannot pay A with same UTXO         │
│                                                                             │
│  ADAPTOR POINT (differs from task payments):                                │
│  ───────────────────────────────────────────                                │
│    Task payments:      T = R_last + e·P_last (signature-as-secret)          │
│    Autonomous:         T = z·G (receiver generates z)                       │
│                                                                             │
│    Receiver-generates-secret is used because:                               │
│      - No gateway coordination to set up signature-as-secret                │
│      - No "last operator" acknowledgment in autonomous flow                 │
│      - Receiver controls when to reveal z (after service provided)          │
│                                                                             │
│  RECOMMENDATION:                                                            │
│  ───────────────                                                            │
│    Autonomous on-chain payments are possible for Phase 1 deployments        │
│    where channels are not yet available. However, channels (Phase 2)        │
│    are strongly preferred for autonomous payments due to:                   │
│      - Instant settlement                                                   │
│      - Multi-use (reusable liquidity)                                       │
│      - Better capital efficiency                                            │
│      - Bidirectional payments                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 15.3 Phase Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TWO-PHASE DEPLOYMENT                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1: ON-CHAIN PTLCs (this document)                                    │
│  ─────────────────────────────────────────                                  │
│    Status: Implementable today                                              │
│    Dependencies: None (uses existing Bitcoin features)                      │
│                                                                             │
│    Use cases:                                                               │
│      ✓ First transaction with new operator (no channel yet)                 │
│      ✓ Very high value tasks (extra security)                               │
│      ✓ Operators without existing channel relationship                      │
│                                                                             │
│    Characteristics:                                                         │
│      □ On-chain transaction per task (Tx_1)                                 │
│      □ Task starts after mempool acceptance (~2 seconds)                    │
│      □ Settlement requires ground contact for PTLC claims                   │
│      □ Delivery proof via signature-as-secret                               │
│                                                                             │
│  PHASE 2: OPERATOR CHANNELS (../future/CHANNELS.md)                          │
│  ─────────────────────────────────────────────────                          │
│    Status: Standard Lightning (no soft fork needed for basic version)       │
│    Dependencies: Operators maintain Lightning nodes                         │
│                                                                             │
│    CRITICAL INSIGHT: Channels between OPERATORS, not satellites.            │
│    Operators are always online (ground-based).                              │
│    Standard Lightning multi-hop works.                                      │
│                                                                             │
│    Use cases:                                                               │
│      ✓ Routine tasks between federated operators                            │
│      ✓ High frequency operations                                            │
│      ✓ Cost-sensitive applications                                          │
│                                                                             │
│    Characteristics:                                                         │
│      □ Pre-funded operator-to-operator channels                             │
│      □ Task starts IMMEDIATELY (no mempool wait)                            │
│      □ Settlement in <1 second (operators online)                           │
│      □ Same adaptor signature binding for atomicity                         │
│      □ No on-chain transaction per task                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 15.3.1 Why Operator Channels, Not Satellite Channels

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OPERATOR VS SATELLITE CHANNELS                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SATELLITE-TO-SATELLITE CHANNELS DON'T WORK:                                │
│  ───────────────────────────────────────────                                │
│    - ISL connectivity is sparse and intermittent                            │
│    - Multi-hop Lightning requires real-time coordination                    │
│    - Store-and-forward payments take hours (9+ for 3-hop)                   │
│    - HTLC timeouts become impractically long (12+ hours)                    │
│                                                                             │
│  OPERATOR-TO-OPERATOR CHANNELS WORK:                                        │
│  ───────────────────────────────────                                        │
│    - Operators are ALWAYS ONLINE (ground-based)                             │
│    - Standard Lightning multi-hop (milliseconds)                            │
│    - No ISL timing constraints for payment                                  │
│    - Satellites just execute tasks, no payment logic                        │
│                                                                             │
│  SEPARATION OF CONCERNS:                                                    │
│  ───────────────────────                                                    │
│    TASK LAYER (satellites):                                                 │
│      - Execute tasks                                                        │
│      - Route data via ISL (store-and-forward)                               │
│      - Verify capability tokens                                             │
│      - NO payment logic                                                     │
│                                                                             │
│    PAYMENT LAYER (operators):                                               │
│      - Maintain Lightning channels                                          │
│      - Route payments via standard Lightning                                │
│      - Settle atomically using adaptor signatures                           │
│      - ALWAYS ONLINE                                                        │
│                                                                             │
│  FLOW:                                                                      │
│  ─────                                                                      │
│    Task route:    Sat_B (Op_X) → Sat_C (Op_Y) → Sat_D (Op_Z)               │
│    Payment route: Gateway → Op_X → Op_Y → Op_Z (ground-based)               │
│                                                                             │
│    Payment coordination: <1 second (operators online)                       │
│    Task execution: minutes to hours (ISL store-and-forward)                 │
│    Settlement: <1 second once proof available                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 15.4 What Changes Between Phases

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PHASE COMPARISON                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────┬───────────────────────┬───────────────────────┐   │
│  │ Component           │ Phase 1 (On-Chain)    │ Phase 2 (Op Channels) │   │
│  ├─────────────────────┼───────────────────────┼───────────────────────┤   │
│  │ PTLC funding        │ Tx_1 per task         │ Operator channel      │   │
│  │ Settlement          │ On-chain              │ Off-chain (instant)   │   │
│  │ Task start          │ After mempool (~2s)   │ Immediately           │   │
│  │ Payment parties     │ Gateway + Operators   │ Gateway + Operators   │   │
│  │ Satellite role      │ Execute only          │ Execute only          │   │
│  │ On-chain cost       │ ~$1+ per task         │ Amortized over tasks  │   │
│  │ BIP 118 required    │ No                    │ No (standard LN OK)   │   │
│  └─────────────────────┴───────────────────────┴───────────────────────┘   │
│                                                                             │
│  KEY INSIGHT: SATELLITES NEVER HANDLE PAYMENTS                              │
│  ─────────────────────────────────────────────────                          │
│    In BOTH phases:                                                          │
│      - Satellites execute tasks and route data                              │
│      - Operators handle all payment logic                                   │
│      - Payment coordination happens on the ground                           │
│                                                                             │
│  ADAPTOR SIGNATURE BINDING (same in both phases):                           │
│  ────────────────────────────────────────────────                           │
│    All payments locked to adaptor point T = R_last + e·P_last               │
│    Last operator's delivery acknowledgment reveals t = s_last               │
│    All payments settle atomically when t is revealed                        │
│                                                                             │
│  UNCHANGED BETWEEN PHASES:                                                  │
│    □ Task routing via satellites (ISL, store-and-forward)                   │
│    □ Capability token verification on satellites                            │
│    □ Proof-of-execution generation                                          │
│    □ Adaptor signature binding for atomicity                                │
│    □ Ground-to-ground delivery confirmation                                 │
│                                                                             │
│  CHANGES IN PHASE 2:                                                        │
│    □ Gateway routes payment through operator channels (not on-chain)        │
│    □ No Tx_1 creation (channel state update instead)                        │
│    □ Instant settlement (operators online, <1 second)                       │
│    □ Lower per-task cost (no on-chain fees)                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 16. Future Extensions

### 16.1 Additional Protocol Features

```
When SIGHASH_ANYPREVOUT activates (BIP 118):
  - Replace individual UTXOs with LN-Symmetry channels
  - Same adaptor signature mechanics
  - Better capital efficiency (channel reuse)
  - No penalty risk (latest state always wins)

Migration path:
  1. Current: Individual UTXOs (safe, works today)
  2. Future: LN-Symmetry channels (efficient, pending soft fork)
  3. Adaptor signature mechanics remain unchanged (unified convention)
```

### 16.2 Multi-Operator Routing

```
Multiple operators' constellations:
  - Each operator runs gateway(s)
  - Inter-operator task routing via ISL
  - Payments settled via Lightning between operators
  - Reputation/deposit system for inter-operator trust
```

### 14.3 Streaming Payments

```
For long-running tasks (continuous observation, extended relay):
  - Multiple micro-payments during execution
  - Each interval's payment released on interval acknowledgment
  - Reduces capital lockup
  - Better aligns incentives for sustained quality
```

### 14.4 Protocol Versioning

```
VERSIONING STRATEGY:
  The packet format includes "version": 1 in the outer envelope.

  Version negotiation:
    - Satellites advertise supported versions during ground contact
    - Gateway selects highest mutually-supported version
    - Packet version field indicates which protocol rules apply

  Backward compatibility:
    - New versions SHOULD maintain backward compatibility where possible
    - Breaking changes require version bump
    - Satellites MAY support multiple versions simultaneously
    - Gateway SHOULD support N-1 version for transition period

  Version changelog (maintain in implementation docs):
    v1: Initial protocol (this document)
    v2: (reserved for future)

  Deprecation policy:
    - Announce deprecation 6+ months before removal
    - Gateway logs warnings for deprecated version usage
    - Satellite firmware updates include version upgrades
```

---

## 15. References

### Standards
- BIP 340: Schnorr Signatures for secp256k1
- BIP 341: Taproot: SegWit version 1 spending rules
- BIP 118: SIGHASH_ANYPREVOUT (proposed)
- BOLT specifications (Lightning Network)
- RFC 5869: HKDF (HMAC-based Key Derivation Function)

### Implementations
- LDK (Lightning Dev Kit): https://lightningdevkit.org/
- secp256k1-zkp: https://github.com/BlockstreamResearch/secp256k1-zkp
- rust-bitcoin: https://github.com/rust-bitcoin/rust-bitcoin

### Academic
- "One-Time Verifiably Encrypted Signatures A.K.A. Adaptor Signatures" - Aumayr et al.
- "Payment Points Part 1-4" - Bitcoin Optech

---

## 16. Conclusion

This protocol enables trustless satellite payments through:

1. **PTLCs with adaptor signatures** - Payment claims cryptographically bound to acknowledgment signatures
2. **Pre-signed transaction chains** - No on-chain confirmation needed during task execution
3. **Two-way acknowledgment** - Each hop proves delivery to the next
4. **Nonce pre-commitment** - Enables correct adaptor point construction
5. **Lightning integration** - Customers pay via standard Lightning invoices
6. **Satellite-exclusive key custody** - Operators cannot steal satellite funds

The protocol requires bidirectional ISL communication for acknowledgments but tolerates extended periods without ground contact. Settlement is asynchronous, happening when convenient rather than blocking task execution.

Key security invariant: **Never reuse nonces.** All other security properties depend on this.

Capital efficiency is traded for safety (no penalty mechanism). Future LN-Symmetry integration will improve efficiency while maintaining safety.
