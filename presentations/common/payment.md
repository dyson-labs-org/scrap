## Settlement Layer

### Trustless Payment via PTLCs

**Customer pays Dyson Labs via Lightning:**
- Instant payment, no on-chain wait
- Standard Lightning wallet compatible

**Dyson Labs creates on-chain PTLCs:**
- One PTLC output per operator in the task chain
- Each locked to an adaptor point T
- Operators can claim independently once task completes

**Task completion unlocks payment:**
- Last operator receives delivery, signs acknowledgment
- Acknowledgment signature reveals secret t
- All operators use t to claim their PTLCs
- Payment and proof-of-delivery are cryptographically atomic

**Timeout protection:**
- If task fails, PTLCs refund after timeout
- Operators who performed work get paid; those who didn't, don't
