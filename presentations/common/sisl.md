## SISL: Secure Inter-Satellite Link

### Authentication Without Pre-Shared Secrets

**The challenge:** Two satellites from different operators meet in orbit. They've never communicated. How do they authenticate?

**Current systems fail:** CCSDS SDLS uses symmetric keys. Only the key holder can authenticate. No delegation possible.

**SISL solution:** X3DH key agreement (same as Signal)
- Each satellite has operator-signed identity key
- Ephemeral keys provide forward secrecy
- No pre-shared secrets required
- Works between any two satellites

**Stack:**
| Layer | Function |
|-------|----------|
| SCRAP | Capability tokens, task authorization |
| SISL | X3DH key agreement, AES-256-GCM |
| Physical | RF or optical ISL |
