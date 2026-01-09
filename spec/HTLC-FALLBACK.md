# SCRAP HTLC Fallback Mode

## Status

This document describes a **degraded operating mode** for SCRAP (Secure
Capabilities and Routed Authorization Protocol) that can be deployed on
current Bitcoin before BIP-118 (ANYPREVOUT) activation.

**This mode is NOT recommended for production use.** It sacrifices key
protocol properties but enables early deployment for testing and validation:

1. Validate capability token verification and task routing
2. Test ground-agent coordination infrastructure
3. Prove channel state management works (with watchtower requirements)
4. Enable ecosystem development before BIP-118 activation

For the primary SCRAP specification using ln-symmetry channels and PTLCs,
see [SCRAP.md](SCRAP.md).

---

## 1. Limitations

The HTLC fallback mode loses the following properties compared to full SCRAP:

| Property | Full SCRAP (PTLC) | HTLC Fallback |
|----------|-------------------|---------------|
| Payment-proof atomicity | Adaptor secret = proof | Separate attestation required |
| Watchtower key custody | Not required | Required (revocation keys) |
| State backup | Latest state only | Full history required |
| Offline resilience | State sync via any path | Must respond to old states |
| Payment correlation | Uncorrelated per-hop | Hash-correlated across hops |

### 1.1 Loss of Payment-Proof Atomicity

With PTLCs, the adaptor signature that unlocks payment IS the acknowledgment
signature proving task completion. They are cryptographically inseparable.

With HTLCs, the payment preimage is independent of task completion. An executor
could:
- Reveal a preimage without completing the task
- Complete the task without receiving payment

**Mitigation**: Require separate signed attestations that bind payment hash to
task completion. This adds trust assumptions and complexity. See Section 7.

### 1.2 Watchtower Requirements

LN-penalty channels require watchtowers with access to revocation keys. If a
peer broadcasts an old state and the counterparty fails to respond within the
timelock window, funds are lost.

For satellites with intermittent ground contact, this means:
- Ground stations must run watchtowers for each satellite channel
- Watchtowers must hold revocation keys (security risk)
- Satellites must have reliable ground contact within punishment windows

**Mitigation**: Use conservative timelocks (weeks) and multiple redundant
watchtowers. Accept the operational complexity.

### 1.3 Full State History Required

With LN-penalty, every prior state is "toxic waste" that could be used to
steal funds. Implementations must retain all historical states and their
revocation secrets.

For constrained devices (satellites, IoT), this is problematic:
- Storage requirements grow with channel lifetime
- Backup/restore is complex (must include all states)
- Any state loss risks fund theft

**Mitigation**: Limit channel lifetime and close/reopen periodically. Accept
higher on-chain costs.

### 1.4 Payment Correlation

HTLCs use the same payment hash across all hops. Any party controlling
multiple nodes in a payment path can correlate the payment.

**Mitigation**: Accept reduced privacy. For satellite operations where
operators are known entities, this may be acceptable.

---

## 2. Lightning Network Protocol Background

### 2.1 BOLT Specifications

| BOLT | Description | Relevance |
|------|-------------|-----------|
| [BOLT 2](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md) | Peer protocol | HTLC addition, commitment signing |
| [BOLT 3](https://github.com/lightning/bolts/blob/master/03-transactions.md) | Transaction formats | HTLC output scripts |
| [BOLT 4](https://github.com/lightning/bolts/blob/master/04-onion-routing.md) | Onion routing | Multi-hop payment encoding |
| [BOLT 8](https://github.com/lightning/bolts/blob/master/08-transport.md) | Transport | Noise Protocol encryption |
| [BOLT 11](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md) | Invoice protocol | Payment request format |

### 2.2 HTLC Mechanics

An HTLC (Hash Time-Locked Contract) is a conditional payment:

```
HTLC Script (simplified):
-------------------------
IF
    # Payment path: recipient can claim with preimage
    <recipient_pubkey> CHECKSIG
    HASH256 <payment_hash> EQUAL
ELSE
    # Refund path: sender can reclaim after timeout
    <sender_pubkey> CHECKSIG
    <timeout> CHECKLOCKTIMEVERIFY
ENDIF
```

### 2.3 Channel State Updates (BOLT 2)

Adding an HTLC requires an interactive protocol:

```
+-----------------------------------------------------------------------------+
|                    BOLT 2: HTLC ADDITION PROTOCOL                           |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Node A (payer)                                    Node B (payee)           |
|       |                                                   |                 |
|       |--- update_add_htlc ------------------------------>|                 |
|       |    * channel_id                                   |                 |
|       |    * htlc_id                                      |                 |
|       |    * amount_msat                                  |                 |
|       |    * payment_hash                                 |                 |
|       |    * cltv_expiry                                  |                 |
|       |    * onion_routing_packet                         |                 |
|       |                                                   |                 |
|       |--- commitment_signed ---------------------------->|                 |
|       |    * signature (for B's new commitment tx)        |                 |
|       |    * htlc_signatures[]                            |                 |
|       |                                                   |                 |
|       |<-- revoke_and_ack --------------------------------|                 |
|       |    * per_commitment_secret (B's old state)        |                 |
|       |    * next_per_commitment_point                    |                 |
|       |                                                   |                 |
|       |<-- commitment_signed -----------------------------|                 |
|       |    * signature (for A's new commitment tx)        |                 |
|       |                                                   |                 |
|       |--- revoke_and_ack ------------------------------->|                 |
|       |    * per_commitment_secret (A's old state)        |                 |
|       |                                                   |                 |
|  HTLC now active in both commitment transactions                            |
|  Total: 5 messages, ~5 round trips with pipelining                          |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 2.4 HTLC Settlement

```
+-----------------------------------------------------------------------------+
|                    HTLC FULFILLMENT (Preimage Reveal)                       |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Node B (has preimage)                             Node A (payer)           |
|       |                                                   |                 |
|       |--- update_fulfill_htlc -------------------------->|                 |
|       |    * channel_id                                   |                 |
|       |    * htlc_id                                      |                 |
|       |    * payment_preimage                             |                 |
|       |                                                   |                 |
|       |--- commitment_signed ---------------------------->|                 |
|       |<-- revoke_and_ack --------------------------------|                 |
|       |<-- commitment_signed -----------------------------|                 |
|       |--- revoke_and_ack ------------------------------->|                 |
|       |                                                   |                 |
|  Payment complete. A has preimage as proof of payment.                      |
|  Total: 5 additional messages                                               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 2.5 Timing Analysis for ISL Windows

```
+-----------------------------------------------------------------------------+
|                    ISL CONTACT TIMING BUDGET                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Scenario: LEO satellites, 5-minute ISL window, 20ms RTT                    |
|                                                                             |
|  Protocol Phase              Messages    RTTs    Time (worst case)          |
|  -----------------------------------------------------------------          |
|  Connection establishment         4        2          40ms                  |
|  Channel reestablish (if needed)  4        2          40ms                  |
|  Invoice exchange                 2        1          20ms                  |
|  HTLC addition                    5        5         100ms                  |
|  Task execution              (variable)    -     1-60 seconds               |
|  HTLC fulfillment                 5        5         100ms                  |
|  -----------------------------------------------------------------          |
|  Total protocol overhead:                           ~300ms                  |
|  Available for task execution:                    4+ minutes                |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 3. System Architecture

### 3.1 Network Topology

```
+-----------------------------------------------------------------------------+
|                    SATELLITE LIGHTNING NETWORK                              |
+-----------------------------------------------------------------------------+
|                                                                             |
|                           SPACE SEGMENT                                     |
|  ========================================================================   |
|                                                                             |
|        +----------+         ISL          +----------+                       |
|        |Satellite |<-------------------->|Satellite |                       |
|        |    A     |      (payment        |    B     |                       |
|        |          |       channel)       |          |                       |
|        | LN Node  |                      | LN Node  |                       |
|        +----+-----+                      +----+-----+                       |
|             |                                  |                            |
|             | ISL/RF                      ISL/RF                            |
|             | Channel                    Channel                            |
|             |                                  |                            |
|        +----+-----+                      +----+-----+                       |
|        |Satellite |                      |Satellite |                       |
|        |    C     |<------ ISL --------->|    D     |                       |
|        |(Relay/   |                      |          |                       |
|        | Router)  |                      |          |                       |
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
|        |          |                      |          |                       |
|        | LN Node  |                      | LN Node  |                       |
|        +----+-----+                      +----+-----+                       |
|             |                                  |                            |
|             +----------> Bitcoin <-------------+                            |
|                         Blockchain                                          |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 3.2 Channel Types

| Channel Type | Purpose | Characteristics |
|--------------|---------|-----------------|
| **S2S Direct** | Payment between frequently-passing satellites | Opened during ISL window, persists across passes |
| **S2S Routed** | Payment via constellation mesh | Uses existing S2S channels as hops |
| **S2G (Satellite-Ground)** | On-chain settlement, liquidity | Always available during ground contact |
| **G2G (Ground-Ground)** | Cross-operator settlement | Standard Lightning routing |

### 3.3 Protocol Stack

```
+-----------------------------------------------------------------------------+
|                    SATELLITE LIGHTNING PROTOCOL STACK                       |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------------+    |
|  |  Application Layer                                                  |    |
|  |  * Task negotiation                                                 |    |
|  |  * Invoice management                                               |    |
|  |  * Arbiter interaction                                              |    |
|  +---------------------------------------------------------------------+    |
|                              |                                              |
|  +---------------------------------------------------------------------+    |
|  |  Lightning Layer (BOLT 1-12)                                        |    |
|  |  * Channel management                                               |    |
|  |  * HTLC protocol                                                    |    |
|  |  * Onion routing                                                    |    |
|  +---------------------------------------------------------------------+    |
|                              |                                              |
|  +---------------------------------------------------------------------+    |
|  |  Transport Layer (BOLT 8)                                           |    |
|  |  * Noise Protocol encryption                                        |    |
|  |  * Authenticated key exchange                                       |    |
|  +---------------------------------------------------------------------+    |
|                              |                                              |
|  +---------------------------------------------------------------------+    |
|  |  Link Layer                                                         |    |
|  |  * ISL (optical or RF)                                              |    |
|  |  * Ground link (S-band, X-band, Ka-band)                            |    |
|  +---------------------------------------------------------------------+    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 4. Payment Protocol

### 4.1 Task-Payment Flow

```
+-----------------------------------------------------------------------------+
|                    TASK-PAYMENT PROTOCOL                                    |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Satellite A (Customer/Payer)              Satellite B (Executor/Payee)     |
|                                                                             |
|  PRE-CONTACT (Coordination via ground or prior contact):                    |
|  =======================================================                    |
|                                                                             |
|       |    Task request published to coordination network                   |
|       |    Satellite B indicates availability and price                     |
|                                                                             |
|  ISL CONTACT ESTABLISHED:                                                   |
|  ========================                                                   |
|                                                                             |
|       |<--------------- ISL Link Up ----------------------->|               |
|       |                                                     |               |
|       |<-> channel_reestablish ---------------------------->|               |
|                                                                             |
|  PHASE 1: TASK NEGOTIATION                                                  |
|  -------------------------                                                  |
|       |                                                     |               |
|       |--- task_request ----------------------------------->|               |
|       |    * capability_token                               |               |
|       |    * task_parameters                                |               |
|       |    * max_payment_sats                               |               |
|       |                                                     |               |
|       |<-- task_accept + invoice ---------------------------|               |
|       |    * invoice (payment_hash H, amount)               |               |
|       |    * estimated_duration                             |               |
|                                                                             |
|  PHASE 2: PAYMENT SETUP (HTLC)                                              |
|  -----------------------------                                              |
|       |                                                     |               |
|       |--- update_add_htlc (hash=H, amount) --------------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|                                                                             |
|  Payment is now LOCKED. B can claim by revealing preimage.                  |
|  A cannot revoke. Either B claims or timeout refunds A.                     |
|                                                                             |
|  PHASE 3: TASK EXECUTION                                                    |
|  -----------------------                                                    |
|       |                                                     |               |
|       |                          Satellite B executes task  |               |
|       |                                                     |               |
|       |<-- task_complete -----------------------------------|               |
|       |    * result_hash                                    |               |
|       |    * execution_proof                                |               |
|                                                                             |
|  PHASE 4: PAYMENT SETTLEMENT                                                |
|  ---------------------------                                                |
|       |                                                     |               |
|       |<-- update_fulfill_htlc (preimage=R) ----------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|                                                                             |
|  Payment COMPLETE. A has preimage as receipt.                               |
|                                                                             |
|       |<--------------- ISL Link Down --------------------->|               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 4.2 Payment State Machine

```
+-----------------------------------------------------------------------------+
|                    PAYMENT STATE MACHINE                                    |
+-----------------------------------------------------------------------------+
|                                                                             |
|                      +-------------+                                        |
|                      |   INITIAL   |                                        |
|                      +------+------+                                        |
|                             | A sends update_add_htlc                       |
|                             v                                               |
|                      +-------------+                                        |
|                      |   OFFERED   | A has offered HTLC                     |
|                      +------+------+                                        |
|                             | Both sign new commitments                     |
|                             v                                               |
|       +--------------+-------------+--------------+                         |
|       |              |   LOCKED    |              |                         |
|       |              +------+------+              |                         |
|       |                     |                     |                         |
|       | B reveals      ISL lost          Timeout expires                    |
|       | preimage       (recoverable)     (refund)                           |
|       |                     |                     |                         |
|       v                     v                     v                         |
|  +---------+         +-------------+       +----------+                     |
|  |FULFILLED|         |   PENDING   |       | REFUNDED |                     |
|  |         |         |             |       |          |                     |
|  | B paid  |         | Resume on   |       | A gets   |                     |
|  | A has   |         | next ISL    |       | funds    |                     |
|  | receipt |         | contact     |       | back     |                     |
|  +---------+         +-------------+       +----------+                     |
|                                                                             |
|  KEY PROPERTY: Once LOCKED, payment WILL complete (one way or other)        |
|  Either B reveals preimage -> FULFILLED                                     |
|  Or timeout expires -> REFUNDED                                             |
|  No third party can interfere with this.                                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 4.3 ISL Disconnect Handling

```
+-----------------------------------------------------------------------------+
|                    ISL DISCONNECT RECOVERY                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Case 1: Disconnect BEFORE HTLC locked                                      |
|  -------------------------------------                                      |
|  * HTLC not in either commitment transaction                                |
|  * Payment simply didn't happen                                             |
|  * Retry on next ISL contact                                                |
|  * No funds at risk                                                         |
|                                                                             |
|  Case 2: Disconnect AFTER HTLC locked, BEFORE task complete                 |
|  ----------------------------------------------------------                 |
|  * HTLC is in both commitment transactions                                  |
|  * B has not revealed preimage                                              |
|                                                                             |
|  Options for B:                                                             |
|  a) Complete task, hold preimage, settle on next ISL contact                |
|  b) Abandon task, let HTLC timeout (A gets refund)                          |
|                                                                             |
|  If B completes task:                                                       |
|  * B can claim payment on next ISL contact with A                           |
|  * Or B can claim on-chain if no ISL contact before timeout                 |
|  * B must monitor timeout and force-close if necessary                      |
|                                                                             |
|  Case 3: Disconnect AFTER preimage revealed, BEFORE settlement              |
|  ------------------------------------------------------------               |
|  * A has received update_fulfill_htlc with preimage                         |
|  * But commitment update not complete                                       |
|                                                                             |
|  On next ISL contact:                                                       |
|  * channel_reestablish synchronizes state                                   |
|  * If A has preimage, HTLC removed from A's commitment                      |
|  * If state inconsistent, use commitment transaction proofs                 |
|                                                                             |
|  Worst case:                                                                |
|  * B force-closes with commitment showing HTLC                              |
|  * B claims HTLC output using preimage                                      |
|  * On-chain settlement via ground station                                   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 5. Multi-Hop Payments

### 5.1 Routing Through Constellation

When payer and payee are not in direct ISL contact:

```
+-----------------------------------------------------------------------------+
|                    MULTI-HOP PAYMENT ROUTING                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Satellite A          Satellite R1         Satellite R2         Satellite B |
|  (Payer)              (Router)             (Router)             (Payee)     |
|       |                    |                    |                    |      |
|       |<-- ISL ----------->|<-- ISL ---------->|<-- ISL ----------->|      |
|       |   Channel 1        |   Channel 2       |   Channel 3        |      |
|                                                                             |
|  Payment: A pays B 10,000 sats via R1, R2                                   |
|  Routing fees: R1 takes 100 sats, R2 takes 100 sats                         |
|                                                                             |
|  HTLC Chain (same payment_hash H throughout):                               |
|  ----------------------------------------------                             |
|       |                    |                    |                    |      |
|       |- HTLC 10,200 sats >|                    |                    |      |
|       |  timeout: T        |- HTLC 10,100 sats >|                    |      |
|       |                    |  timeout: T-144    |- HTLC 10,000 sats >|      |
|       |                    |                    |  timeout: T-288    |      |
|       |                    |                    |                    |      |
|       |                    |                    |<-- preimage R -----|      |
|       |                    |<-- preimage R -----|                    |      |
|       |<-- preimage R -----|                    |                    |      |
|                                                                             |
|  Timing constraint: All hops must be contactable within timeout window      |
|  Decreasing timeouts ensure B claims first, then R2, then R1, then A        |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 5.2 Onion Routing

Standard Lightning onion routing (BOLT 4) provides privacy:

- Each hop only sees where to forward (next hop)
- Each hop only sees amount and timeout for their HTLC
- No hop can see origin, destination, or full path
- Route is encrypted layer-by-layer, decrypted hop-by-hop

### 5.3 Routing Challenges in Space

| Challenge | Mitigation |
|-----------|------------|
| **Intermittent paths** | Route through satellites with overlapping ISL windows |
| **Topology changes** | Constellation-aware routing using orbital mechanics |
| **Partial path failure** | HTLC timeouts ensure atomic success or refund |
| **No global view** | Gossiped topology updates during ISL/ground contacts |

---

## 6. Arbiter Integration

### 6.1 The Fair Exchange Problem

Task payment is a fair exchange: A wants to pay only if task done, B wants
payment only if they'll be paid.

**Cryptography alone cannot solve this.** We need minimal trust.

In full SCRAP with PTLCs, the adaptor signature binds payment to proof. In
HTLC fallback mode, we need an arbiter or attestation layer.

### 6.2 Trust-Minimized Arbiter Design

```
+-----------------------------------------------------------------------------+
|                    ARBITER TRUST MODEL                                      |
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

### 6.3 Arbiter Protocol Options

**Option 1: Immediate Settlement (No Arbiter)**
- B completes task during ISL window
- A verifies completion directly
- B reveals preimage, payment settles
- Works for: Simple tasks, trusted relationships, low value

**Option 2: Deferred Settlement with Arbiter**
- HTLC locked during ISL
- B submits completion proof to arbiter
- Arbiter verifies and approves
- B reveals preimage on next ISL contact

**Option 3: Timeout-Based Default Approval**
- B submits completion to arbiter
- If arbiter doesn't respond within X hours: auto-approve
- A must actively dispute to block payment
- Protects B from unresponsive arbiter/customer

---

## 7. Attestation Layer

Because HTLC preimages are independent of task completion, this fallback mode
requires an attestation layer to partially recover payment-proof binding.

### 7.1 Attestation Structure

```
DeliveryAttestation:
  v: 1
  task_token_id: <16 bytes>       # Links to capability token
  payment_hash: <32 bytes>        # Links to HTLC
  output_hash: SHA256(delivered_data)
  timestamp: 1704067200
  executor_pubkey: <33 bytes>
  sig: <schnorr-signature>
```

### 7.2 Verification

Before revealing the preimage, the gateway MUST verify:

1. Attestation signature is valid
2. `task_token_id` matches the requested task
3. `payment_hash` matches the HTLC
4. `output_hash` matches received data
5. `timestamp` is within acceptable window

### 7.3 Trust Assumption

The gateway must trust the executor to provide honest attestations. Unlike
PTLC mode where payment and proof are cryptographically bound, fallback mode
relies on:

- Executor reputation
- Economic incentives (future business)
- Legal agreements between operators

This is strictly weaker than the cryptographic guarantees of full SCRAP.

---

## 8. Ground Station Functions

### 8.1 On-Chain Settlement

Ground stations provide Bitcoin network connectivity:

| Function | Description |
|----------|-------------|
| **Channel funding** | Broadcast funding tx, monitor confirmations |
| **Cooperative close** | Broadcast closing tx negotiated by satellites |
| **Force close** | Broadcast commitment tx if peer unresponsive |
| **Liquidity management** | Submarine swaps, splicing |
| **Blockchain monitoring** | Watch for cheating, HTLC timeouts |

**Trust model**: Ground station is operated by satellite's own operator.
Cannot steal funds (doesn't have satellite's keys). Can only delay or fail
to broadcast.

### 8.2 Watchtower Function

Ground station acts as watchtower for its satellite:

1. Satellite uploads watch data during ground contact:
   - Commitment transaction ID to watch for
   - Pre-signed penalty transaction
   - Revocation key for that state

2. Ground station monitors each Bitcoin block:
   - Check if any watched commitment transactions appear
   - If cheating detected, broadcast penalty transaction
   - Alert satellite

**Critical requirement**: Watchtower must hold revocation keys, creating a
security risk. This is a fundamental limitation of LN-penalty channels that
ln-symmetry (full SCRAP) eliminates.

---

## 9. Implementation Requirements

### 9.1 Satellite Node Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **CPU** | ARM Cortex-A class or better | For crypto operations |
| **RAM** | 64 MB minimum | Channel state, routing tables |
| **Storage** | 1 MB per channel | Commitment history, HTLCs |
| **RNG** | Hardware TRNG | Critical for key/nonce generation |
| **Clock** | GPS-disciplined | For HTLC timeouts |

### 9.2 Lightning Implementation Options

| Implementation | Language | Size | Satellite Suitability |
|----------------|----------|------|----------------------|
| **LDK** | Rust | ~2 MB | Excellent - modular, embeddable |
| **CLN** | C | ~10 MB | Good - lightweight |
| **Custom** | Rust/C | <1 MB | Best - minimal implementation |

**Recommendation**: LDK-based custom implementation or minimal BOLT-compliant
implementation.

---

## 10. Security Analysis

### 10.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| **Counterparty broadcasts old state** | Watchtower (ground station) broadcasts penalty |
| **Payment intercepted on ISL** | Noise Protocol encryption (BOLT 8) |
| **HTLC timeout manipulation** | GPS-disciplined clocks, conservative timeouts |
| **Eclipse attack on satellite** | Multiple ground station connections |
| **Malicious routing node** | Standard LN routing fees, reputation |

### 10.2 ISL-Specific Security

```
+-----------------------------------------------------------------------------+
|                    ISL SECURITY CONSIDERATIONS                              |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. LINK AUTHENTICATION                                                     |
|  ----------------------                                                     |
|  * BOLT 8 handshake provides mutual authentication                          |
|  * Node IDs are secp256k1 public keys                                       |
|  * Cannot impersonate another satellite                                     |
|                                                                             |
|  2. ENCRYPTION                                                              |
|  ------------                                                               |
|  * BOLT 8 uses ChaCha20-Poly1305 AEAD                                       |
|  * Forward secrecy via ephemeral keys                                       |
|  * ISL eavesdropper sees encrypted traffic only                             |
|                                                                             |
|  3. PHYSICAL LAYER                                                          |
|  -------------                                                              |
|  * Optical ISL: Narrow beam, hard to intercept                              |
|  * RF ISL: Wider beam, but encrypted at Lightning layer                     |
|  * Jamming: Causes disconnect, doesn't compromise funds                     |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 11. What Still Works

The following SCRAP components function identically in fallback mode:

### Capability Tokens

Capability token verification is unchanged:
- Token structure (v, iss, sub, aud, iat, exp, token_id, cap, prf, sig)
- Delegation and attenuation
- Replay protection
- Signature verification

### Task Routing

Task routing through agents works identically:
- Multi-hop task forwarding
- Capability verification at each hop
- Output hash commitments

### Ground-Agent Coordination

Infrastructure coordination is unchanged:
- Gateway operation
- Operator communication

---

## 12. Deployment Guidance

### 12.1 When to Use Fallback Mode

- Development and testing
- Proof-of-concept demonstrations
- Ecosystem tooling development
- Academic research

### 12.2 When NOT to Use Fallback Mode

- Production payments between untrusted parties
- High-value task execution
- Long-lived channels with significant capacity
- Deployments where watchtower reliability is uncertain

### 12.3 Migration Path

When BIP-118 activates:

1. Close existing LN-penalty channels cooperatively
2. Open new ln-symmetry channels
3. Update attestation layer to use adaptor signatures
4. Remove watchtower key custody
5. Simplify state backup to latest-only

The capability token layer requires no changes. Task routing requires no
changes. Only the payment layer migrates.

---

## 13. References

### SCRAP Specifications
- [SCRAP.md](SCRAP.md) - Full protocol specification (ln-symmetry + PTLCs)
- [BIP-SCRAP.md](BIP-SCRAP.md) - Informational BIP motivating ANYPREVOUT
- [PTLC-FALLBACK.md](PTLC-FALLBACK.md) - On-chain PTLC fallback

### BOLT Specifications
- [BOLT 2: Peer Protocol](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md)
- [BOLT 3: Transactions](https://github.com/lightning/bolts/blob/master/03-transactions.md)
- [BOLT 4: Onion Routing](https://github.com/lightning/bolts/blob/master/04-onion-routing.md)
- [BOLT 8: Transport](https://github.com/lightning/bolts/blob/master/08-transport.md)

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/)
- [Core Lightning](https://docs.corelightning.org/)

### Related Work
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)
- [Bitcoin Optech: eltoo](https://bitcoinops.org/en/topics/eltoo/)
