## The Insight

### Operators Pre-Sign. Satellites Verify Offline.

**Current systems require ground loops:**
- Satellite receives request
- Waits for ground station pass (47 minutes average)
- Ground authorizes or denies
- Waits for next pass to relay decision

**SCRAP eliminates the ground loop:**
- Operator pre-signs capability tokens (before mission)
- Tokens uploaded to requesting satellite
- Target satellite verifies token signature on-orbit
- No ground contact needed for authorization

**Key property:** The target satellite knows its operator's public key. It can verify any token signed by that operator — instantly, offline, autonomously.

**Result:** Authorization in milliseconds, not hours.
