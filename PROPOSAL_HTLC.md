# Satellite Payment Protocol Using HTLCs

## Abstract

This proposal defines a trustless payment system for inter-satellite task execution using Bitcoin Lightning Network Hash Time-Locked Contracts (HTLCs). Satellites operate as Lightning Network nodes, establishing payment channels with each other and completing the interactive HTLC protocol during Inter-Satellite Link (ISL) contact windows. Ground stations provide on-chain settlement and liquidity management but do not participate in space-segment payment flows. Task verification requires a trusted arbiter, but the payment rails are fully trustless and Bitcoin-native.

---

## 1. Introduction

### 1.1 Problem Statement

Satellites need to pay each other for services (imaging, relay, processing) with unique constraints:

1. **Intermittent connectivity**: ISL contact windows of 2-15 minutes during orbital passes
2. **Interactive protocols**: Lightning/MuSig2 require multiple round-trip messages
3. **Multi-hop task chains**: Tasks delegated through 3+ satellites require payment at each hop
4. **Trustless settlement**: Operators should not need to trust each other for payment validity

### 1.2 Key Assumption

**Satellites have sufficient ISL contact time for interactive protocols.**

During a close approach, two LEO satellites have:
- Contact window: 2-15 minutes typical
- ISL latency: 1-50ms depending on distance
- Round trips available: Hundreds to thousands

This is sufficient for:
- MuSig2 signing (3 round trips, ~150ms)
- HTLC protocol (5 messages, ~250ms)
- Full payment including task negotiation

### 1.3 Design Goals

| Goal | Description |
|------|-------------|
| **Trustless payments** | Payment enforced by Bitcoin script, not third parties |
| **Direct S2S settlement** | Payments complete during ISL contact, no ground delegation |
| **Atomic execution** | Payment either completes fully or refunds completely |
| **Multi-hop routing** | Payments can route through satellite constellations |
| **Minimal arbiter trust** | Arbiter controls timing only, cannot steal funds |

### 1.4 Non-Goals

- Ground station delegation of payment signing
- Asynchronous/offline payment initiation (both parties interact during ISL window)
- Automatic task verification (requires domain-specific judgment)

---

## 2. Background: Lightning Network Protocol

### 2.1 BOLT Specifications Overview

| BOLT | Description | Relevance |
|------|-------------|-----------|
| [BOLT 2](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md) | Peer protocol for channel management | HTLC addition, commitment signing |
| [BOLT 3](https://github.com/lightning/bolts/blob/master/03-transactions.md) | Transaction formats | HTLC output scripts |
| [BOLT 4](https://github.com/lightning/bolts/blob/master/04-onion-routing.md) | Onion routing | Multi-hop payment encoding |
| [BOLT 11](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md) | Invoice protocol | Payment request format |
| [BOLT 12](https://bolt12.org/) | Offers | Reusable payment endpoints |

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

Adding an HTLC requires interactive protocol:

```
+-----------------------------------------------------------------------------+
|                    BOLT 2: HTLC ADDITION PROTOCOL                            |
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
|                    HTLC FULFILLMENT (Preimage Reveal)                        |
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
|                    ISL CONTACT TIMING BUDGET                                 |
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
|  With MuSig2/Taproot channels, add ~150ms for signing rounds                |
|  Still well within typical ISL windows                                      |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 3. System Architecture

### 3.1 Network Topology

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

### 3.3 Satellite Lightning Node

Each satellite runs a lightweight Lightning node:

```python
class SatelliteLightningNode:
    """
    Lightning node implementation for satellite operations.
    Designed for intermittent connectivity and resource constraints.
    """

    def __init__(self, node_id: bytes, signing_key: PrivateKey):
        self.node_id = node_id
        self.signing_key = signing_key

        # Channel state
        self.channels: Dict[ChannelId, Channel] = {}
        self.pending_htlcs: Dict[PaymentHash, HTLC] = {}

        # Peer connections (ephemeral during ISL windows)
        self.peers: Dict[NodeId, PeerConnection] = {}

        # Invoice management
        self.preimages: Dict[PaymentHash, bytes] = {}  # For receiving
        self.invoices: Dict[PaymentHash, Invoice] = {}

    def on_isl_contact(self, peer_node_id: bytes, link: ISLConnection):
        """
        Called when ISL contact established with another satellite.
        This is when all payment activity occurs.
        """
        # Establish or resume Lightning peer connection
        peer = self.connect_peer(peer_node_id, link)

        # Reestablish any existing channels (BOLT 2 channel_reestablish)
        for channel in self.get_channels_with(peer_node_id):
            self.reestablish_channel(peer, channel)

        # Process any pending payments/tasks
        self.process_pending_operations(peer)

    def on_isl_disconnect(self, peer_node_id: bytes):
        """
        Called when ISL contact lost.
        Clean up peer connection, channels remain valid.
        """
        if peer_node_id in self.peers:
            del self.peers[peer_node_id]
        # Channels persist - will reestablish on next contact

    def create_invoice(self, amount_msat: int, description: str) -> Invoice:
        """
        Create an invoice for receiving payment.
        Called when satellite will perform a task.
        """
        preimage = os.urandom(32)
        payment_hash = sha256(preimage)

        self.preimages[payment_hash] = preimage

        invoice = Invoice(
            payment_hash=payment_hash,
            amount_msat=amount_msat,
            description=description,
            expiry=3600 * 24,  # 24 hours
            node_id=self.node_id,
            route_hints=self.get_route_hints()
        )

        self.invoices[payment_hash] = invoice
        return invoice

    def send_payment(self, invoice: Invoice, channel: Channel) -> PaymentResult:
        """
        Send payment over a direct channel.
        Must be called during ISL contact with payee.
        """
        if not channel.peer_connected:
            raise PaymentError("Peer not connected - no ISL contact")

        # BOLT 2: Add HTLC
        htlc = self.add_htlc(
            channel=channel,
            amount_msat=invoice.amount_msat,
            payment_hash=invoice.payment_hash,
            cltv_expiry=self.current_height + 144
        )

        # Wait for fulfillment or failure
        # This happens within the ISL window
        result = self.await_htlc_resolution(htlc, timeout=60)

        if result.preimage:
            return PaymentResult(success=True, preimage=result.preimage)
        else:
            return PaymentResult(success=False, error=result.error)
```

### 3.4 Channel Lifecycle

```
+-----------------------------------------------------------------------------+
|                    SATELLITE CHANNEL LIFECYCLE                               |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. CHANNEL OPEN (First ISL Contact)                                        |
|  ===================================                                        |
|                                                                             |
|  Satellite A                                           Satellite B          |
|       |                                                     |               |
|       |--- open_channel ----------------------------------->|               |
|       |    (funding_satoshis, push_msat, channel_flags)     |               |
|       |                                                     |               |
|       |<-- accept_channel ----------------------------------|               |
|       |                                                     |               |
|       |    [Create funding transaction - 2-of-2 multisig]   |               |
|       |    [Exchange signatures for commitment txs]         |               |
|       |                                                     |               |
|       |--- funding_created -------------------------------->|               |
|       |<-- funding_signed ----------------------------------|               |
|       |                                                     |               |
|       |    [Funding tx broadcast via ground station]        |               |
|       |    [Wait for confirmations - can span multiple      |               |
|       |     ISL windows and ground contacts]                |               |
|       |                                                     |               |
|       |--- channel_ready ---------------------------------->|               |
|       |<-- channel_ready -----------------------------------|               |
|       |                                                     |               |
|  Channel now operational for payments                                       |
|                                                                             |
|                                                                             |
|  2. NORMAL OPERATION (Subsequent ISL Contacts)                              |
|  =============================================                              |
|                                                                             |
|  On each ISL contact:                                                       |
|       |                                                     |               |
|       |<-> channel_reestablish ---------------------------->|               |
|       |    (next_commitment_number, next_revocation_number) |               |
|       |                                                     |               |
|       |    [Reconcile any state differences]                |               |
|       |    [Resume normal HTLC operations]                  |               |
|       |                                                     |               |
|       |<-> update_add_htlc / update_fulfill_htlc ---------->|               |
|       |<-> commitment_signed / revoke_and_ack ------------->|               |
|       |                                                     |               |
|  Between contacts:                                                          |
|       - Channel state persisted locally                                     |
|       - Pending HTLCs remain pending                                        |
|       - No communication possible                                           |
|                                                                             |
|                                                                             |
|  3. CHANNEL CLOSE                                                           |
|  ================                                                           |
|                                                                             |
|  Cooperative (during ISL contact):                                          |
|       |--- shutdown --------------------------------------->|               |
|       |<-- shutdown ----------------------------------------|               |
|       |<-> closing_signed (fee negotiation) --------------->|               |
|       |    [Broadcast closing tx via ground]                |               |
|                                                                             |
|  Force close (unilateral, if peer unresponsive):                            |
|       |    [Broadcast commitment tx via ground]             |               |
|       |    [Wait for timelock, claim outputs]               |               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 4. Payment Protocol

### 4.1 Task-Payment Flow

```
+-----------------------------------------------------------------------------+
|                    TASK-PAYMENT PROTOCOL                                     |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Satellite A (Customer/Payer)              Satellite B (Executor/Payee)     |
|                                                                             |
|  PRE-CONTACT (Coordination via ground or prior contact):                    |
|  =======================================================                    |
|                                                                             |
|       |    Task request published to coordination network                   |
|       |    Satellite B indicates availability and price                     |
|       |                                                                     |
|                                                                             |
|  ISL CONTACT ESTABLISHED:                                                   |
|  ========================                                                   |
|                                                                             |
|       |<--------------- ISL Link Up ----------------------->|               |
|       |                                                     |               |
|       |<-> channel_reestablish ---------------------------->|               |
|       |                                                     |               |
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
|       |    * execution_commitment                           |               |
|       |                                                     |               |
|                                                                             |
|  PHASE 2: PAYMENT SETUP (HTLC)                                              |
|  -----------------------------                                              |
|       |                                                     |               |
|       |--- update_add_htlc (hash=H, amount) --------------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|       |                                                     |               |
|  Payment is now LOCKED. B can claim by revealing preimage.                  |
|  A cannot revoke. Either B claims or timeout refunds A.                     |
|                                                                             |
|                                                                             |
|  PHASE 3: TASK EXECUTION                                                    |
|  -----------------------                                                    |
|       |                                                     |               |
|       |                          Satellite B executes task: |               |
|       |                          * Imaging                  |               |
|       |                          * Data relay               |               |
|       |                          * Processing               |               |
|       |                          * RPO maneuver             |               |
|       |                                                     |               |
|       |<-- task_progress (optional status updates) ---------|               |
|       |                                                     |               |
|       |<-- task_complete -----------------------------------|               |
|       |    * result_hash                                    |               |
|       |    * execution_proof                                |               |
|       |    * data_pointer (if applicable)                   |               |
|       |                                                     |               |
|                                                                             |
|  PHASE 4: PAYMENT SETTLEMENT                                                |
|  ---------------------------                                                |
|       |                                                     |               |
|       |    [A verifies task_complete is acceptable]         |               |
|       |                                                     |               |
|       |<-- update_fulfill_htlc (preimage=R) ----------------|               |
|       |<-- commitment_signed -------------------------------|               |
|       |--- revoke_and_ack --------------------------------->|               |
|       |--- commitment_signed ------------------------------>|               |
|       |<-- revoke_and_ack ----------------------------------|               |
|       |                                                     |               |
|  Payment COMPLETE. A has preimage as receipt.                               |
|  B's channel balance increased.                                             |
|                                                                             |
|       |<--------------- ISL Link Down --------------------->|               |
|                                                                             |
|  TOTAL TIME: ~1-5 minutes depending on task                                 |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 4.2 Payment Timing and Atomicity

```
+-----------------------------------------------------------------------------+
|                    PAYMENT STATE MACHINE                                     |
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
|  Either B reveals preimage -> FULFILLED                                      |
|  Or timeout expires -> REFUNDED                                              |
|  No third party can interfere with this.                                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 4.3 ISL Disconnect During Payment

If ISL contact is lost during the payment flow:

```
+-----------------------------------------------------------------------------+
|                    ISL DISCONNECT RECOVERY                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Case 1: Disconnect BEFORE HTLC locked                                      |
|  -------------------------------------                                      |
|  * HTLC not in either commitment transaction                                |
|  * Payment simply didn't happen                                             |
|  * Retry on next ISL contact                                                |
|  * No funds at risk                                                         |
|                                                                             |
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
|                    MULTI-HOP PAYMENT ROUTING                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Satellite A          Satellite R1         Satellite R2         Satellite B |
|  (Payer)              (Router)             (Router)             (Payee)     |
|       |                    |                    |                    |      |
|       |<-- ISL ----------->|<-- ISL ---------->|<-- ISL ----------->|      |
|       |   Channel 1        |   Channel 2       |   Channel 3        |      |
|       |                    |                    |                    |      |
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
|       |                    |                    |                    |      |
|                                                                             |
|  Timing constraint: All hops must be contactable within timeout window      |
|  Decreasing timeouts ensure B claims first, then R2, then R1, then A        |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 5.2 Onion Routing for Privacy

Standard Lightning onion routing (BOLT 4) applies:

```python
class OnionPacket:
    """
    Each hop only sees:
    - Where to forward (next hop)
    - Amount and timeout for their HTLC
    - Cannot see origin, destination, or full path
    """

    def create_onion(self, route: List[NodeId], payment_hash: bytes,
                     final_amount: int) -> bytes:
        """
        Create onion-encrypted routing packet.
        Each hop can only decrypt their layer.
        """
        packet = b""

        # Build from destination backwards
        for i, hop in enumerate(reversed(route)):
            hop_data = HopData(
                short_channel_id=hop.channel_id,
                amt_to_forward=self.amounts[i],
                outgoing_cltv=self.timeouts[i]
            )

            # Encrypt this layer with hop's public key
            packet = self.wrap_layer(packet, hop_data, hop.pubkey)

        return packet
```

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

Task payment is a fair exchange: A wants to pay only if task done, B wants payment only if they'll be paid.

**Cryptography cannot solve this.** We need minimal trust.

### 6.2 Trust-Minimized Arbiter Design

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

### 6.3 Arbiter Protocol

```
+-----------------------------------------------------------------------------+
|                    ARBITER VERIFICATION FLOW                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  OPTION 1: Immediate Settlement (No Arbiter)                                |
|  ===========================================                                |
|                                                                             |
|  * B completes task during ISL window                                       |
|  * A verifies completion directly                                           |
|  * B reveals preimage, payment settles                                      |
|  * Works for: Simple tasks, trusted relationships, low value                |
|                                                                             |
|                                                                             |
|  OPTION 2: Deferred Settlement with Arbiter                                 |
|  ===========================================                                |
|                                                                             |
|  Satellite A              Arbiter               Satellite B                 |
|       |                      |                       |                      |
|       |-- HTLC locked ------------------------------->                      |
|       |   (payment_hash H)   |                       |                      |
|       |                      |                       |                      |
|       |                      |<-- task_complete -----|                      |
|       |                      |    (proof, data)      |                      |
|       |                      |                       |                      |
|       |                      |   [Arbiter verifies]  |                      |
|       |                      |                       |                      |
|       |                      |--- approval --------->|                      |
|       |                      |                       |                      |
|       |<-- preimage R -------------------------------|                      |
|       |   (on next ISL)      |                       |                      |
|       |                      |                       |                      |
|                                                                             |
|  OPTION 3: Timeout-Based Default Approval                                   |
|  ========================================                                   |
|                                                                             |
|  * B submits completion to arbiter                                          |
|  * If arbiter doesn't respond within X hours: auto-approve                  |
|  * A must actively dispute to block payment                                 |
|  * Protects B from unresponsive arbiter/customer                            |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 7. On-Chain Settlement

### 7.1 Ground Station Role

Ground stations provide Bitcoin network connectivity:

```
+-----------------------------------------------------------------------------+
|                    GROUND STATION FUNCTIONS                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. CHANNEL FUNDING                                                         |
|  ------------------                                                         |
|  * Satellite requests channel open with another satellite                   |
|  * Funding transaction created (2-of-2 multisig or MuSig2)                  |
|  * Ground station broadcasts funding tx to Bitcoin network                  |
|  * Monitors for confirmations                                               |
|  * Notifies satellite when channel is ready                                 |
|                                                                             |
|  2. COOPERATIVE CLOSE                                                       |
|  --------------------                                                       |
|  * Satellites agree to close channel (during ISL contact)                   |
|  * Create and sign closing transaction                                      |
|  * Ground station broadcasts closing tx                                     |
|                                                                             |
|  3. FORCE CLOSE                                                             |
|  -------------                                                              |
|  * Satellite cannot reach counterparty                                      |
|  * Satellite signs and sends commitment tx to ground station                |
|  * Ground station broadcasts commitment tx                                  |
|  * Monitors for counterparty response                                       |
|  * Handles HTLC claims/timeouts                                             |
|                                                                             |
|  4. LIQUIDITY MANAGEMENT                                                    |
|  -------------------------                                                  |
|  * Satellite requests channel rebalancing                                   |
|  * Ground station facilitates submarine swaps or splicing                   |
|  * Adds/removes liquidity from satellite channels                           |
|                                                                             |
|  5. BLOCKCHAIN MONITORING                                                   |
|  -------------------------                                                  |
|  * Watch for cheating attempts (old commitment broadcasts)                  |
|  * Broadcast penalty transactions if needed                                 |
|  * Monitor HTLC timeouts                                                    |
|                                                                             |
|  TRUST MODEL: Ground station is operated by satellite's own operator        |
|  Ground station cannot steal funds (doesn't have satellite's keys)          |
|  Ground station can only delay or fail to broadcast                         |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 7.2 Watchtower Function

Ground station acts as watchtower for its satellite:

```python
class SatelliteWatchtower:
    """
    Ground station monitors blockchain for cheating attempts.
    Satellite uploads encrypted penalty data during ground contacts.
    """

    def __init__(self, satellite_id: bytes):
        self.satellite_id = satellite_id
        self.watched_channels: Dict[ChannelId, WatchData] = {}

    def upload_watch_data(self, channel_id: bytes,
                          commitment_txid: bytes,
                          penalty_tx: bytes,
                          revocation_key: bytes):
        """
        Called by satellite during ground contact.
        Uploads data needed to penalize cheating counterparty.
        """
        self.watched_channels[channel_id] = WatchData(
            commitment_txid=commitment_txid,
            penalty_tx=penalty_tx,
            revocation_key=revocation_key
        )

    def on_block(self, block: Block):
        """
        Called for each new Bitcoin block.
        Check if any watched commitment transactions appear.
        """
        for tx in block.transactions:
            for channel_id, watch_data in self.watched_channels.items():
                if tx.txid == watch_data.commitment_txid:
                    # Cheating detected! Broadcast penalty.
                    self.broadcast_penalty(watch_data.penalty_tx)
                    self.alert_satellite(channel_id, "PENALTY_BROADCAST")
```

---

## 8. Implementation Considerations

### 8.1 Satellite Node Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **CPU** | ARM Cortex-A class or better | For crypto operations |
| **RAM** | 64 MB minimum | Channel state, routing tables |
| **Storage** | 1 MB per channel | Commitment history, HTLCs |
| **RNG** | Hardware TRNG | Critical for key/nonce generation |
| **Clock** | GPS-disciplined | For HTLC timeouts |

### 8.2 Protocol Stack

```
+-----------------------------------------------------------------------------+
|                    SATELLITE LIGHTNING PROTOCOL STACK                        |
+-----------------------------------------------------------------------------+
|                                                                             |
|  +---------------------------------------------------------------------+   |
|  |  Application Layer                                                   |   |
|  |  * Task negotiation                                                  |   |
|  |  * Invoice management                                                |   |
|  |  * Arbiter interaction                                               |   |
|  +---------------------------------------------------------------------+   |
|                              |                                              |
|  +---------------------------------------------------------------------+   |
|  |  Lightning Layer (BOLT 1-12)                                         |   |
|  |  * Channel management                                                |   |
|  |  * HTLC protocol                                                     |   |
|  |  * Onion routing                                                     |   |
|  +---------------------------------------------------------------------+   |
|                              |                                              |
|  +---------------------------------------------------------------------+   |
|  |  Transport Layer (BOLT 8)                                            |   |
|  |  * Noise Protocol encryption                                         |   |
|  |  * Authenticated key exchange                                        |   |
|  +---------------------------------------------------------------------+   |
|                              |                                              |
|  +---------------------------------------------------------------------+   |
|  |  Link Layer                                                          |   |
|  |  * ISL (optical or RF)                                               |   |
|  |  * Ground link (S-band, X-band, Ka-band)                             |   |
|  +---------------------------------------------------------------------+   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 8.3 Lightning Implementation Options

| Implementation | Language | Size | Satellite Suitability |
|----------------|----------|------|----------------------|
| **LDK** | Rust | ~2 MB | Excellent - modular, embeddable |
| **Eclair** | Scala/JVM | ~50 MB | Poor - JVM overhead |
| **LND** | Go | ~30 MB | Moderate - full node |
| **CLN** | C | ~10 MB | Good - lightweight |
| **Custom** | Rust/C | <1 MB | Best - minimal implementation |

**Recommendation**: LDK-based custom implementation or minimal BOLT-compliant implementation.

---

## 9. PTLC Enhancements

### 9.1 PTLC Benefits for Satellites

When PTLCs become available, the protocol improves:

| Aspect | HTLC | PTLC |
|--------|------|------|
| **Privacy** | Same hash across route | Unique points per hop |
| **Routing correlation** | Observable | Unlinkable |
| **Task binding** | Separate proof | Signature IS proof |
| **On-chain footprint** | Reveals hash/preimage | Indistinguishable |

### 9.2 Task-Bound PTLC

With PTLCs, the executor's signature on task output directly unlocks payment:

```
+-----------------------------------------------------------------------------+
|                    PTLC TASK-PAYMENT BINDING                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Setup:                                                                     |
|  ------                                                                     |
|  A wants B to execute task T with expected output O                         |
|                                                                             |
|  Adaptor point: P = Hash-to-Curve(task_id || B_pubkey)                      |
|  Adaptor secret: s = B's signature on output_hash                           |
|                                                                             |
|  Protocol:                                                                  |
|  ---------                                                                  |
|  1. A creates PTLC locked to point P                                        |
|  2. B executes task, produces output O                                      |
|  3. B computes output_hash = SHA256(O)                                      |
|  4. B signs: sig_B = Sign(B_privkey, output_hash)                           |
|  5. sig_B IS the adaptor secret s that unlocks PTLC                         |
|  6. Payment completes; A receives sig_B as proof                            |
|                                                                             |
|  Properties:                                                                |
|  -----------                                                                |
|  * B cannot claim without producing signed output                           |
|  * A receives cryptographic proof of task completion                        |
|  * No separate preimage management                                          |
|  * Proof and payment are atomic                                             |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 9.3 PTLC Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Schnorr (BIP 340)** | Complete | Taproot activation Nov 2021 |
| **MuSig2 (BIP 327)** | Complete | Spec finalized 2024 |
| **Taproot channels** | Experimental | LND v0.17+, CLN in progress |
| **PTLC in Lightning** | Research | No implementation yet |

**Timeline estimate**: PTLCs in production Lightning: 2-4 years.

### 9.4 Migration Path

1. **Now**: Deploy HTLC-based direct S2S payments
2. **When available**: Upgrade to Taproot channels (better privacy)
3. **Future**: Add PTLC support for task-bound payments

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
|                    ISL SECURITY CONSIDERATIONS                               |
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

## 11. References

### BOLT Specifications
- [BOLT 2: Peer Protocol](https://github.com/lightning/bolts/blob/master/02-peer-protocol.md)
- [BOLT 3: Transactions](https://github.com/lightning/bolts/blob/master/03-transactions.md)
- [BOLT 4: Onion Routing](https://github.com/lightning/bolts/blob/master/04-onion-routing.md)
- [BOLT 8: Transport](https://github.com/lightning/bolts/blob/master/08-transport.md)
- [BOLT 12: Offers](https://bolt12.org/)

### Implementations
- [LDK (Lightning Dev Kit)](https://lightningdevkit.org/)
- [LND](https://docs.lightning.engineering/)
- [Core Lightning](https://docs.corelightning.org/)
- [Eclair](https://github.com/ACINQ/eclair)

### PTLCs and Taproot
- [Bitcoin Optech: PTLCs](https://bitcoinops.org/en/topics/ptlc/)
- [Bitcoin Optech: MuSig](https://bitcoinops.org/en/topics/musig/)
- [Taproot Lightning Updates](https://github.com/t-bast/lightning-docs/blob/master/taproot-updates.md)

### Related Work
- [Async Payments](https://bitcoinops.org/en/topics/async-payments/)
- [Trampoline Routing](https://bitcoinops.org/en/topics/trampoline-payments/)
- [Suredbits PTLC PoC](https://suredbits.com/ptlc-proof-of-concept/)
