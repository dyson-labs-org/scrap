# SCRAP/SISL Regulatory Landscape

Last updated: 2025-12-29

This document tracks regulatory developments, spectrum allocation, and policy considerations relevant to SCRAP (Secure Capabilities and Routed Authorization Protocol) and SISL (Secure Inter-Satellite Link) deployment.

---

## FCC Spectrum Proceedings

### Satellite Spectrum Expansion (May 2025)

| Field | Value |
|-------|-------|
| Proceeding | Final Frontiers agenda |
| Spectrum | >20,000 MHz proposed for satellite broadband |
| Bands | 12.7-13.25 GHz, 42.0-42.5 GHz, 51.4-52.4 GHz, W-band (92-114 GHz) |
| Comment Deadline | July 28, 2025 (CLOSED) |
| Reply Comments | August 26, 2025 (CLOSED) |

**Key Changes:**
- Modernizing power limits from 1990s rules
- Enabling NGSO/GSO sharing improvements
- Expedited licensing for Ground-Station-as-a-Service
- SpaceX EPFD rulemaking for 10.7-30 GHz bands

**Industry Support:** Satellite Industry Association applauded the expansion as critical for "domestic technological innovation and U.S. space industry leadership."

**Relevance to SCRAP/SISL:** X-band and higher frequency ISL operations may benefit from new spectrum allocations. W-band (92-114 GHz) particularly relevant for high-bandwidth ISL.

---

## ITU Coordination

### Inter-Satellite Link Spectrum

| Band | Frequency Range | Primary Use | ITU Region |
|------|-----------------|-------------|------------|
| Ku-band | 13.4-14.5 GHz | ISL | All |
| Ka-band | 22.55-23.55 GHz | ISL | All |
| V-band | 54.25-58.2 GHz | ISL | All |
| Optical | ~1550 nm | Laser ISL | Unregulated |

**Action Items:**
1. Monitor ITU WRC-27 agenda items for ISL spectrum
2. Engage with national administration (FCC for US, Ofcom for UK) for ISL coordination
3. Consider optical ISL to avoid RF spectrum constraints

---

## Office of Space Commerce

| Field | Value |
|-------|-------|
| Agency | NOAA / Dept. of Commerce |
| URL | https://space.commerce.gov/ |
| FY2025 Budget | $75.6M proposed |
| FY2026 Budget | $10M proposed (significant reduction) |
| Director | Taylor Jordan (appointed Dec 2025) |

### Programs

**TraCSS (Traffic Coordination System for Space)**
- Space situational awareness and traffic management
- At risk in FY2026 budget proposal
- Industry coalition (AIA, Commercial Space Federation, SIA, SpaceX, Blue Origin, Amazon, Boeing) advocating for continued funding

**Commercial Data Buys**
- Updated guidance released Dec 2024
- Framework for NOAA to acquire commercial satellite data

**Relevance to SCRAP/SISL:** Space traffic coordination affects ISL operations. SCRAP could integrate with TraCSS for coordinated maneuvers.

---

## Export Control Considerations

### ITAR (International Traffic in Arms Regulations)

| Category | USML Reference | Consideration |
|----------|----------------|---------------|
| Satellite encryption | Cat XV | SISL AES-256-GCM may require license |
| Space-qualified hardware | Cat XV | CubeSat components generally EAR99 |
| Spread spectrum | Cat XI | DSSS/FHSS techniques may be controlled |

**Mitigation Strategies:**
1. Use commercial-off-the-shelf (COTS) encryption where possible
2. Seek commodity jurisdiction (CJ) determination for SISL
3. Consider EAR99 classification for open-source implementations

### EAR (Export Administration Regulations)

| ECCN | Description | Relevance |
|------|-------------|-----------|
| 5A002 | Cryptographic items | SISL encryption module |
| 5D002 | Cryptographic software | SISL/SCRAP software |
| 9A515 | Spacecraft | Complete satellite systems |

**License Exception TSR** may apply for fundamental research conducted at universities.

---

## Amateur Radio Regulations

### AX.25 Binding Considerations

| Regulation | Requirement | Impact on SCRAP |
|------------|-------------|----------------|
| FCC Part 97 | No encryption on amateur bands | SISL encryption not permitted |
| ITU Radio Regulations | Station identification | Callsign mapping required |
| IARU Band Plan | Frequency coordination | 435-438 MHz for CubeSat |

**Phase 1 Demo Approach:**
- Use amateur 70cm band (435-438 MHz) for unencrypted SCRAP messages
- Capability token signatures provide authentication (permitted)
- Encryption requires licensed spectrum (e.g., S-band, X-band)

---

## Space Debris and Sustainability

### FCC Orbital Debris Rules (2024)

| Requirement | Timeline | Impact |
|-------------|----------|--------|
| Post-mission disposal | 5 years (was 25) | Affects mission planning |
| Collision avoidance | Maneuver capability required | ISL aids coordination |
| Casualty risk | <1:10,000 for reentry | Affects deorbit strategy |

### ESA Space Debris Mitigation

| Guideline | Requirement |
|-----------|-------------|
| ECSS-U-AS-10C | Passivation at end of life |
| ISO 24113 | Space debris mitigation |

**Relevance:** SCRAP's autonomous coordination capabilities could support debris avoidance maneuvers.

---

## Cybersecurity Requirements

### NIST SP 800-171 (CUI Protection)

If SCRAP/SISL handles Controlled Unclassified Information (CUI) for government contracts:
- 110 security controls required
- CMMC Level 2 certification may be needed
- Encryption requirements align with SISL's AES-256-GCM

### Space Policy Directive 5 (SPD-5)

| Principle | Requirement |
|-----------|-------------|
| Risk-based approach | Assess threats to space systems |
| Authentication | Strong identity verification |
| Encryption | Protect data in transit/at rest |
| Anomaly detection | Monitor for intrusions |

**SCRAP/SISL Alignment:**
- SISL X3DH provides strong authentication
- AES-256-GCM encryption for data protection
- Capability tokens enable fine-grained authorization

---

## International Frameworks

### Outer Space Treaty (1967)

| Article | Requirement | Relevance |
|---------|-------------|-----------|
| I | Free exploration/use | Cross-operator cooperation enabled |
| VI | State responsibility | Operators liable for satellite actions |
| IX | Harmful contamination | Debris mitigation |

### UN Guidelines for Long-term Sustainability

| Guideline | Recommendation |
|-----------|----------------|
| A.1 | Develop national regulatory frameworks |
| A.2 | Consider safety in licensing |
| B.1 | Share orbital data |
| D.2 | Manage space debris |

---

## Recommended Regulatory Actions

### Immediate

1. **FCC Experimental License** - Apply for Part 5 experimental license for X-band ISL testing
2. **Amateur Callsign** - Obtain callsigns for Phase 1 CubeSat demo
3. **Export Classification** - Request CJ determination for SISL software

### Near-Term

1. **ITU Coordination** - Engage with NTIA for ISL spectrum coordination
2. **CMMC Preparation** - Assess CMMC Level 2 requirements for government contracts
3. **ESA Spectrum** - Coordinate with member state for European operations

### Standards Engagement

See [STANDARDIZATION.md](STANDARDIZATION.md) for CCSDS and industry standards activities.

---

## Key Contacts and Resources

| Resource | URL |
|----------|-----|
| FCC Experimental Licensing | https://www.fcc.gov/oet/els |
| NTIA Spectrum Management | https://www.ntia.doc.gov/category/spectrum-management |
| Office of Space Commerce | https://space.commerce.gov/ |
| BIS Export Controls | https://www.bis.doc.gov/ |
| DDTC (ITAR) | https://www.pmddtc.state.gov/ |
| ITU Space Services | https://www.itu.int/en/ITU-R/space/ |
| IARU Satellite Coordination | https://www.iaru.org/satellite/ |

---

## References

- FCC: [Final Frontiers Spectrum Blog](https://www.fcc.gov/news-events/blog/2025/04/04/spectrum-back-again)
- FCC: [Satellite Spectrum Expansion Fact Sheet](https://docs.fcc.gov/public/attachments/DOC-413054A1.pdf)
- Office of Space Commerce: [Homepage](https://space.commerce.gov/)
- NIST: [SP 800-171](https://csrc.nist.gov/publications/detail/sp/800-171/rev-2/final)
- White House: [Space Policy Directive 5](https://trumpwhitehouse.archives.gov/presidential-actions/memorandum-space-policy-directive-5-cybersecurity-principles-space-systems/)

---

*Document maintained for SCRAP/SISL regulatory tracking. Last updated: 2025-12-29.*
