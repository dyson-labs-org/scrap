## Capability Delegation

### Pre-Authorized Emergency Response

**Scenario:** NASA pre-authorizes Iridium constellation to command CALIPSO for volcanic ash emergencies.

**Root token** (NASA issues):
- Subject: `IRIDIUM-*` (any Iridium satellite)
- Audience: CALIPSO
- Capabilities: `[imaging, atmospheric]`
- Expiration: 30 days

**Delegated token** (Iridium-155 re-issues):
- Subject: IRIDIUM-172 (specific satellite)
- Capabilities: `[imaging]` (subset only)
- Expiration: 24 hours (shorter only)

**Attenuation rules:** Child tokens can only narrow permissions, never expand.

**Result:** Sub-minute emergency response. No ground loop required.
