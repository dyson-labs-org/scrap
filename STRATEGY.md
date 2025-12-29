# SCAP Strategy: From UHF Demo to Production Deployment

## Executive Summary

This document outlines the strategic path from UHF CubeSat protocol demonstration through standardization to production deployment. The strategy prioritizes de-risking through phased execution, separating protocol validation from infrastructure dependencies.

---

## Phase Overview

```
                    TIMELINE
    ─────────────────────────────────────────────────────────►

    PHASE 1           PHASE 2           PHASE 3           PHASE 4
    Protocol Demo     Standardization   Regulatory        Production
    (12-18 months)    (24-36 months)    (36-48 months)    (48+ months)

    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ UHF CubeSat │   │ CCSDS       │   │ ITU WRC-27  │   │ Commercial  │
    │ Demo        │──►│ Green Book  │──►│ X-band S2S  │──►│ Service     │
    │             │   │ BIP Draft   │   │ AGS Deploy  │   │ Launch      │
    └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
         │                  │                  │                  │
         ▼                  ▼                  ▼                  ▼
    Grant Funding     Industry WG       FCC Filing        Revenue
    NASA/DARPA        Formation         ITU Coordination  Operations
```

---

## Phase 1: Protocol Demonstration (12-18 months)

### Objective
Validate SCAP/SISL protocol correctness on existing CubeSat infrastructure.

### Scope

**In Scope:**
- Capability token issuance, delegation, verification
- Onion-routed task bundles through 2-3 satellites
- Adaptor signature binding (task↔payment atomicity)
- On-chain Schnorr PTLC settlement
- Ground relay hop integration
- Multi-hop acknowledgment protocol

**Out of Scope:**
- High-bandwidth data relay (UHF limitation)
- Actual imaging/processing tasks (depends on partner capabilities)
- AGS infrastructure (separate proposal)
- Lightning channels (Phase 2+, requires PTLC soft fork)

### Technical Approach

**UHF CubeSat Testbed:**
```
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│   CubeSat A   │────►│   CubeSat B   │────►│   CubeSat C   │
│  (UHF relay)  │     │  (UHF relay)  │     │  (UHF relay)  │
└───────────────┘     └───────────────┘     └───────────────┘
       │                                            │
       ▼                                            ▼
┌───────────────┐                          ┌───────────────┐
│   Ground Tx   │                          │   Ground Rx   │
│  Task Upload  │                          │   Delivery    │
└───────────────┘                          └───────────────┘
       │                                            │
       └──────────────── Bitcoin ───────────────────┘
                    (On-chain PTLC settlement)
```

**UHF Characteristics:**
- Band: 435-438 MHz (amateur/ISL allocation)
- Data rate: 9.6 kbps typical, 19.2 kbps max
- Sufficient for: tokens (~1KB), signatures (64B), acks (100B)
- Insufficient for: imagery, bulk data

**What Demo Proves:**
- Protocol cryptographic correctness
- Multi-hop routing works
- Adaptor signatures bind task to payment
- Settlement occurs atomically
- Ground relay integrates seamlessly

### Funding Strategy

**Target Programs:**

| Agency | Program | Alignment | Funding Range |
|--------|---------|-----------|---------------|
| NASA | SBIR Phase I | Autonomous Operations | $150K |
| NASA | SBIR Phase II | Autonomous Operations | $750K-1M |
| DARPA | Blackjack-related | Proliferated LEO | Varies |
| NSF | CPS | Cyber-Physical Systems | $500K-1M |
| Space Force | Commercial Integration | Cross-operator | Varies |

**Proposal Positioning:**

For NASA:
> "Cryptographically-verified authorization for autonomous inter-satellite operations, reducing ground-loop latency from hours to minutes."

For DARPA:
> "Trustless task delegation across contested networks where pre-shared secrets are unavailable and real-time ground coordination is denied."

**Key Messages:**
1. Lead with AUTHORIZATION, not payment
2. Emphasize autonomy and reduced ground dependency
3. Highlight contested/degraded environment resilience
4. Show TRL progression roadmap
5. Reference existing standards (CCSDS, Bitcoin/Schnorr)

### Partner Requirements

**CubeSat Operators:**
- Existing UHF ISL capability
- Willing to upload experimental firmware
- Minimum 2 satellites for multi-hop demo
- Ideally 3+ for realistic relay chain

**Potential Partners:**
- University CubeSat programs
- Commercial CubeSat operators (Spire, Planet if interested)
- Government research constellations

### Deliverables

| Deliverable | Description |
|-------------|-------------|
| Flight firmware | SCAP/SISL stack for target CubeSat platform |
| Ground software | Task bundle creation, settlement monitoring |
| Demo report | Results, latency measurements, lessons learned |
| Open source release | Reference implementation (Rust) |
| Specification updates | Incorporate demo learnings |

---

## Phase 2: Standardization (24-36 months)

### Objective
Establish SCAP as recognized standard through CCSDS and Bitcoin communities.

### CCSDS Path

**Target Working Group:** Space Internetworking Services Area (SIS)

**Document Progression:**
```
Year 1: Informational Report (Green Book)
        └─► "Capability-Based Authorization for Inter-Satellite Operations"

Year 2: Experimental Specification (Orange Book)
        └─► Trial implementations, interoperability testing

Year 3+: Recommended Standard (Blue Book)
        └─► Production specification
```

**CCSDS Alignment:**
- Build on CCSDS 133.0-B (Space Packet Protocol)
- Integrate with CCSDS 355.0-B (Space Data Link Security)
- Reference CCSDS 732.0-B (Internet Protocol over CCSDS)

**Engagement Strategy:**
1. Identify CCSDS member organization sponsor (NASA, ESA, JAXA)
2. Present at CCSDS technical meetings
3. Submit Green Book draft
4. Form Birds-of-a-Feather working group
5. Iterate through review process

### Bitcoin Improvement Proposals (BIP)

**Scope:** Satellite-specific adaptor signature conventions

**Potential BIPs:**
1. **Nonce Pre-commitment for Constrained Environments**
   - Address radiation-induced entropy failures
   - Specify nonce pool management
   - Define recovery procedures

2. **Task-Payment Binding Format**
   - Standardize adaptor point derivation
   - Define proof-of-execution message format
   - Specify timeout conventions

**Process:**
1. Draft informational BIP
2. Submit to bitcoin-dev mailing list
3. Gather feedback from Lightning developers
4. Revise and formalize

### Industry Working Group

**Formation:**
- Convene interested parties from demo phase
- Include: satellite operators, ground station providers, payment processors
- Structure: informal consortium initially, formalize if traction

**Charter:**
- Interoperability testing
- Use case validation
- Regulatory coordination
- Market development

---

## Phase 3: Regulatory Coordination (36-48 months)

### ITU Strategy (AGS X-band Allocation)

**Goal:** Secure X-band (8.025-8.4 GHz) space-to-space allocation at WRC-27

**Current Status:**
- X-band EESS allocated for space-to-Earth only
- No explicit rejection of space-to-space
- WRC-23 established Ka-band ISL precedent

**Timeline:**
```
2025: Propose WRC-27 agenda item via national administration (US/EU)
2025-2027: ITU-R Study Group 7 sharing studies
2027: WRC-27 considers X-band space-to-space allocation
2028: National implementation
```

**Parallel Strategy:**
- Deploy AGS using "receive-only interpretation" (legal theory)
- Bilateral agreements with key EO operators
- Build coalition for WRC-27 advocacy

**Stakeholder Coalition:**
- US: NASA, NOAA, NRO commercial partners
- EU: ESA, Copernicus operators
- Others: JAXA, CSA, commercial EO operators

### FCC Coordination

**License Requirements:**
- Space station license for AGS constellation
- Earth station licenses for ground segment
- Experimental licenses for initial demo

**Process:**
1. Pre-application meeting with FCC Space Bureau
2. Experimental license for demo phase
3. Full application after ITU allocation secured

### NTIA Coordination

**For Government Spectrum:**
- NTIA coordinates federal spectrum use
- Relevant for NASA/DoD partnership scenarios
- May provide path for government-sponsored demo

---

## Phase 4: Production Deployment (48+ months)

### Prerequisites

Before production deployment:
- [ ] CCSDS Blue Book (or equivalent industry standard)
- [ ] ITU X-band allocation (for AGS) OR Ka-band-only architecture
- [ ] Lightning PTLC activation (or continue on-chain PTLCs)
- [ ] Anchor customers committed
- [ ] Regulatory licenses secured

### Architecture Options

**Option A: ISL-Native Only**
- Deploy with Starlink/Kuiper/Iridium-capable satellites
- No AGS required
- Limited to ISL-equipped operators

**Option B: AGS-Enabled**
- Deploy AGS constellation (12 satellites, ~$300M)
- Enable any X-band EO satellite
- Requires ITU allocation

**Option C: Hybrid**
- ISL-native for equipped satellites
- Ground relay for others
- AGS as future upgrade

### Revenue Model

| Service | Price Point | Volume |
|---------|-------------|--------|
| Relay (per MB) | $0.01-0.10 | High |
| Scheduled contact | $100-500/pass | Medium |
| Emergency priority | $1,000-5,000/pass | Low |
| Dedicated capacity | $10K-50K/month | Anchor |

### Go-to-Market

**Initial Customers:**
- Emergency response agencies (USCG, FEMA, EU Civil Protection)
- Weather services (NOAA, EUMETSAT)
- Defense/intelligence (classified programs)

**Value Proposition:**
- Latency reduction (hours → minutes)
- Coverage improvement (global vs. ground station sparse)
- Operational flexibility (any satellite, any operator)

---

## Risk Matrix

| Risk | Phase | Likelihood | Impact | Mitigation |
|------|-------|------------|--------|------------|
| CubeSat partner unavailable | 1 | Medium | High | Multiple partner outreach; ground-only simulation fallback |
| Grant funding not secured | 1 | Medium | High | Diversify across NASA/DARPA/NSF; bootstrap with smaller grants |
| CCSDS adoption slow | 2 | Medium | Medium | Parallel de facto standard via industry consortium |
| BIP rejected/ignored | 2 | Low | Low | Proceed without BIP; spec is self-contained |
| ITU X-band allocation denied | 3 | Medium | High | Pivot to Ka-band only (requires EO upgrades) |
| Lightning PTLC delayed | 4 | Medium | Medium | Continue on-chain PTLCs; operational but higher fees |
| Market timing (SpaceLink precedent) | 4 | Medium | High | Anchor customers before full deployment; phased rollout |

---

## Dependencies

```
PHASE 1 DEPENDENCIES:
├── CubeSat partner with UHF ISL ────────────────────────► BLOCKING
├── Grant funding ($150K+ for Phase I) ──────────────────► BLOCKING
├── Reference implementation complete ───────────────────► BLOCKING
└── Test vectors validated ──────────────────────────────► Required

PHASE 2 DEPENDENCIES:
├── Phase 1 demo success ────────────────────────────────► BLOCKING
├── CCSDS sponsor organization ──────────────────────────► Required
├── Industry working group formation ────────────────────► Required
└── BIP community engagement ────────────────────────────► Nice-to-have

PHASE 3 DEPENDENCIES:
├── National administration sponsor (US/EU) ─────────────► BLOCKING for ITU
├── WRC-27 agenda item acceptance ───────────────────────► BLOCKING for ITU
├── FCC experimental license ────────────────────────────► Required
└── Sharing studies completion ──────────────────────────► Required for ITU

PHASE 4 DEPENDENCIES:
├── ITU allocation OR Ka-band-only decision ─────────────► BLOCKING for AGS
├── Lightning PTLC OR on-chain PTLC acceptance ──────────► Required
├── Anchor customer commitments ─────────────────────────► BLOCKING
└── Regulatory licenses ─────────────────────────────────► BLOCKING
```

---

## Key Milestones

| Milestone | Target Date | Success Criteria |
|-----------|-------------|------------------|
| Grant proposal submitted | Q2 2025 | NASA SBIR or equivalent |
| CubeSat partner secured | Q3 2025 | Signed agreement |
| Ground demo complete | Q4 2025 | Protocol validated in simulation |
| Flight demo complete | Q4 2026 | Multi-hop task settled on-chain |
| CCSDS Green Book submitted | Q2 2026 | Accepted for review |
| Industry WG formed | Q4 2026 | 5+ participating organizations |
| WRC-27 agenda item | Q4 2025 | Submitted by national admin |
| CCSDS Blue Book | Q4 2028 | Approved standard |
| ITU allocation | Q4 2027 | WRC-27 decision |
| Production service | Q4 2029 | First commercial customers |

---

## Immediate Next Steps

1. **Complete Sprint 1** - Document corrections and clarifications
2. **Finalize slideshow** - Government-friendly framing
3. **Identify grant targets** - NASA SBIR topics, DARPA BAAs
4. **Partner outreach** - CubeSat operators with UHF ISL
5. **CCSDS contact** - Identify potential sponsor organization

---

## Appendix A: Relevant Solicitations

### NASA SBIR/STTR

**Typical Topics:**
- Autonomous spacecraft operations
- Inter-satellite communication
- Space situational awareness
- On-orbit servicing

**Cycle:** Annual, subtopics released ~November

**Contact:** sbir@nasa.gov, specific center POCs

### DARPA

**Relevant Programs:**
- Blackjack (proliferated LEO)
- Space-BACN (optical crosslinks)
- Future programs TBD

**Process:** BAA responses, direct PM engagement

### NSF

**Relevant Programs:**
- Cyber-Physical Systems (CPS)
- Secure and Trustworthy Cyberspace (SaTC)

---

## Appendix B: CCSDS Process

### Document Types

| Color | Type | Purpose |
|-------|------|---------|
| Green | Informational Report | Concept description, not normative |
| Orange | Experimental | Trial specification |
| Magenta | Recommended Practice | Implementation guidance |
| Blue | Recommended Standard | Normative specification |

### Submission Process

1. Identify Area Director (Space Internetworking Services)
2. Submit White Paper for interest assessment
3. Form Working Group if interest confirmed
4. Draft document through WG review cycles
5. CCSDS-wide review and ballot
6. Publication

### Timeline

- White Paper to Green Book: 6-12 months
- Green Book to Orange Book: 12-18 months
- Orange Book to Blue Book: 18-24 months

---

## Appendix C: Bitcoin/Lightning Timeline

### Current State (2025)

- Schnorr signatures (BIP-340): Activated (Taproot, Nov 2021)
- Adaptor signatures: Available, no soft fork required
- PTLCs: Requires signature aggregation, not yet activated
- LN-Symmetry (Eltoo): Requires SIGHASH_ANYPREVOUT, not yet activated

### SCAP Implications

**Today:**
- On-chain PTLCs with Schnorr adaptor signatures: AVAILABLE
- Use for Phase 1 demo

**Future (if/when activated):**
- Lightning PTLCs: Instant settlement, lower fees
- LN-Symmetry: Simplified channel state management
- Upgrade path documented in PROPOSAL_CHANNELS.md

### Activation Timeline (Speculative)

- Signature aggregation (MuSig2 in Lightning): 2025-2026
- SIGHASH_ANYPREVOUT: Unknown (requires soft fork consensus)
- Lightning PTLC deployment: 2026-2027 if primitives activated
