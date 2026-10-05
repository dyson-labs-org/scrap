# Online operation authority profile, version 1

This profile binds a root SAT-CAP token to an immutable online application grant.
It does not replace account authorization, provider entitlement, revocation or usage
accounting. It supports no offline authority or delegated token chains.

The issuer and executor agree on a versioned audience and exact operation
capability. JTI is the lowercase 64-character SHA-256 digest of the immutable
application grant, whose canonical representation is defined by that application.
The grant contains resource identities, authorized scope, limits and ownership.
The executor obtains expected issuer, subject, audience, capability and digest
from trusted application state, not from the unverified token.

The wire remains the existing protected CBOR byte string plus ES256K signature.
The strict verifier authenticates the received protected bytes and rejects
trailing bytes, unknown fields, constraints, parent references, nonzero chain
depth, wildcard capabilities and more than one capability. The validity interval
is issued_at <= now < expires_at. Maximum token size is 16 KiB.

Header fields: alg=ES256K, typ=SAT-CAP, optional enc=CBOR, optional chn=0.
Payload fields: iss, sub, aud, iat, exp, jti, cap.
No additional fields are accepted in version 1. In particular, callers must not
assume that arbitrary CDDL constraint extensions are preserved by typed consumers.

The executor MUST verify current grant validity/revocation, ownership, requested
resource scope and shared allowance before execution and before each retry.
A signature alone is not an authorization decision. Grant IDs, operation IDs and
attempt IDs have different purposes; idempotent recovery must not duplicate work.

The Rust entry point is authority::verify_operation. The C entry point is
scrap_verify_operation. Both require all trusted expectations and a signing public
key. The Python scrap-authority wheel contains this existing native library;
it implements no cryptography in Python.

This profile does not define payment or a delivery receipt. It does not prove
scientific quality, physical execution or customer transfer completion.
