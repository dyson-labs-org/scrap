## SCRAP: Capability Tokens

### Operator-Signed Authorization

**How it works:** Target satellite's operator pre-signs tokens. Commanding satellite presents token during ISL contact. Target verifies signature against its operator's public key.

**Token contents:**

| Field | Purpose |
|-------|---------|
| **Issuer** | Target's operator (signer) |
| **Subject** | Who can command (satellite ID or wildcard) |
| **Audience** | Target satellite |
| **Capabilities** | What commands are allowed |
| **Constraints** | Limits (range, geography, rate) |
| **Expiration** | 24-48 hours typical |

**Key property:** Anyone can verify, only operator can issue.

This enables delegation chains and cross-operator authorization.
