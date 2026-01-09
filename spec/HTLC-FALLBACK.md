# SCRAP HTLC Fallback Mode

## Overview

This document describes a degraded operating mode for SCRAP (Secure Capabilities
and Routed Authorization Protocol) that can be deployed on current Bitcoin
before BIP-118 (ANYPREVOUT) activation. This fallback mode sacrifices key
protocol properties but enables early deployment for testing and validation.

**This mode is NOT recommended for production use.** It exists to:

1. Validate capability token verification and task routing
2. Test ground-agent coordination infrastructure
3. Prove channel state management works (with watchtower requirements)
4. Enable ecosystem development before BIP-118 activation

## Limitations

The HTLC fallback mode loses the following properties compared to full SCRAP:

| Property | Full SCRAP (PTLC) | HTLC Fallback |
|----------|-------------------|---------------|
| Payment-proof atomicity | Adaptor secret = proof | Separate attestation required |
| Watchtower key custody | Not required | Required (revocation keys) |
| State backup | Latest state only | Full history required |
| Offline resilience | State sync via any path | Must respond to old states |
| Payment correlation | Uncorrelated per-hop | Hash-correlated across hops |

### Loss of Payment-Proof Atomicity

With PTLCs, the adaptor signature that unlocks payment IS the acknowledgment
signature proving task completion. They are cryptographically inseparable.

With HTLCs, the payment preimage is independent of task completion. An executor
could:
- Reveal a preimage without completing the task
- Complete the task without receiving payment

**Mitigation**: Require separate signed attestations that bind payment hash to
task completion. This adds trust assumptions and complexity.

### Watchtower Requirements

LN-penalty channels require watchtowers with access to revocation keys. If a
peer broadcasts an old state and the counterparty fails to respond within the
timelock window, funds are lost.

For satellites with intermittent ground contact, this means:
- Ground stations must run watchtowers for each satellite channel
- Watchtowers must hold revocation keys (security risk)
- Satellites must have reliable ground contact within punishment windows

**Mitigation**: Use conservative timelocks (weeks) and multiple redundant
watchtowers. Accept the operational complexity.

### Full State History Required

With LN-penalty, every prior state is "toxic waste" that could be used to
steal funds. Implementations must retain all historical states and their
revocation secrets.

For constrained devices (satellites, IoT), this is problematic:
- Storage requirements grow with channel lifetime
- Backup/restore is complex (must include all states)
- Any state loss risks fund theft

**Mitigation**: Limit channel lifetime and close/reopen periodically. Accept
higher on-chain costs.

### Payment Correlation

HTLCs use the same payment hash across all hops. Any party controlling
multiple nodes in a payment path can correlate the payment.

**Mitigation**: Accept reduced privacy. For satellite operations where
operators are known entities, this may be acceptable.

## What Still Works

The following SCRAP components function identically in fallback mode:

### Capability Tokens

Capability token verification is unchanged:
- Token structure (v, iss, sub, aud, iat, exp, jti, cap, prf, sig)
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
- Nonce pre-commitment (though used differently)

## Protocol Differences

### Payment Setup

**Full SCRAP (PTLC)**:
1. Last operator commits to nonce R_last
2. Gateway computes adaptor point T
3. All PTLCs locked to same T
4. Delivery signature reveals adaptor secret

**HTLC Fallback**:
1. Gateway generates payment preimage p
2. Compute payment_hash = SHA256(p)
3. All HTLCs locked to same payment_hash
4. Gateway reveals p to unlock payments
5. Separate attestation required for delivery proof

### Settlement Flow

**Full SCRAP**:
```
Last operator signs acknowledgment
  -> Signature reveals adaptor secret t
  -> All parties claim PTLCs with t
  -> Payment = Proof (atomic)
```

**HTLC Fallback**:
```
Gateway verifies delivery attestation
  -> Gateway reveals preimage p
  -> All parties claim HTLCs with p
  -> Attestation separate from payment (non-atomic)
```

### Channel State Machine

**Full SCRAP (ln-symmetry)**:
- Update transactions spend ANY prior state (ANYPREVOUT)
- No revocation keys
- Latest state always valid

**HTLC Fallback (LN-penalty)**:
- Each state has specific revocation key
- Old states are toxic (can be used to steal)
- Watchtower must respond to old state broadcasts

## Attestation Layer

To partially recover payment-proof binding, the fallback mode requires an
attestation layer:

### Attestation Structure

```
DeliveryAttestation:
  v: 1
  task_jti: "task-token-id"
  payment_hash: <32 bytes>
  output_hash: SHA256(delivered_data)
  timestamp: 1704067200
  executor_pubkey: <33 bytes>
  sig: <schnorr-signature>
```

### Verification

Before revealing the preimage, the gateway MUST verify:

1. Attestation signature is valid
2. `task_jti` matches the requested task
3. `payment_hash` matches the HTLC
4. `output_hash` matches received data
5. `timestamp` is within acceptable window

### Trust Assumption

The gateway must trust the executor to provide honest attestations. Unlike
PTLC mode where payment and proof are cryptographically bound, fallback mode
relies on:

- Executor reputation
- Economic incentives (future business)
- Legal agreements between operators

This is strictly weaker than the cryptographic guarantees of full SCRAP.

## Deployment Guidance

### When to Use Fallback Mode

- Development and testing
- Proof-of-concept demonstrations
- Ecosystem tooling development
- Academic research

### When NOT to Use Fallback Mode

- Production payments between untrusted parties
- High-value task execution
- Long-lived channels with significant capacity
- Deployments where watchtower reliability is uncertain

### Migration Path

When BIP-118 activates:

1. Close existing LN-penalty channels cooperatively
2. Open new ln-symmetry channels
3. Update attestation layer to use adaptor signatures
4. Remove watchtower key custody
5. Simplify state backup to latest-only

The capability token layer requires no changes. Task routing requires no
changes. Only the payment layer migrates.

## References

- [SCRAP Specification](SCRAP.md) - Full protocol specification
- [BIP-SCRAP](BIP-SCRAP.md) - Informational BIP motivating ANYPREVOUT
- [Lightning BOLTs](https://github.com/lightning/bolts) - LN-penalty protocol
