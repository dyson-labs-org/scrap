# SCRAP Strategy: From UHF Demo to Production Deployment

## Executive Summary

This document outlines the strategic path from UHF CubeSat protocol demonstration through standardization to production deployment. The strategy prioritizes de-risking through phased execution, separating protocol validation from infrastructure dependencies.

---

## Phase Overview

```
                              TIMELINE
    ─────────────────────────────────────────────────────────────────────────────────►

    PHASE 1           PHASE 2           PHASE 3           PHASE 4
    Protocol Demo     Standardization   Regulatory        Production
    (6-12 months)     (24-36 months)    (36-48 months)    (48+ months)

    ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
    │ UHF CubeSat │   │ CCSDS       │   │ ITU WRC-27  │   │ Commercial  │
    │ Software    │──►│ Green Book  │──►│ X-band S2S  │──►│ Service     │
    │ Demo        │   │ BIP Draft   │   │ AGS Deploy  │   │ Launch      │
    └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
         │                  │                  │                  │
         ▼                  ▼                  ▼                  ▼
    Firmware Upload   Industry WG       FCC Filing        Revenue
    Existing Sats     Formation         ITU Coordination  Operations


    PARALLEL TRACK: BitAxe Hardware
    ────────────────────────────────────────────────────────────────────►

    ┌─────────────────────────────────────────────────────────────────┐
    │ BitAxe Radiation Characterization (independent of protocol)     │
    │ - Can fly whenever funding/launch secured                       │
    │ - Validates space computing hardware                            │
    │ - Not a prerequisite for protocol demo                          │
    └─────────────────────────────────────────────────────────────────┘
```

---

## Parallel Track: BitAxe Radiation Characterization

**Status:** Independent of protocol demo. Can proceed whenever funding/launch secured.

### Objective
Characterize commercial ASIC chip operation in LEO radiation environment. Validates space computing hardware for future commercial deployment.

### Hardware

**BitAxe Space Payload:**
- Board: Open-source BitAxe mining board (or partner-provided)
- Chip: **3nm ASIC** from Auradine (Teraflux) or Block (Proto)
- Form Factor: 1U CubeSat compatible
- Power: ~12W per chip (Auradine spec)

**Chip Partner Options:**
| Partner | Chip | Process | Power | Hashrate |
|---------|------|---------|-------|----------|
| **Auradine** | Teraflux | 3nm TSMC | 12W | 0.87 TH/s |
| **Block** | Proto | 3nm TSMC | TBD | TBD |

**What Mission Proves:**
- **First 3nm space characterization** - SEU rates, TID effects
- Commercial ASIC radiation tolerance
- Thermal management in vacuum
- Power system performance
- Data downlink via amateur UHF

### Launch Pathways

| Pathway | Cost | Timeline | Requirements |
|---------|------|----------|--------------|
| **NASA CSLI** | Free | Spring 2026 call → 2027 launch | Educational partner required |
| **NASA TechLeap** | Prize ($500K) | Summer 2026 | Suborbital only |
| **AMSAT** | ~$10-50K | Flexible | Amateur radio coordination |
| **Commercial Rideshare** | $50-150K | 3-6 months | SpaceX, RocketLab |
| **ISS Deployment** | $50-100K | 6-12 months | Nanoracks, D-Orbit |

### Recommended Path: NASA CSLI + University Partner

**Why CSLI:**
- Free launch (rideshare on NASA missions)
- 200+ CubeSats launched across 42 states
- Credibility for follow-on funding
- Educational mission aligns with grant requirements

**University Partner Requirements:**
- Must be US educational institution
- Provides academic PI for proposals
- Students gain flight experience
- Shared IP/publication rights

**Candidate Partners (see [ACADEMIC.md](ACADEMIC.md)):**

| Institution | Contact | Relevance |
|-------------|---------|-----------|
| **USF** | Dr. Attila Yavuz | Satellite security, post-quantum |
| **FAU** | Dr. Reza Azarderakhsh | Cryptography hardware |
| **Florida Tech** | Dr. Carlos Otero | Satellite communications |

### Alternative Path: AMSAT Integration

**Advantages:**
- Global ground station network (SatNOGS)
- Community eager for new projects
- Lower cost than commercial
- UHF amateur band (435-438 MHz)

**AMSAT Engagement:**
1. Join AMSAT (https://www.amsat.org/)
2. Present BitAxe concept to engineering team
3. Propose as secondary payload on Fox-Plus or future mission
4. Coordinate frequency allocation with IARU

### Combined BitAxe + SCRAP Mission

**Concept:** Single CubeSat with both products:

```
┌─────────────────────────────────────────────────────────────┐
│                    1U-3U CubeSat                            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │   BitAxe ASIC   │    │        SCRAP/SISL Stack          │ │
│  │                 │    │                                 │ │
│  │  - Mining chip  │◄──►│  - Capability tokens            │ │
│  │  - Thermal mgmt │    │  - X3DH authentication          │ │
│  │  - Power system │    │  - Onion routing                │ │
│  └─────────────────┘    │  - Adaptor signatures           │ │
│                         └─────────────────────────────────┘ │
│                                     │                       │
│                         ┌───────────▼───────────┐           │
│                         │   UHF Radio (9.6kbps) │           │
│                         │   435-438 MHz         │           │
│                         └───────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

**Benefits:**
- Single launch validates both products
- BitAxe provides compute, SCRAP provides secure comms
- Demonstrates space computing + payment in one mission
- Reduces total launch costs

### Deliverables

| Deliverable | Description |
|-------------|-------------|
| Radiation data | SEU rates, TID measurements, chip performance |
| Thermal analysis | Temperature profiles, power dissipation |
| Flight heritage | Demonstrated space operation |
| Open data release | Publish results for community |
| Design files | Open-source CubeSat payload design |

### Commercial Data Customers

**The Value Proposition:** Ground radiation testing is cheaper and faster than flight. The unique value of in-flight data is **model validation**—correlating real-world performance with predictions from environment models (AP9/AE9, SPENVIS).

**Critical Advantage:** With Auradine or Block partnership, you would fly **3nm TSMC technology** which has **ZERO space flight heritage**. TSMC N3 only entered volume production in December 2022. This is not incremental data—it's first-ever characterization of a process node that will power next-generation satellites.

| Customer Type | Value Proposition | Engagement Model | Potential Value |
|--------------|-------------------|------------------|-----------------|
| **NASA GSFC REAG** | **First 3nm flight data** - validate models | Space Act Agreement | Credibility, co-publications |
| **AFRL / Aerospace Corp** | **3nm characterization** - no existing data | Research contract | $200-500K |
| **NewSpace Constellation Ops** | Design margin for next-gen 3nm designs | Data license | $100-300K |
| **Rad Test Service Providers** | **Exclusive 3nm flight data** | Partnership/resale | Revenue share |
| **Auradine / Block** | Flight heritage for their chips | Sponsored mission | $300K+ |
| **TSMC (via customers)** | "N3 has demonstrated LEO operation" | Co-marketing | Variable |

**Path A: NASA GSFC Partnership**
- NASA's [Radiation Effects and Analysis Group](https://etd.gsfc.nasa.gov/capabilities/capabilities-listing/radiation-effects-and-analysis/) maintains 30+ years of flight data
- They provide free data to commercial partners
- Value: Space Act Agreement → credibility → follow-on funding
- Contact: radhome.gsfc.nasa.gov

**Path B: Aerospace Corp Research Contract**
- Aerospace Corp is the [FFRDC for DoD/IC space](https://aerospace.org)
- They publish COTS design guidance and need flight validation
- Pitch: "Characterize [process node] in LEO for $X"
- Contact: Technical POC via Space Enterprise Consortium

**Path C: NewSpace Operator Data Sales**
- Constellation operators (Starlink, Planet, OneWeb, Swarm) use COTS extensively
- Reference: [Starlink radiation study](https://ieeexplore.ieee.org/document/10354004) shows value of in-flight data
- Challenge: May wait for your published paper rather than pay
- Strategy: Offer exclusive early access before publication

**Path D: Rad Test Service Partnership**
- Companies: [Radiation Test Solutions](https://radiationtestsolutions.com/), [Space Radiation Services](https://www.spaceradiationservices.com/)
- Structure: They resell your flight data bundled with ground test correlation
- Value: Flight heritage adds premium to their service offerings
- Revenue: Licensing fee or revenue share

**Path E: Auradine/Block Sponsored Mission**
- Both companies want flight heritage for their 3nm chips
- Value to them: "Our chip has demonstrated LEO operation"
- Auradine: US-based, Marathon-backed, already selling chips directly
- Block: Open source, strong brand, may see PR value in space mission
- Pitch: "Partner with us on first 3nm space characterization—marketing + technical validation"

**ASIC Partner Options:**

| Partner | Chip | Process Node | Foundry | Status |
|---------|------|--------------|---------|--------|
| **Auradine** | Teraflux | **3nm** | TSMC N3 | Shipping (2024) |
| **Block** | Proto | **3nm** | TSMC N3 | Shipping to Core Scientific (2024) |
| ~~Bitmain~~ | BM1397 | 7nm | TSMC N7 | ❌ Not pursuing |

**Why 3nm is More Valuable:**

| Process | Volume Production | Space Ground Testing | Flight Heritage |
|---------|-------------------|---------------------|-----------------|
| 7nm | 2018 | Extensive (Versal, INFINIT) | Limited |
| **3nm** | **Dec 2022** | **Minimal** | **NONE** |

**Auradine Advantages:**
- US-based company (easier partnership, ITAR compliance)
- [Marathon-backed](https://auradine.com/) ($48.7M invested)
- Selling chips directly (unique in industry)
- 3nm ASIC: 0.87 TH/s per chip, 12W, 8×8mm package

**Block Advantages:**
- [Open source chips](https://cointelegraph.com/news/block-3nm-mining-asics-core-scientific)
- Strong brand (Jack Dorsey)
- Proto Rig modular design
- Already shipping to Core Scientific

**Space Heritage Status (Dec 2024):**

TSMC 3nm (N3) entered volume production December 2022. Research shows:
- **Ground radiation testing:** Minimal or unpublished
- **ESA/NASA characterization:** None found
- **On-orbit flight data:** **ZERO**

**Implication:** Your BitAxe mission would provide **the first on-orbit characterization of 3nm technology**. This is significantly more valuable than 7nm characterization because:
1. No existing flight data to compare against
2. GAA vs FinFET transistor architecture differences (Samsung 3nm uses GAA)
3. Critical for next-gen satellite designs considering 3nm
4. Foundries/fabless companies have zero space qualification data

**Key Due Diligence:**
1. ~~Identify process node options~~ ✓ Auradine/Block at 3nm
2. ~~Search for existing 3nm flight data~~ ✓ None exists
3. **VERY HIGH value proposition** - first-ever 3nm flight characterization
4. Contact Auradine/Block for partnership discussion
5. Contact NASA GSFC REAG - they will be very interested in 3nm data

### Funding Sources

| Source | Amount | Fit |
|--------|--------|-----|
| [NSIC](#) | OTA | Dual-use hardware |
| [AFRL STAR](#) | Varies | Space technology |
| [NASA TechLeap](#) | $500K + flight | Suborbital test |
| [DIU CSO](#) | Varies | Commercial space hardware |

See [FUNDING.md](FUNDING.md) for full details.

### Timeline

| Milestone | Target |
|-----------|--------|
| University partner secured | Q1 2026 |
| CSLI proposal submitted | Q2 2026 |
| Payload design complete | Q3 2026 |
| Integration & test | Q4 2026 |
| Launch (target) | 2027 |

---

## Phase 1: Protocol Demonstration (6-12 months)

### Objective
Validate SCRAP/SISL protocol correctness via firmware update to existing flying satellites.

### Why This Is Easier Than Hardware

| Aspect | Protocol Demo | Hardware Demo |
|--------|---------------|---------------|
| **What's needed** | Firmware upload | Build payload, find launch |
| **Timeline** | Weeks after partner agreement | 12-24 months |
| **Cost** | Partner's satellite time | $50-150K+ launch |
| **Regulatory** | Amateur UHF (435-438 MHz) already allocated | May need coordination |
| **Risk** | Software bugs (fixable) | Hardware failure (not fixable) |

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
| Flight firmware | SCRAP/SISL stack for target CubeSat platform |
| Ground software | Task bundle creation, settlement monitoring |
| Demo report | Results, latency measurements, lessons learned |
| Open source release | Reference implementation (Rust) |
| Specification updates | Incorporate demo learnings |

---

## Phase 2: Standardization (24-36 months)

### Objective
Establish SCRAP as recognized standard through CCSDS and Bitcoin communities.

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
| CubeSat partner unavailable | 1 | Medium | High | Multiple partner outreach (university, AMSAT, commercial); ground simulation proves protocol |
| Firmware integration issues | 1 | Medium | Medium | Work with partner on target platform; provide reference impl |
| Grant funding not secured | 1 | Low | Low | Protocol demo can proceed without grants - just need partner |
| CCSDS adoption slow | 2 | Medium | Medium | Parallel de facto standard via industry consortium |
| BIP rejected/ignored | 2 | Low | Low | Proceed without BIP; spec is self-contained |
| ITU X-band allocation denied | 3 | Medium | High | Pivot to Ka-band only (requires EO upgrades) |
| Lightning PTLC delayed | 4 | Medium | Medium | Continue on-chain PTLCs; operational but higher fees |
| Market timing (SpaceLink precedent) | 4 | Medium | High | Anchor customers before full deployment; phased rollout |
| **BitAxe Risks (Parallel)** | | | | |
| Hardware funding unavailable | BitAxe | Medium | Medium | Wait for opportunities; not blocking protocol demo |
| University partner unavailable | BitAxe | Low | Medium | Multiple options; commercial launch fallback |
| BitAxe radiation failure | BitAxe | Medium | Low | Characterization data valuable either way |

---

## Dependencies

```
PHASE 1 DEPENDENCIES (Protocol Demo - PRIMARY PATH):
├── CubeSat partner with UHF capability ────────────────────► BLOCKING
├── Reference implementation complete ──────────────────────► BLOCKING
├── Test vectors validated ─────────────────────────────────► Required
├── Ground station access (or partner provides) ───────────► Required
└── Grant funding ($150K+) ─────────────────────────────────► Helpful but not blocking

BITAXE DEPENDENCIES (Parallel Track):
├── Hardware funding ($50-150K) ────────────────────────────► BLOCKING
├── University partner (for CSLI) OR commercial launch ────► BLOCKING
├── BitAxe payload design complete ─────────────────────────► BLOCKING
├── Amateur radio coordination (if AMSAT path) ────────────► Required
└── Ground station access ──────────────────────────────────► Required

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
| **Phase 1: Protocol Demo (Priority)** | | |
| Reference implementation complete | Q1 2026 | Rust crate, test vectors pass |
| CubeSat partner secured | Q1 2026 | Signed agreement |
| Ground simulation complete | Q2 2026 | Protocol validated end-to-end |
| Firmware uploaded to satellite | Q2 2026 | Partner accepts code |
| **Flight demo complete** | **Q3 2026** | Multi-hop task settled on-chain |
| **Phase 2: Standards** | | |
| CCSDS Green Book submitted | Q4 2026 | Accepted for review |
| Industry WG formed | Q1 2027 | 5+ participating organizations |
| WRC-27 agenda item | Q4 2025 | Submitted by national admin |
| **Phase 3-4: Production** | | |
| CCSDS Blue Book | Q4 2028 | Approved standard |
| ITU allocation | Q4 2027 | WRC-27 decision |
| Production service | Q4 2029 | First commercial customers |
| **BitAxe (Parallel Track)** | | |
| Hardware funding secured | When available | NSIC, AFRL STAR, or other |
| University partner (if CSLI) | When available | MOU signed |
| BitAxe launch | TBD | Radiation data collected |

---

## Immediate Next Steps

### Phase 1: Protocol Demo (Priority)

1. **Complete reference implementation** - Rust crate with full protocol stack
2. **CubeSat partner outreach** - Find operator willing to upload experimental firmware
   - University CubeSat programs (existing UHF satellites)
   - AMSAT community (Fox satellites, others)
   - Commercial operators (Spire, Planet if interested)
3. **Ground simulation** - End-to-end protocol validation before flight
4. **Finalize slideshow** - Government-friendly framing for partner conversations
5. **Grant applications** - NSF SaTC (Jan 26), NASA when SBIR resumes

### BitAxe Hardware (Parallel - Lower Priority)

6. **Apply to hardware funding** - NSIC, AFRL STAR, DIU CSO (when opportunities arise)
7. **University partner outreach** - For NASA CSLI free launch path
8. **Join AMSAT** - Explore secondary payload opportunity
9. **BitAxe payload design** - Can proceed slowly while protocol demo is priority

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

### SCRAP Implications

**Today:**
- On-chain PTLCs with Schnorr adaptor signatures: AVAILABLE
- Use for Phase 1 demo

**Future (if/when activated):**
- Lightning PTLCs: Instant settlement, lower fees
- LN-Symmetry: Simplified channel state management
- Upgrade path documented in [CHANNELS.md](../spec/CHANNELS.md)

### Activation Timeline (Speculative)

- Signature aggregation (MuSig2 in Lightning): 2025-2026
- SIGHASH_ANYPREVOUT: Unknown (requires soft fork consensus)
- Lightning PTLC deployment: 2026-2027 if primitives activated
