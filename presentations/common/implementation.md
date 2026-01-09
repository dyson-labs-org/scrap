## Implementation

### Rust on CubeSat-Class Hardware

**Target:** ARM Cortex-A53, 64 MB RAM

**Performance:**
| Operation | Time |
|-----------|------|
| Token verification | <100ms |
| Schnorr signature | ~25ms |
| X3DH handshake | ~200ms |

**Software stack:**
- `scrap-core` — Token creation/verification (no-std)
- `scrap-lightning` — LDK integration for settlement
- `scrap-ffi` — C bindings for flight software

**Crypto:** secp256k1 only (same curve as Bitcoin). Single key hierarchy simplifies provisioning.

**Status:** Reference implementation in progress. Test vectors complete.
