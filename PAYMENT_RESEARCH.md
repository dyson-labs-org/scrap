# Satellite Task Payment Systems

## Executive Summary

This document investigates Bitcoin-based payment systems for inter-satellite task execution, addressing the unique challenge that satellites operate with intermittent connectivity and cannot always verify payments in real-time. We propose a hybrid architecture combining **eCash bearer tokens** for offline payment capability with **dedicated Lightning channels** for settlement, enabling satellites to function as "prepaid" payment nodes.

---

## 1. The Satellite Payment Problem

### 1.1 Unique Constraints

Satellite-to-satellite payments differ fundamentally from terrestrial transactions:

| Constraint | Impact |
|------------|--------|
| **Intermittent connectivity** | Satellites have ground contact windows of 5-15 minutes per 90-minute orbit |
| **Latency** | LEO-GEO-Ground round-trip: 600-800ms; multi-hop ISL: variable |
| **One-sided offline** | Executing satellite may be offline while customer's ground station is online |
| **Multi-hop chains** | Task delegation through 3+ satellites requires atomic payment guarantees |
| **Verification asymmetry** | Satellite cannot verify on-chain state; operator can verify from ground |
| **Bandwidth constraints** | Payment proofs must be compact (< 1 KB ideal) |

### 1.2 Payment Flow Requirements

```
+-----------------------------------------------------------------------------+
|                     TASK PAYMENT LIFECYCLE                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|  1. PREPAYMENT (Ground)                                                     |
|     Customer deposits BTC -> Receives eCash tokens                           |
|     Tokens uploaded to commanding satellite                                 |
|                                                                             |
|  2. TASK SUBMISSION (Space)                                                 |
|     Commanding satellite submits task + eCash tokens                        |
|     Target satellite accepts task, holds tokens in escrow                   |
|                                                                             |
|  3. EXECUTION (Space)                                                       |
|     Target executes task, generates proof-of-execution                      |
|     Signs token release                                                     |
|                                                                             |
|  4. SETTLEMENT (Ground)                                                     |
|     Tokens relayed to ground via any available path                         |
|     Target operator redeems eCash -> Lightning -> BTC                        |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 2. Bitcoin Layer 2 Technologies

### 2.1 Lightning Network

The [Lightning Network](https://lightning.network/lightning-network-paper.pdf) enables instant Bitcoin payments through payment channels and Hash Time-Locked Contracts (HTLCs).

**How HTLCs Work:**

```
+-----------------------------------------------------------------------------+
|                           HTLC PAYMENT FLOW                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Sender                    Routing Node                    Receiver         |
|    |                           |                              |             |
|    |   HTLC(hash(R), 100sat)  |                              |             |
|    | ------------------------->                              |             |
|    |                           |  HTLC(hash(R), 99sat)       |             |
|    |                           | ---------------------------->             |
|    |                           |                              |             |
|    |                           |         R (preimage)        |             |
|    |                           | <----------------------------             |
|    |         R (preimage)      |                              |             |
|    | <-------------------------                              |             |
|                                                                             |
|  Payment succeeds atomically: either all hops complete or none do           |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Satellite Limitations:**
- Both parties must be online to route payments
- Channel state must be monitored for fraud (requires watchtowers)
- Receiving payments requires active connection

**References:**
- [HTLC Technical Details](https://docs.lightning.engineering/the-lightning-network/multihop-payments/hash-time-lock-contract-htlc)
- [Voltage HTLC Explainer](https://www.voltage.cloud/blog/how-do-htlc-work-lightning-network)

### 2.2 eCash Systems

#### 2.2.1 Cashu

[Cashu](https://cashu.space/) is a Chaumian eCash protocol built for Bitcoin, creating digital bearer tokens stored on the user's device.

**Key Properties:**
- **Bearer instrument**: Tokens are stored locally, not on a server
- **Offline sending**: Wallet can create tokens without internet
- **Privacy**: Blind signatures prevent mint from linking deposits to withdrawals
- **P2PK locking**: Tokens can be locked to a recipient's public key

```json
{
  "cashu_token": {
    "mint": "https://mint.example.com",
    "proofs": [
      {
        "amount": 1000,
        "secret": "0x7a3f...",
        "C": "02abc...",
        "id": "00ffd48b"
      }
    ]
  }
}
```

**Offline Capabilities:**
> "Pretty much all Cashu wallets allow you to send tokens offline. This is because all that the wallet needs to do is look if it can create the desired amount from the proofs stored locally."
> -- [Cashu Documentation](https://docs.cashu.space/)

**P2PK Locking for Satellite Use:**
Tokens can be locked to a satellite's public key, ensuring only that satellite can redeem them:

```
Sender (ground) -> mint.lock(amount, satellite_pubkey) -> locked_token
                                                              |
Satellite receives locked_token                               |
Satellite signs redemption with private key                   |
                                                              v
                                              Only valid holder can redeem
```

**References:**
- [Cashu Bitcoin Design Guide](https://bitcoin.design/guide/how-it-works/ecash/cashu/)
- [Advancements in eCash](https://opensats.org/blog/advancements-in-ecash)

#### 2.2.2 Fedimint

[Fedimint](https://fedimint.org/) is a federated Chaumian mint with distributed custody among multiple guardians.

**Architecture:**
```
+-----------------------------------------------------------------------------+
|                        FEDIMINT FEDERATION                                   |
+-----------------------------------------------------------------------------+
|                                                                             |
|     Guardian 1          Guardian 2          Guardian 3          Guardian 4  |
|        |                    |                   |                   |       |
|        +--------------------+-------------------+-------------------+       |
|                             |                   |                           |
|                      +------+-------------------+------+                    |
|                      |    3-of-4 Multisig Custody      |                    |
|                      |    Byzantine Fault Tolerant     |                    |
|                      +----------------------------------+                   |
|                                      |                                      |
|                             eCash Token Issuance                            |
|                                      |                                      |
|                      +---------------+---------------+                      |
|                      v               v               v                      |
|                   User A          User B          User C                    |
|                 (satellite)     (satellite)     (ground)                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Advantages for Satellite Operations:**
- Federation can tolerate guardian failures (Byzantine Fault Tolerant)
- Multiple ground stations could operate as guardians
- eCash transfers are instant within the federation
- Lightning gateway enables external payments

**References:**
- [Fedimint Documentation](https://fedimint.org/)
- [Coinbase Institutional Analysis](https://www.coinbase.com/institutional/research-insights/research/market-intelligence/bitcoin-fedimints)

### 2.3 Ark Protocol

[Ark](https://ark-protocol.org/) is a Layer 2 protocol using Virtual UTXOs (vTXOs) for off-chain transactions with unilateral exit capability.

**How It Works:**
```
+-----------------------------------------------------------------------------+
|                         ARK VIRTUAL UTXO MODEL                               |
+-----------------------------------------------------------------------------+
|                                                                             |
|                    On-chain UTXO (Shared Pool)                              |
|                              |                                              |
|           +------------------+------------------+                           |
|           v                  v                  v                           |
|      +---------+        +---------+        +---------+                      |
|      | vTXO-A  |        | vTXO-B  |        | vTXO-C  |                      |
|      | 10,000  |        | 50,000  |        | 25,000  |                      |
|      |  sats   |        |  sats   |        |  sats   |                      |
|      +---------+        +---------+        +---------+                      |
|                                                                             |
|   * vTXOs expire after 4 weeks (must be refreshed or spent)                 |
|   * Payments credited every 5 seconds                                       |
|   * Users can unilaterally exit to mainchain                               |
|   * No channel liquidity management required                                |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Satellite Relevance:**
- No channel setup required (unlike Lightning)
- vTXOs can be transferred without recipient liquidity
- 4-week expiry matches typical mission planning horizons
- Ark Server (ASP) can be operated by ground infrastructure

**Limitation:** Requires ASP availability for transfers; satellite cannot transfer vTXOs while offline.

**References:**
- [Ark Protocol Specification](https://docs.arklabs.xyz/ark.pdf)
- [Ark Labs Launch Announcement](https://www.theblock.co/post/375271/ark-labs-arkade-public-beta-layer-2-bitcoin)

### 2.4 Statechains (Mercury Layer)

[Mercury Layer](https://mercurylayer.com/) enables off-chain transfer of UTXO ownership using blind co-signing.

**Statechain Transfer Model:**
```
+-----------------------------------------------------------------------------+
|                      MERCURY LAYER STATECHAIN                                |
+-----------------------------------------------------------------------------+
|                                                                             |
|  On-chain UTXO: 100,000 sats                                               |
|  Key: 2-of-2 (User + Mercury Server)                                       |
|                                                                             |
|  Transfer 1: Alice -> Bob                                                    |
|  +----------------------------------------------------------------+        |
|  | Alice's backup tx: nLocktime = 1,000,000 (far future)         |        |
|  | Bob's backup tx:   nLocktime =   999,000 (sooner)             |        |
|  | Mercury updates key share, Alice's key invalidated            |        |
|  +----------------------------------------------------------------+        |
|                                                                             |
|  Transfer 2: Bob -> Carol                                                    |
|  +----------------------------------------------------------------+        |
|  | Carol's backup tx: nLocktime = 998,000 (soonest)              |        |
|  | Carol can claim before Bob or Alice if they try to cheat      |        |
|  +----------------------------------------------------------------+        |
|                                                                             |
|  BLINDING: Mercury server never sees transaction details                    |
|                                                                             |
+-----------------------------------------------------------------------------+
```

**Advantages:**
- Full UTXO transferred (no channel fragmentation)
- No receiving liquidity required
- Privacy through blind signing
- Instant transfers

**Satellite Consideration:** Decrementing timelocks mean statechains must eventually be closed on-chain. For long-duration missions, this creates operational complexity.

**References:**
- [Mercury Layer Technical Details](https://bitcoinmagazine.com/technical/mercury-layer-a-massive-improvement-on-statechains)
- [Mercury Documentation](https://docs.mercurywallet.com/docs/)

### 2.5 Lightspark and Spark Protocol

[Lightspark](https://www.lightspark.com/) provides enterprise Lightning infrastructure, and in October 2024 launched the [Spark protocol](https://www.lightspark.com/news/lightspark/introducing-spark) as a Lightning-compatible Layer 2.

**Key Features:**
- Remote key signing (keys held separately from node infrastructure)
- Predictive routing for transaction success
- Multi-asset support (stablecoins planned)
- Wallet-as-a-service

**Enterprise Adoption:**
> "15% of Bitcoin transactions on Coinbase now move over Lightning Network, powered by Lightspark"
> -- [Lightspark Announcement, 2024](https://www.lightspark.com/news/lightspark/coinbase-lightning-network-lightspark)

**References:**
- [Lightspark Platform](https://www.lightspark.com/)
- [Spark Protocol Introduction](https://www.lightspark.com/news/lightspark/introducing-spark)

### 2.6 Point Time-Locked Contracts (PTLCs)

[PTLCs](https://bitcoinops.org/en/topics/ptlc/) are a proposed upgrade to HTLCs offering improved privacy and new capabilities.

**Improvements Over HTLCs:**

| Feature | HTLC | PTLC |
|---------|------|------|
| Locking mechanism | Hash preimage | Schnorr signature adaptor |
| Path correlation | Same hash across route | Unique points per hop |
| On-chain footprint | Hash + preimage revealed | Indistinguishable from normal tx |
| Stuckless payments | Not supported | Supported |
| Oracle integration | Limited | Native support |

**Relevance to Satellite Payments:**
PTLCs enable payments that depend on external data (oracles), such as:
- Proof that imaging was completed (data hash)
- Confirmation of orbital maneuver (telemetry signature)
- Timestamp verification (on-board clock attestation)

**Status:** Enabled by Taproot (2021), but network-wide adoption pending.

**References:**
- [Bitcoin Optech PTLC Topic](https://bitcoinops.org/en/topics/ptlc/)
- [River PTLC Glossary](https://river.com/learn/terms/p/point-timelocked-contract-ptlc/)

---

## 3. Proposed Satellite Payment Architecture

### 3.1 Design Principles

1. **Prepaid Operation**: Satellites carry eCash tokens as "spending balance"
2. **Offline Payment**: Satellites can pay without ground verification
3. **Deferred Verification**: Operators verify payments during ground contacts
4. **Atomic Task-Payment Binding**: Payment is cryptographically bound to task execution
5. **Multi-hop Support**: Payment chains follow task delegation chains

### 3.2 System Architecture

```
+-----------------------------------------------------------------------------+
|                    SATELLITE PAYMENT SYSTEM ARCHITECTURE                     |
+-----------------------------------------------------------------------------+
|                                                                             |
|  GROUND LAYER                                                               |
|  =======================================================================   |
|                                                                             |
|  +-----------------+    +-----------------+    +-----------------+         |
|  |   Customer      |    |  Satellite Mint |    |   Operator      |         |
|  |   Wallet        |    |  Federation     |    |   Settlement    |         |
|  |                 |    |                 |    |                 |         |
|  |  * BTC deposit  |--->|  * eCash issue  |    |  * Redemption   |         |
|  |  * Task submit  |    |  * LN gateway   |<---|  * Accounting   |         |
|  |  * Token lock   |    |  * Multi-sig    |    |  * Verification |         |
|  +-----------------+    +-----------------+    +-----------------+         |
|           |                      |                      ^                   |
|           |              Token Issuance                 |                   |
|           |                      |                 Settlement               |
|           v                      v                      |                   |
|  =======================================================================   |
|  SPACE LAYER                                                                |
|  =======================================================================   |
|                                                                             |
|  +-----------------+              +-----------------+                       |
|  |  Commanding     |   Task +     |   Target        |                       |
|  |  Satellite      |   Tokens     |   Satellite     |                       |
|  |                 |------------->|                 |                       |
|  |  Token Store:   |              |  Escrow Store:  |                       |
|  |  +-----------+  |              |  +-----------+  |                       |
|  |  | Cashu     |  |              |  | P2PK      |  |                       |
|  |  | Tokens    |  |              |  | Locked    |  |                       |
|  |  | 500,000   |  |   Proof +    |  | Tokens    |  |                       |
|  |  | sats      |  |<-------------|  |           |  |                       |
|  |  +-----------+  |   Receipt    |  +-----------+  |                       |
|  +-----------------+              +-----------------+                       |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 3.3 Component Specifications

#### 3.3.1 Satellite Mint Federation

A Fedimint deployment operated by satellite operators and trusted third parties:

```json
{
  "federation_config": {
    "name": "SatPay Federation",
    "threshold": 3,
    "guardians": [
      {
        "id": "GUARDIAN-ESA",
        "operator": "European Space Agency",
        "ground_station": "ESOC Darmstadt"
      },
      {
        "id": "GUARDIAN-NASA",
        "operator": "NASA",
        "ground_station": "JPL Pasadena"
      },
      {
        "id": "GUARDIAN-JAXA",
        "operator": "JAXA",
        "ground_station": "Sagamihara"
      },
      {
        "id": "GUARDIAN-COMMERCIAL",
        "operator": "Space Data Association",
        "ground_station": "AWS Ground Station"
      }
    ],
    "lightning_gateway": {
      "node_pubkey": "03abc...",
      "min_confirmations": 3
    },
    "token_denominations_sats": [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024,
                                  2048, 4096, 8192, 16384, 32768, 65536]
  }
}
```

#### 3.3.2 Satellite Token Store

On-board storage for eCash tokens with spending authorization:

```python
class SatelliteTokenStore:
    """
    Secure on-board storage for eCash tokens.
    Tokens are pre-loaded during ground contacts.
    """

    def __init__(self, satellite_keypair, mint_pubkeys):
        self.keypair = satellite_keypair
        self.mint_pubkeys = mint_pubkeys  # Trusted mint public keys
        self.tokens = []  # Cashu token proofs
        self.spending_limit_sats = 0
        self.spent_secrets = set()  # Prevent double-spend tracking

    def load_tokens(self, tokens: list, spending_limit: int):
        """Load tokens during ground contact."""
        for token in tokens:
            if self.verify_mint_signature(token):
                self.tokens.append(token)
        self.spending_limit_sats = spending_limit

    def create_payment(self, amount_sats: int, recipient_pubkey: str) -> dict:
        """
        Create a P2PK-locked payment for a task.
        Can be done offline - no mint contact required.
        """
        if amount_sats > self.spending_limit_sats:
            raise InsufficientAuthorization()

        # Select tokens to cover amount
        selected = self.select_tokens(amount_sats)

        # Create P2PK lock to recipient
        locked_tokens = []
        for token in selected:
            locked = {
                "amount": token["amount"],
                "secret": token["secret"],
                "C": token["C"],
                "p2pk": {
                    "pubkey": recipient_pubkey,
                    "locktime": None,  # No expiry
                    "refund_pubkey": self.keypair.pubkey  # Refund if task fails
                }
            }
            locked_tokens.append(locked)
            self.spent_secrets.add(token["secret"])

        self.spending_limit_sats -= amount_sats
        return {"tokens": locked_tokens, "amount": amount_sats}

    def verify_mint_signature(self, token) -> bool:
        """Verify token was signed by trusted mint."""
        # Blind signature verification
        return verify_dleq_proof(token, self.mint_pubkeys)
```

#### 3.3.3 Task-Payment Binding

Cryptographic binding between capability tokens and payment:

```json
{
  "task_payment_bundle": {
    "capability_token": {
      "header": {"alg": "ES256K", "typ": "SAT-CAP"},
      "payload": {
        "iss": "ESA-COPERNICUS",
        "sub": "STARLINK-RELAY",
        "aud": "SENTINEL-2C-60989",
        "cap": ["cmd:imaging:msi"],
        "jti": "task-2025-001"
      },
      "signature": "ECDSA_SIG..."
    },
    "payment": {
      "mint": "https://satpay.federation.space",
      "tokens": [
        {
          "amount": 10000,
          "secret": "0x7a3f...",
          "C": "02abc...",
          "p2pk": {
            "pubkey": "SENTINEL-2C-PAYMENT-PUBKEY",
            "refund_pubkey": "CUSTOMER-REFUND-PUBKEY"
          }
        }
      ],
      "task_binding": {
        "task_jti": "task-2025-001",
        "payment_hash": "sha256(tokens)",
        "execution_conditions": {
          "data_hash_required": true,
          "min_coverage_km2": 1000
        }
      }
    },
    "combined_signature": "ECDSA_SIG_BINDING_BOTH"
  }
}
```

### 3.4 Payment Flows

#### 3.4.1 Single-Hop Payment

```
+-----------------------------------------------------------------------------+
|                      SINGLE-HOP TASK PAYMENT                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|  PHASE 1: PREPAYMENT (Ground, T-24h)                                        |
|  ------------------------------------                                       |
|  Customer                    Mint Federation                                |
|     |                              |                                        |
|     |--- Deposit 100,000 sats ---->|                                        |
|     |                              |                                        |
|     |<-- eCash tokens (P2PK) ------|                                        |
|     |    locked to Starlink-7823   |                                        |
|     |                              |                                        |
|  Customer uploads tokens to Starlink-7823 via ground station                |
|                                                                             |
|  PHASE 2: TASK SUBMISSION (Space, T+0)                                      |
|  -------------------------------------                                      |
|  Starlink-7823                 Sentinel-2C                                  |
|     |                              |                                        |
|     |--- Capability Token -------->|                                        |
|     |--- P2PK Locked Tokens ------>| (10,000 sats for this task)            |
|     |    (locked to Sentinel-2C)   |                                        |
|     |                              |                                        |
|     |                              |-- Verify cap token signature           |
|     |                              |-- Verify P2PK lock to self             |
|     |                              |-- Store in escrow                      |
|     |                              |                                        |
|     |<-- Task Accepted ------------|                                        |
|                                                                             |
|  PHASE 3: EXECUTION (Space, T+30min)                                        |
|  -----------------------------------                                        |
|  Sentinel-2C                                                                |
|     |                                                                       |
|     |-- Execute imaging task                                                |
|     |-- Generate proof-of-execution:                                        |
|     |   * Data hash                                                         |
|     |   * Timestamp                                                         |
|     |   * Coverage metadata                                                 |
|     |                                                                       |
|     |-- Sign token release with Sentinel-2C key                             |
|     |                                                                       |
|                                                                             |
|  PHASE 4: SETTLEMENT (Ground, T+2h)                                         |
|  ----------------------------------                                         |
|  Sentinel-2C Operator          Mint Federation         Bitcoin Network      |
|     |                              |                         |              |
|     |--- Redeem P2PK tokens ------>|                         |              |
|     |    (signed by Sentinel-2C)   |                         |              |
|     |                              |                         |              |
|     |                              |--- Lightning payment -->|              |
|     |                              |    (or on-chain)        |              |
|     |                              |                         |              |
|     |<-- Settlement confirmed -----|                         |              |
|                                                                             |
+-----------------------------------------------------------------------------+
```

#### 3.4.2 Multi-Hop Payment Chain

For delegated tasks through multiple satellites:

```
+-----------------------------------------------------------------------------+
|                     MULTI-HOP DELEGATION PAYMENT                             |
+-----------------------------------------------------------------------------+
|                                                                             |
|  Customer -> Iridium-168 -> Iridium-172 -> Sentinel-2C                         |
|                                                                             |
|  Payment Structure:                                                         |
|  +-----------------------------------------------------------------+       |
|  |  Total task payment: 15,000 sats                                |       |
|  |                                                                 |       |
|  |  Token 1: 2,000 sats  | P2PK: Iridium-168  | Relay fee        |       |
|  |  Token 2: 2,000 sats  | P2PK: Iridium-172  | Relay fee        |       |
|  |  Token 3: 11,000 sats | P2PK: Sentinel-2C  | Execution fee    |       |
|  +-----------------------------------------------------------------+       |
|                                                                             |
|  Flow:                                                                      |
|                                                                             |
|  Customer (Ground)                                                          |
|     |                                                                       |
|     |-- Upload all 3 tokens to Iridium-168                                  |
|     |                                                                       |
|  Iridium-168 (Space)                                                        |
|     |                                                                       |
|     |-- Keep Token 1 (P2PK to self) (yes)                                       |
|     |-- Forward Token 2 + Token 3 to Iridium-172                            |
|     |                                                                       |
|  Iridium-172 (Space)                                                        |
|     |                                                                       |
|     |-- Keep Token 2 (P2PK to self) (yes)                                       |
|     |-- Forward Token 3 to Sentinel-2C with task                            |
|     |                                                                       |
|  Sentinel-2C (Space)                                                        |
|     |                                                                       |
|     |-- Verify Token 3 P2PK lock to self (yes)                                  |
|     |-- Execute task                                                        |
|     |-- Sign proof-of-execution                                             |
|                                                                             |
|  Settlement (Ground) - Each operator redeems independently                  |
|                                                                             |
+-----------------------------------------------------------------------------+
```

### 3.5 Escrow and Dispute Resolution

#### 3.5.1 Time-Locked Refunds

Tokens include refund conditions if task execution fails:

```json
{
  "p2pk_token": {
    "amount": 10000,
    "secret": "0x7a3f...",
    "C": "02abc...",
    "p2pk": {
      "pubkey": "SENTINEL-2C-PUBKEY",
      "conditions": {
        "execution_proof_required": true,
        "proof_schema": "imaging_v1",
        "timeout_unix": 1705420800,
        "refund": {
          "pubkey": "CUSTOMER-REFUND-PUBKEY",
          "after_timeout": true
        }
      }
    }
  }
}
```

**Resolution Logic:**

```python
def resolve_payment(token, proof, current_time):
    """
    Resolve payment based on execution proof or timeout.
    """
    if proof and verify_execution_proof(proof, token.conditions.proof_schema):
        # Task completed - release to executor
        return Release(to=token.p2pk.pubkey)

    elif current_time > token.p2pk.conditions.timeout_unix:
        # Timeout - refund to customer
        return Release(to=token.p2pk.conditions.refund.pubkey)

    else:
        # Still pending
        return Pending()
```

#### 3.5.2 Proof-of-Execution Requirements

| Task Type | Proof Requirements |
|-----------|-------------------|
| **Imaging** | Data hash, coverage polygon, acquisition timestamp |
| **SAR** | Data hash, incidence angle, polarization mode |
| **Relay** | Forwarded message hash, routing path, delivery timestamp |
| **RPO** | Relative position log, sensor data hash, maneuver record |
| **Data Processing** | Input hash, output hash, algorithm version |

---

## 4. Implementation Considerations

### 4.1 On-Board Cryptographic Requirements

Satellites require hardware support for:

| Operation | Algorithm | Purpose |
|-----------|-----------|---------|
| Token verification | DLEQ proofs | Verify mint signatures |
| P2PK spending | secp256k1 ECDSA | Sign token redemption |
| Capability tokens | ES256K (secp256k1) | Verify task authorization |
| Proof generation | SHA-256 | Create execution proofs |

**Storage Requirements:**
- Token store: ~100 KB for 1,000 tokens
- Spent secret cache: ~32 KB for 1,000 entries
- Mint public keys: ~1 KB

### 4.2 Double-Spend Prevention

**Risk:** Satellite could attempt to spend same tokens twice during offline periods.

**Mitigations:**

1. **On-board spent tracking**: Satellites maintain local spent-secret set
2. **Epoch-based tokens**: Tokens valid only within time epochs
3. **Ground reconciliation**: Operator verifies against mint during contacts
4. **Reputation staking**: Operators stake BTC as fraud bond

```python
class DoubleSpendPrevention:
    def __init__(self):
        self.spent_secrets = BloomFilter(capacity=10000, error_rate=0.001)
        self.epoch_start = current_epoch()

    def check_and_mark(self, secret: bytes) -> bool:
        """Check if secret was spent, mark as spent."""
        if secret in self.spent_secrets:
            return False  # Already spent

        self.spent_secrets.add(secret)
        return True

    def epoch_rollover(self, new_epoch: int):
        """Clear spent tracking on epoch boundary."""
        if new_epoch > self.epoch_start:
            self.spent_secrets = BloomFilter(capacity=10000, error_rate=0.001)
            self.epoch_start = new_epoch
```

### 4.3 Bandwidth Optimization

**Compact Token Format:**

```
Standard Cashu Token: ~200 bytes per proof
Optimized Satellite Token: ~80 bytes per proof

Optimizations:
+-- Use 4-byte mint ID instead of URL
+-- Use CBOR encoding instead of JSON
+-- Compress point encoding (33 -> 32 bytes)
+-- Batch multiple tokens with shared metadata
```

**Example Compact Encoding:**

```
+----------------------------------------------------------------+
| Byte 0-3:   Mint ID (4 bytes)                                  |
| Byte 4:     Token count (1 byte)                               |
| Byte 5-8:   Epoch (4 bytes)                                    |
| Per token (75 bytes each):                                     |
|   Byte 0-1:   Amount (2 bytes, log2 denomination index)        |
|   Byte 2-33:  Secret (32 bytes)                                |
|   Byte 34-65: C point (32 bytes, x-only)                       |
|   Byte 66-74: DLEQ proof (9 bytes, compressed)                 |
+----------------------------------------------------------------+

1000 sats payment: ~80 bytes (vs 200+ bytes standard)
```

### 4.4 Integration with Capability Tokens

The payment system integrates with the capability token framework from Section 11 of CNC_PROTOCOLS.md:

```json
{
  "capability_token_with_payment": {
    "header": {"alg": "ES256K", "typ": "SAT-CAP-PAY"},
    "payload": {
      "iss": "ESA-COPERNICUS",
      "sub": "CUSTOMER-WALLET",
      "aud": "SENTINEL-2C-60989",
      "iat": 1705320000,
      "exp": 1705406400,
      "jti": "imaging-task-2025-001",
      "cap": [
        "cmd:imaging:msi:all_bands",
        "cmd:downlink:starlink"
      ],
      "cns": {
        "max_area_km2": 10000,
        "geographic_bounds": {"lat_min": -60, "lat_max": 60}
      },
      "pay": {
        "mint_id": "0x00000001",
        "amount_sats": 10000,
        "token_hash": "sha256(cashu_tokens)",
        "escrow_timeout_hours": 24
      }
    },
    "signature": "ECDSA_SIG..."
  }
}
```

### 4.5 Failure Modes and Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Token loss (OBC failure) | Missing token inventory on reboot | Re-issue from ground |
| Double-spend attempt | Mint rejection on redemption | Flag satellite, use backup tokens |
| Task execution failure | Missing proof after timeout | Automatic refund via timeout |
| Mint unavailable | Settlement timeout | Use backup Lightning channel |
| Communication loss | No ground contact | Tokens remain valid; settle later |

---

## 5. Security Analysis

### 5.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| **Rogue satellite spends tokens without execution** | P2PK locks require target signature; proof-of-execution required |
| **Customer double-deposits same BTC** | Mint verifies on-chain confirmation before issuing tokens |
| **Mint collusion** | Federation requires threshold signatures; multiple operators |
| **Token theft via ISL interception** | P2PK locks to specific recipients; useless to interceptor |
| **Replay of old task+payment** | Task JTI and token secrets are single-use |
| **Operator fraud (claims payment without data)** | Proof-of-execution hash must match delivered data |

### 5.2 Trust Assumptions

1. **Mint Federation**: Majority of guardians are honest
2. **On-board crypto**: HSM protects satellite private keys
3. **Time synchronization**: Satellites have accurate clocks for timeouts
4. **Proof verification**: Ground systems can verify execution proofs

### 5.3 Privacy Considerations

- **Customer privacy**: Blind signatures hide deposit-withdrawal links
- **Satellite privacy**: Task payments not visible on-chain
- **Operator privacy**: Settlement batching obscures individual task payments

---

## 6. Comparison of Approaches

| Feature | Lightning | Cashu | Fedimint | Ark | Mercury |
|---------|-----------|-------|----------|-----|---------|
| **Offline sending** | No | Yes | Yes | No | No |
| **Offline receiving** | No | P2PK | P2PK | No | No |
| **Instant finality** | Yes | Yes (trusted) | Yes (trusted) | Yes | Yes |
| **Trust model** | Trustless | Single mint | Federation | ASP | Coordinator |
| **Setup cost** | Channel open | None | None | None | None |
| **Liquidity mgmt** | Required | None | None | None | None |
| **On-chain footprint** | Channel open/close | Deposit/withdraw | Deposit/withdraw | Pool refresh | Close only |
| **Privacy** | Limited | Excellent | Excellent | Good | Excellent |
| **Satellite fit** | Medium | Excellent | Excellent | Good | Good |

### Recommended Hybrid Architecture

```
PRIMARY:   Cashu/Fedimint eCash tokens for offline operation
BACKUP:    Dedicated Lightning channels per operator for settlement
FALLBACK:  On-chain BTC for high-value settlements
```

---

## 7. Future Enhancements

### 7.1 PTLC Integration

When Lightning Network adopts PTLCs:

```
Current: H = hash(preimage)     ->  Reveal preimage to claim
Future:  P = point(adaptor)     ->  Reveal adaptor signature to claim

Benefits for satellites:
+-- Execution proof can BE the adaptor signature
+-- Payment automatically releases when proof provided
+-- No separate proof verification step
+-- Native oracle support for external data
```

### 7.2 Ark Virtual UTXOs for Constellations

Large constellation operators could run Ark Servers:

```
Starlink Ark Server
+-- All Starlink satellites share VTXO pool
+-- Inter-satellite payments: instant, free
+-- External payments: via Lightning gateway
+-- vTXO refresh: batched during ground contacts
```

### 7.3 Cross-Federation Atomic Swaps

Multiple mint federations could enable cross-operator payments:

```
ESA Federation <----- Atomic Swap -----> NASA Federation
     |                                        |
     +-- Sentinel satellites                  +-- TDRSS satellites
```

---

## 8. Implementation Roadmap

### Phase 1: Foundation (Months 1-3)
- [ ] Deploy Fedimint federation with 4 guardians
- [ ] Implement satellite token store (simulation)
- [ ] Define compact token encoding specification
- [ ] Create proof-of-execution schemas

### Phase 2: Integration (Months 4-6)
- [ ] Integrate payment into capability token format
- [ ] Implement P2PK locking for satellite pubkeys
- [ ] Build ground settlement service
- [ ] Test multi-hop payment chains

### Phase 3: Deployment (Months 7-9)
- [ ] Flight software integration
- [ ] Security audit
- [ ] Pilot with test satellites
- [ ] Documentation and operator training

### Phase 4: Operations (Months 10-12)
- [ ] Production deployment
- [ ] Monitor and optimize
- [ ] Add additional mints/federations
- [ ] Implement PTLC upgrade path

---

## 9. References

### Lightning Network
- [Lightning Network Paper](https://lightning.network/lightning-network-paper.pdf)
- [HTLC Technical Guide](https://docs.lightning.engineering/the-lightning-network/multihop-payments/hash-time-lock-contract-htlc)
- [Voltage HTLC Explainer](https://www.voltage.cloud/blog/how-do-htlc-work-lightning-network)

### eCash Systems
- [Cashu Protocol](https://cashu.space/)
- [Cashu Documentation](https://docs.cashu.space/)
- [Bitcoin Design Guide - Cashu](https://bitcoin.design/guide/how-it-works/ecash/cashu/)
- [Fedimint](https://fedimint.org/)
- [Fedimint Bitcoin Design Guide](https://bitcoin.design/guide/how-it-works/ecash/fedimint/)
- [OpenSats eCash Advancements](https://opensats.org/blog/advancements-in-ecash)

### Layer 2 Protocols
- [Ark Protocol](https://ark-protocol.org/)
- [Ark Technical Paper](https://docs.arklabs.xyz/ark.pdf)
- [Mercury Layer](https://mercurylayer.com/)
- [Mercury Layer Analysis](https://bitcoinmagazine.com/technical/mercury-layer-a-massive-improvement-on-statechains)

### Enterprise Solutions
- [Lightspark Platform](https://www.lightspark.com/)
- [Spark Protocol](https://www.lightspark.com/news/lightspark/introducing-spark)

### PTLCs
- [Bitcoin Optech - PTLCs](https://bitcoinops.org/en/topics/ptlc/)
- [River Glossary - PTLC](https://river.com/learn/terms/p/point-timelocked-contract-ptlc/)

### Machine-to-Machine Payments
- [M2M Cryptocurrency Payments](https://www.sheepy.com/blog/the-future-of-transactions-cryptocurrencies-and-automated-machine-to-machine-m2m-payments)
- [IoT and Cryptocurrency Integration](https://mapmetrics.org/blog/iot-and-cryptocurrency-a-new-era-of-integration/)

---

## 10. Glossary

| Term | Definition |
|------|------------|
| **Bearer token** | Digital token where possession equals ownership |
| **Blind signature** | Cryptographic signature where signer doesn't see message content |
| **CBBA** | Consensus-Based Bundle Algorithm for distributed task allocation |
| **Chaumian eCash** | Digital cash system using blind signatures (David Chaum, 1982) |
| **DLEQ proof** | Discrete Log Equality proof for verifying blind signatures |
| **eCash** | Electronic cash using cryptographic bearer tokens |
| **Federation** | Group of guardians jointly managing a mint |
| **Guardian** | Federation member holding key share |
| **HTLC** | Hash Time-Locked Contract |
| **ISL** | Inter-Satellite Link |
| **Mint** | Service that issues and redeems eCash tokens |
| **P2PK** | Pay-to-Public-Key lock on eCash tokens |
| **PTLC** | Point Time-Locked Contract |
| **Statechain** | Off-chain UTXO ownership transfer protocol |
| **vTXO** | Virtual UTXO in Ark protocol |

