## Security Properties

### No Trusted Third Parties

| Property | How It's Achieved |
|----------|-------------------|
| **Authentication** | X3DH mutual auth (no pre-shared secrets) |
| **Authorization** | Operator-signed capability tokens |
| **Forward Secrecy** | Ephemeral keys deleted after session |
| **Non-repudiation** | Cryptographic proof of execution |
| **Link Security** | AES-256-GCM per CCSDS SDLS |

**What an attacker cannot do:**
- Forge capability tokens (requires operator key)
- Replay tokens (unique ID + expiration)
- Impersonate satellites (X3DH verification)
- Eavesdrop on ISL (encrypted link)
- Steal payments (cryptographic binding)
