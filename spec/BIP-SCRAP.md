```
BIP: TBD
Layer: Applications
Title: Secure Capabilities and Routed Authorization Protocol (SCRAP)
Author: Bob McElrath <bob.mcelrath@gmail.com>
Status: Draft
Type: Informational
Created: 2026-01-09
License: CC0-1.0
Requires: 118 (ANYPREVOUT), 340 (Schnorr), 341 (Taproot)
```

## Abstract

This document describes SCRAP (Secure Capabilities and Routed Authorization
Protocol), an application protocol for trustless payments between
intermittently-connected autonomous agents. SCRAP demonstrates compelling use
cases for ANYPREVOUT (BIP-118) and Point Time-Locked Contracts (PTLCs) that
cannot be served by current Lightning Network primitives.

The core problem SCRAP addresses is: **trustless payments between autonomous
agents that cannot maintain persistent connections**. This includes satellites
with orbital contact windows, autonomous vehicles, drone networks, IoT mesh
devices, AI agents, and remote infrastructure. These applications require:
(1) atomic binding of payment to task completion proofs, (2) channel updates
without real-time peer connectivity, and (3) settlement without
watchtower-enforced punishment transactions.

These requirements cannot be met without ANYPREVOUT. This BIP documents
applications that motivate BIP-118 activation.

## Copyright

This document is licensed under the Creative Commons CC0 1.0 Universal license.

## Motivation

### The Intermittent Connectivity Problem

A growing class of autonomous systems requires trustless payment mechanisms but
cannot maintain persistent network connections:

**Satellite Constellations**: Commercial satellites require payments for
inter-satellite services (data relay, imaging, processing). Inter-satellite
links (ISL) have 2-15 minute contact windows during orbital passes. Ground
contact may be hours apart for LEO satellites.

**Autonomous Vehicles**: EVs paying charging stations, vehicles selling sensor
data to nearby vehicles, automated toll payments. Vehicles move between
coverage areas and cannot guarantee connectivity.

**Drone Networks**: Drones selling aerial imagery, multi-hop relay through
drone mesh networks. Flight paths create intermittent connectivity.

**IoT Mesh Networks**: Smart devices ordering supplies, sensor networks selling
data streams, bandwidth sharing between neighbors. Low-power devices sleep
between transmissions.

**AI Agent Economies**: AI agents paying for compute, API calls, and data.
Multi-agent task chains where Agent A delegates to B delegates to C. Agents
may be ephemeral or rate-limited.

**Remote Infrastructure**: Mining equipment, weather stations, undersea
sensors. Satellite uplink may be the only connectivity, with limited bandwidth
and high latency.

**Disaster Response**: Ad-hoc mesh networks after infrastructure failure.
Emergency responders coordinating across agencies with different authorization
systems. Pre-authorized capability tokens enable cross-organization task
execution without real-time coordination with central authorities.

Current Lightning Network architecture assumes persistent peer connectivity,
which is incompatible with these deployment scenarios.

### Three Fundamental Problems

**Problem 1: Payment-Proof Atomicity**

With HTLCs, the payment preimage is independent of task completion. An executor
could reveal a preimage without completing the task, or complete the task
without receiving payment. Separate attestation mechanisms add complexity and
trust assumptions.

With PTLCs, the adaptor signature that unlocks payment IS the acknowledgment
signature proving task completion. Payment and proof are cryptographically
atomic -- one cannot exist without the other.

**Problem 2: Offline Channel Updates**

Current Lightning channels use revocation-based state machines. If a peer
broadcasts an old state, the counterparty must respond within a timelock window
or lose funds. This requires watchtowers with access to private revocation keys
-- impractical for satellites with intermittent ground contact, or IoT devices
that sleep for hours.

ln-symmetry (eltoo) channels use symmetric state where either party can always
spend the latest state. No toxic waste, no punishment transactions, no
watchtower key custody. Agents can exchange state updates via any communication
path and settle when convenient.

Note: ln-symmetry still requires monitoring for old state broadcasts and
responding with the latest state. The difference is that monitors do not
need revocation keys -- they only need the latest signed state, which can be
shared without compromising security.

**Problem 3: Multi-Hop Atomicity**

Lightning multi-hop payments require all nodes in the path to be online
simultaneously to propagate preimage revelation. Store-and-forward breaks this
atomicity.

SCRAP uses a different model: payments are pre-signed and locked to a single
adaptor point derived from the final acknowledgment. All intermediate hops
claim payment with the same adaptor secret, which is only revealed when the
final recipient acknowledges delivery.

The adaptor secret (32 bytes) propagates backward via reliable ground networks
(for satellites) or internet backbone (for terrestrial applications), rather
than through the intermittent agent network. Ground infrastructure has 99.9%+
uptime and sub-second latency, compared to ISL windows of 2-15 minutes that
may not align for hours.

### Why This Requires ANYPREVOUT

ANYPREVOUT (BIP-118) enables signatures that commit only to output scripts,
not specific transaction IDs. This is essential for ln-symmetry:

1. **State rebinding**: Update transactions can spend any prior state without
   knowing which state will be broadcast
2. **No revocation keys**: Latest state is always valid, eliminating toxic waste
3. **Simplified backup**: Only need to store most recent state
4. **Offline catch-up**: Peers exchange latest state, always valid

Without ANYPREVOUT, autonomous agent payment channels would require:
- Watchtower custody of revocation keys (security risk for remote devices)
- Real-time punishment transaction broadcast (connectivity impossible)
- Full state history backup (storage prohibitive for constrained devices)

SCRAP joins other applications motivating ANYPREVOUT:
- Watchtower-free mobile Lightning wallets
- Channel factories with reduced on-chain footprint
- Vault constructions for cold storage security
- Spacechains (currently prototyped on signet)

### Why This Requires PTLCs

PTLCs enable adaptor signatures where payment claim reveals a discrete logarithm.
For autonomous agent payments:

1. **Task-payment binding**: Adaptor secret = acknowledgment signature
2. **Privacy**: Uncorrelated adaptor points across hops (unlike hash-correlated HTLCs)
3. **Efficiency**: Taproot keyspend vs HTLC script reveal

For complex tasks requiring multi-party acknowledgment (e.g., imaging satellite
and processing satellite must both attest), MuSig2 (BIP-327) can aggregate
signatures. This is an optional extension; the base protocol uses single-signer
Schnorr acknowledgments.

### Current Implementation Status

As of January 2026:

**ln-symmetry**: Research-level implementation by Greg Sanders (instagibbs) at
Blockstream, documented in the [LN-Symmetry Project Recap][ln-recap]. Tested on
signet via Bitcoin Inquisition. Features proven include ephemeral anchors, v3
transactions, simplified state machine, and fast-forwards.

**BIP-118**: Specification complete. Implementation available in [Bitcoin
Inquisition][inquisition] for signet testing. Spacechain prototype working on
signet. No confirmed mainnet activation timeline.

**PTLCs**: Proof of concept by [Suredbits][suredbits-ptlc] based on Eclair
using ECDSA adaptor signatures. New Lightning messages (update_add_ptlc,
commitment_signed_ptlc) defined. Active developer discussion on variations.

[ln-recap]: https://delvingbitcoin.org/t/ln-symmetry-project-recap/359
[inquisition]: https://github.com/bitcoin-inquisition/bitcoin/releases
[suredbits-ptlc]: https://suredbits.com/ptlc-proof-of-concept/

## Specification

The full SCRAP protocol is specified in the companion document [SCRAP.md](SCRAP.md).
This BIP provides a summary of the protocol architecture and its dependency on
ANYPREVOUT.

### Protocol Overview

SCRAP consists of three components:

1. **Capability Tokens**: Signed authorization tokens granting specific task
   permissions. Issued by operators, verified by agents. Design follows
   [UCAN][ucan] (User-Controlled Authorization Networks) principles:
   delegation chains, attenuation (narrowing permissions), and bearer
   semantics (possession implies authorization).

2. **PTLC Payment Chains**: Pre-signed transactions locked to a common adaptor
   point. All hops claim with the same adaptor secret.

3. **ln-symmetry Channels**: State updates for ongoing relationships between
   agents or agent-gateway pairs.

[ucan]: https://ucan.xyz/

### Capability Token Structure

Capability tokens authorize specific actions and can be delegated with
attenuation (narrowing of permissions). Tokens are encoded using TLV
(Type-Length-Value) format following Lightning Network conventions (BOLT 1):

```
CapabilityToken (TLV encoding):
  Type 0:   version (1 byte)          # Protocol version
  Type 2:   issuer (33 bytes)         # Target's operator pubkey (signer)
  Type 4:   subject (variable)        # Commander (who may use this token)
  Type 6:   audience (variable)       # Target satellite (who executes)
  Type 8:   issued_at (4 bytes)       # Unix timestamp (uint32 big-endian)
  Type 10:  expires_at (4 bytes)      # Unix timestamp (uint32 big-endian)
  Type 12:  token_id (16 bytes)       # Random bytes for replay protection
  Type 14:  capability (variable)     # Capability string [MAY repeat]
  Type 20:  root_issuer (33 bytes)    # Target's operator (for delegation chains)
  Type 22:  root_token_id (16 bytes)  # Root token's token_id
  Type 24:  parent_token_id (16 bytes) # Parent's token_id
  Type 26:  chain_depth (1 byte)      # Delegation depth (root=0)
  Type 240: signature (64 bytes)      # BIP-340 Schnorr signature (MUST be last)
```

**Encoding rules**: Records MUST appear in ascending type order. Unknown even
types MUST cause rejection; unknown odd types MUST be ignored (forward
compatibility). Signature covers all TLV records except type 240.

**Version field**: The version field enables protocol evolution. Verifiers MUST
reject tokens with unrecognized versions. Version 1 is specified in this
document.

**Delegation**: When delegating, the delegator's pubkey becomes the issuer, and
types 20-26 reference the parent token. Verifiers check the full chain back to
a trusted root. Each delegation may only attenuate (narrow) capabilities.

### Adaptor Signature Construction

SCRAP uses the standard adaptor signature construction secure under the
One-More Discrete Logarithm (OMDL) assumption, as formalized in peer-reviewed
literature:

- Aumayr et al., "Generalized Channels from Limited Blockchain Access",
  ACM CCS 2021
- Malavolta et al., "Anonymous Multi-Hop Locks for Blockchain Scalability
  and Interoperability", CRYPTO 2019

For a task chain `[B -> C -> D]` terminating at an operator's ground station:

1. Last operator commits to nonce `R_last` for acknowledgment signature
2. Gateway computes adaptor point `T` where completing the signature reveals `t`
3. All PTLC outputs locked to same adaptor point `T`
4. On valid delivery, last operator signs acknowledgment with nonce `R_last`
5. Publishing this signature reveals adaptor secret `t`
6. All parties extract `t` and claim their PTLC outputs

**Security**: The last operator only receives payment if they reveal the adaptor
secret. Since all payments in the chain are locked to the same adaptor point,
revealing `t` enables all participants to claim. The last operator cannot
selectively pay -- either everyone gets paid or no one does.

### Relay Task Proofs

For relay tasks (forwarding data without transformation), the proof of delivery
is the next hop's acknowledgment:

- Task: "Relay packet P to agent C"
- Proof: Signature from C over `SHA256(P)`
- If C never received P, no signature exists, and the PTLC times out

This creates a chain of accountability: each hop proves delivery by obtaining
the next hop's signature. The final hop proves delivery to the receiving
ground station or gateway.

### Replay Protection

Capability tokens include unique identifiers (`token_id`, 16 random bytes) that
must not be reused. Verification MUST proceed in this order:

```
1. Reject if exp < now                              (token expired)
2. Reject if exp > now + MAX_TOKEN_LIFETIME         (expiration too far future)
3. Reject if iat > now                              (issued in future)
4. Reject if token_id in used_token_cache           (replay attempt)
5. Add (token_id, exp) to used_token_cache          (record usage)
6. Periodically evict entries where exp < now       (remove expired only)
```

**Critical**: Only evict expired entries from the cache. Never evict entries
for tokens that have not yet expired. This bounds cache size to:

```
max_cache_size = MAX_TOKEN_LIFETIME * max_tokens_per_second
```

With `MAX_TOKEN_LIFETIME = 7 days` and 1 token/second, cache holds approximately
600K entries. Constrained devices may use shorter token lifetimes.

### Fund Lockup

Operators should understand the capital lockup implications of multi-hop
payment chains:

```
Lockup duration = (per_hop_timeout * num_hops) + dispute_window
```

For example, with 24-hour per-hop timeouts, a 3-hop chain, and 6-hour dispute
window: `(24 * 3) + 6 = 78 hours` worst-case lockup.

```
Opportunity cost = (lockup_hours / 8760) * annual_rate * locked_amount
```

Operators set timeout values and accept chains based on their own risk
tolerance and capital efficiency requirements. The protocol does not impose
limits on chain length -- this is an operational decision.

### Agent Recovery Path

Funding outputs include an operator recovery path for agent failure:

```
<agent_key> CHECKSIG
OR
<operator_key> CHECKSIG AND <recovery_delay> CHECKLOCKTIMEVERIFY
```

- **Normal operation**: Agent spends with its key
- **Agent failure**: Operator recovers after recovery delay
- **Agent compromise**: Attacker can only make valid payments (all
  spending paths require valid signatures)

**Recovery delay selection**: The recovery delay is an absolute timelock
(CLTV) set at channel funding time. Operators must balance:

- **Too short** (days to weeks): Risk losing funds if agent is temporarily
  unreachable due to communication outage, orbital mechanics, or maintenance
- **Too long** (years): Capital locked for extended period after actual failure

Recommended values by deployment type:

| Deployment | Recovery Delay | Rationale |
|------------|----------------|-----------|
| Satellites | 3-6 months | Mission lifetime, contact opportunities |
| Vehicles/Drones | 2-4 weeks | Frequent maintenance cycles |
| IoT devices | 1-3 months | Firmware update cycles |
| Remote infrastructure | 6-12 months | Infrequent physical access |

The recovery delay MUST exceed the longest expected communication blackout
plus margin for dispute resolution. For satellites, this accounts for orbital
precession, solar conjunction, and ground station availability.

### ln-symmetry Integration

SCRAP channels use ln-symmetry state machines:

```
Funding Tx
    |
    v
Update_0 (state 0) --[ANYPREVOUT]--> Update_1 (state 1) --[ANYPREVOUT]--> ...
    |                                    |
    v                                    v
Settlement_0                         Settlement_1
```

Each update transaction:
- Spends ANY prior update (ANYPREVOUT signature)
- Has relative timelock before settlement can be broadcast
- Settlement pays current channel balances

Key properties:
- No revocation keys or toxic waste
- Latest state always spendable
- Can sync via any communication path

### Clock Synchronization

Timelocks use Unix timestamps (`CHECKLOCKTIMEVERIFY >= 500,000,000`). Timing
sources in order of preference:

| Source | Accuracy | Timeout Margin | Notes |
|--------|----------|----------------|-------|
| GPS/GNSS receiver | <1 us | +3 hours | Standard on commercial satellites |
| Ground-uplinked NTP | ~1 second | +6 hours | Requires periodic connectivity |
| Onboard RTC | ~10 ppm drift | +24 hours | Last resort; ~1 sec/day drift |

The base margin accounts for Bitcoin Median Time Past (MTP) lag (up to ~2 hours
worst case) plus safety buffer. Implementations must account for their specific
timing source accuracy.

### Dispute Resolution

The timeout-default settlement model favors the executor. To prevent garbage
data attacks, the executor MUST provide:

1. Signed proof of execution containing `output_hash = SHA256(delivered_data)`
2. The actual delivered data

Customer dispute is valid if:
- No proof received within dispute window
- Proof signature is invalid
- `SHA256(received_data) != output_hash` in proof

The executor cryptographically commits to the output hash in the proof. If
delivered data doesn't match the commitment, the customer has trivially
verifiable evidence of fraud and the PTLC times out.

## Backwards Compatibility

SCRAP requires BIP-118 (ANYPREVOUT) activation. It cannot be deployed on
current Bitcoin without sacrificing the core properties that make it valuable
for intermittent-connectivity applications.

The protocol is an application layer built on:
- BIP-118 for ln-symmetry channel updates
- BIP-340 Schnorr signatures for adaptor signatures
- BIP-341 Taproot for efficient on-chain representation

No additional consensus changes are required beyond BIP-118.

## Security Considerations

### Adaptor Signature Security

SCRAP uses adaptor signatures as formalized in peer-reviewed literature:

- Aumayr et al., "Generalized Channels from Limited Blockchain Access",
  ACM CCS 2021
- Malavolta et al., "Anonymous Multi-Hop Locks for Blockchain Scalability
  and Interoperability", CRYPTO 2019

Security holds under the One-More Discrete Logarithm (OMDL) assumption on
secp256k1. The construction satisfies:

- **Pre-signature validity**: Adaptor signatures can be verified without `t`
- **Pre-signature adaptability**: Given `t`, anyone can complete the signature
- **Witness extractability**: Completed signature reveals `t`

### Nonce Security

Adaptor signatures require secure nonce generation:

- Deterministic derivation per RFC 6979, extended with task-specific data
- Nonce pre-commitment before task chain creation
- Single-use requirement: Each (key, nonce) pair used for exactly one signature

Nonce reuse enables private key extraction. Implementations MUST ensure nonces
are never reused, even across device restarts or recovery from backup.

### Replay Protection

See the Replay Protection section above. The verification order is critical:
checking expiration before cache lookup prevents eviction-based replay attacks.

### Clock Synchronization

Timelocks use Unix timestamps. Implementations MUST account for:

- Bitcoin MTP lag (up to ~2 hours behind real time)
- Local clock drift (depends on timing source)
- Network propagation delays

Conservative timeout margins prevent premature timeout claims.

### ln-symmetry State Security

State numbers MUST be monotonically increasing. Implementations MUST:

- Never sign a state with number <= any previously signed state
- Persist latest state number to non-volatile storage before signing
- Reject any state update with number <= current

State rollback could enable double-spending of channel funds.

## Test Vectors

See [SCRAP.md](SCRAP.md) Section 18 for test vectors covering:

- Token ID (token_id) generation
- Binding hash computation (with domain separation)
- Execution proof hash
- BIP-32 key derivation paths

## Reference Implementation

Reference implementation in progress at: https://github.com/dysonlabs/scrap

## References

### Bitcoin Improvement Proposals

- [BIP-118][bip118]: SIGHASH_ANYPREVOUT
- [BIP-340][bip340]: Schnorr Signatures for secp256k1
- [BIP-341][bip341]: Taproot: SegWit version 1 spending rules

[bip118]: https://github.com/bitcoin/bips/blob/master/bip-0118.mediawiki
[bip340]: https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki
[bip341]: https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki

### Academic References

- Aumayr et al., "Generalized Channels from Limited Blockchain Access",
  ACM CCS 2021
- Malavolta et al., "Anonymous Multi-Hop Locks for Blockchain Scalability
  and Interoperability", CRYPTO 2019
- Decker, Russell, Osuntokun, "eltoo: A Simple Layer2 Protocol for Bitcoin",
  2018

### Specifications and Implementations

- [Bitcoin Optech: eltoo][optech-eltoo]
- [Bitcoin Optech: PTLCs][optech-ptlc]
- [Bitcoin Optech: SIGHASH_ANYPREVOUT][optech-apo]
- [LN-Symmetry Project Recap][ln-recap]
- [Bitcoin Inquisition][inquisition]
- [Suredbits PTLC PoC][suredbits-ptlc]
- Lightning BOLTs: https://github.com/lightning/bolts

[optech-eltoo]: https://bitcoinops.org/en/topics/eltoo/
[optech-ptlc]: https://bitcoinops.org/en/topics/ptlc/
[optech-apo]: https://bitcoinops.org/en/topics/sighash_anyprevout/

## Acknowledgments

Thanks to Greg Sanders (instagibbs) for the ln-symmetry implementation and
documentation. Thanks to the Lightning Network developer community for ongoing
work on PTLCs and adaptor signatures.
