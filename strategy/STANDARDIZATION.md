# SCRAP/SISL Standardization Strategy

Last updated: 2025-12-29

This document outlines the path to international standardization for SCRAP (Secure Capabilities and Routed Authorization Protocol) and SISL (Secure Inter-Satellite Link).

---

## Target Standards Bodies

| Organization | Relevance | Priority |
|--------------|-----------|----------|
| CCSDS | Primary - space data systems | High |
| IETF | Internet protocols, DTN | Medium |
| IEEE | Communication standards | Low |
| 3GPP | NTN (Non-Terrestrial Networks) | Medium |
| ETSI | European standards | Low |

---

## CCSDS (Consultative Committee for Space Data Systems)

### Overview

CCSDS is the international standards body for space data systems, founded in 1982. Standards are developed through member agency participation.

| Component | Details |
|-----------|---------|
| Member Agencies | 11 (NASA, ESA, JAXA, CNES, CSA, DLR, ASI, UKSA, ROSCOSMOS, CNSA, KARI) |
| Observer Agencies | 33 |
| Industrial Associates | 141 |
| Secretariat | NASA HQ, Washington DC |

### Target Area: Space Internetworking Services (SIS)

| Field | Value |
|-------|-------|
| Area Director | Tomaso de Cola |
| Deputy | Ivica Ristovski |
| Scope | End-to-end communications across heterogeneous networks |
| OSI Layers | Network through Application (Layers 3-7) |

**Working Groups:**

| Group | Chair | Focus | SCRAP/SISL Relevance |
|-------|-------|-------|---------------------|
| SIS-DTN | Robert Durst | Bundle Protocol, store-and-forward | Delay-tolerant SCRAP messaging |
| SIS-CFDPV1 | Felix Flentge | File delivery protocol | Large payload transfer |
| SIS-MIVA | Flak Schiffner | Motion imagery and voice | Real-time applications |
| SIS-VOICE | - | Voice communications | Audio relay |

**Why SIS Area:**
- SCRAP/SISL addresses network-layer interoperability
- Focus on heterogeneous network interconnection
- Application-layer protocol development
- Direct fit for "communications among multiple spacecraft"

---

### Standards Development Process

| Stage | Document Color | Description | Typical Duration |
|-------|---------------|-------------|------------------|
| 1 | White | Concept Paper - informal suggestion | 0-9 months |
| 2 | White Book | Preliminary draft, New Work Item | 6-12 months |
| 3 | Red Book | Technically mature, agency review | 12-18 months |
| 4 | Blue Book | Recommended Standard (normative) | Final |
| 4 | Green Book | Informational Report | Final |

**Document Types:**

| Type | Purpose | Binding |
|------|---------|---------|
| Blue Book | Recommended Standard | Normative |
| Magenta Book | Recommended Practice | Best practices |
| Green Book | Informational Report | Guidance |
| Orange Book | Experimental | Trial specification |
| Yellow Book | Administrative Record | Procedures |

---

### Proposal Process

**Step 1: Identify Sponsoring Agency**
- NASA (US) - Primary target
- ESA (Europe) - Alternative path
- Contact CCSDS Customer Relations function

**Step 2: Submit Concept Paper**
- Informal technical suggestion
- Maximum 9-month validity
- Describes problem and proposed solution

**Step 3: Birds of a Feather (BOF) Session**
- Develops formal work proposal
- Estimates resources required
- Identifies potential participants

**Step 4: New Work Item (NWI) Proposal**
- Formal proposal to Management Council
- Requires sponsoring agency support
- Working Group assignment

**Step 5: Document Development**
- White Book → Red Book → Blue/Green Book
- Agency reviews at each stage
- Consensus-based approval

---

### SCRAP/SISL Standardization Plan

**Year 1: Foundation**
| Activity | Target | Document |
|----------|--------|----------|
| Concept Paper | Q2 2026 | SCRAP/SISL overview |
| BOF Request | Q3 2026 | SIS Area meeting |
| NWI Proposal | Q4 2026 | Formal work item |

**Year 2: Development**
| Activity | Target | Document |
|----------|--------|----------|
| White Book | Q2 2027 | SCRAP Protocol Specification |
| White Book | Q2 2027 | SISL Link Security |
| Agency Review | Q4 2027 | Red Book preparation |

**Year 3+: Standardization**
| Activity | Target | Document |
|----------|--------|----------|
| Red Book | Q2 2028 | Formal review cycle |
| Blue Book | 2029+ | Recommended Standard |

---

### Related CCSDS Standards

| Document | Title | Relevance |
|----------|-------|-----------|
| CCSDS 133.0-B | Space Packet Protocol | SPP transport binding |
| CCSDS 355.0-B | Space Data Link Security | SDLS alignment |
| CCSDS 734.2-B | Bundle Protocol | DTN integration |
| CCSDS 727.0-B | CCSDS File Delivery Protocol | File transfer |
| CCSDS 732.0-B | IP over CCSDS | IP transport binding |

---

## IETF Standards

### Delay-Tolerant Networking (DTN)

| RFC | Title | Relevance |
|-----|-------|-----------|
| RFC 9171 | Bundle Protocol Version 7 | Message encapsulation |
| RFC 9172 | Bundle Protocol Security | Security framework |
| RFC 9173 | BPSec | Integrity and confidentiality |
| RFC 9174 | DTN TCP CL | Ground segment |
| RFC 9175 | DTN UDP CL | Ground segment |

**SCRAP/SISL Integration:**
- SCRAP messages can be encapsulated in Bundle Protocol
- SISL provides link-layer security (complementary to BPSec)
- DTN addresses store-and-forward for intermittent connectivity

### Working Groups

| Group | Focus | Relevance |
|-------|-------|-----------|
| dtn | Delay-Tolerant Networking | DTN binding |
| cfrg | Crypto Forum | Cryptographic review |
| rats | Remote ATtestation procedureS | Device attestation |

---

## 3GPP Non-Terrestrial Networks (NTN)

### Overview

3GPP is developing standards for satellite integration with 5G/6G.

| Release | Features | Timeline |
|---------|----------|----------|
| Rel-17 | Basic NTN support | 2022 |
| Rel-18 | Enhanced NTN, IoT-NTN | 2024 |
| Rel-19 | Advanced NTN | 2025 |
| Rel-20 | 6G-NTN integration | 2027+ |

### Relevance to SCRAP/SISL

| Feature | 3GPP Approach | SCRAP/SISL Approach |
|---------|---------------|-------------------|
| Authentication | 5G-AKA | X3DH |
| Authorization | Network slicing | Capability tokens |
| Encryption | SNOW, AES | AES-256-GCM |
| ISL | Not specified | SISL |

**Opportunity:** SCRAP/SISL could complement 3GPP NTN for inter-constellation coordination.

---

## IEEE Standards

### Relevant Standards

| Standard | Title | Relevance |
|----------|-------|-----------|
| IEEE 802.11 | Wireless LAN | Ground segment |
| IEEE 1588 | Precision Time Protocol | Time sync |
| IEEE 2030.5 | Smart Energy Profile | IoT integration |

### IEEE Aerospace & Electronic Systems Society

- Technical Committee on Aerospace Communications
- Potential venue for SISL physical layer standards

---

## ESA ISL Standardization Initiative

### ARTES FPE 1A.116

| Field | Value |
|-------|-------|
| Program | ARTES (Advanced Research in Telecommunications Systems) |
| Project | Towards Standardised RF ISL Solutions |
| URL | https://connectivity.esa.int/projects/towards-standardised-rf-intersatellite-link-solutions |
| Focus | Physical and digital ISL interface commonality |

**Objectives:**
1. Establish commonality in physical and digital ISL interfaces
2. Define consolidated RF ISL system architectures
3. Propose technology standards for ISL value chain
4. Framework for interoperation and technology reuse

**Alignment:** SCRAP transport bindings (Section 16) directly support this standardization goal.

---

## Standardization Action Items

### Immediate (Q1 2026)

1. **CCSDS Contact** - Identify NASA SCaN point of contact for SIS Area
2. **ESA Engagement** - Connect with ARTES ISL standardization team
3. **Concept Paper Draft** - Prepare SCRAP/SISL technical overview

### Near-Term (2026)

1. **BOF Request** - Submit request for SIS Area BOF session
2. **IETF Review** - Present SISL security approach to cfrg
3. **Industry Associates** - Consider CCSDS Industrial Associate membership

### Medium-Term (2027-2028)

1. **White Book** - Complete SCRAP protocol specification
2. **Reference Implementation** - Open-source implementation for validation
3. **Interoperability Testing** - Multi-vendor demonstrations

---

## Participation Options

### CCSDS

| Level | Requirements | Benefits |
|-------|--------------|----------|
| Member Agency | Government/quasi-government | Voting rights, leadership |
| Observer Agency | Government/quasi-government | Direct input, no vote |
| Industrial Associate | Any organization | Meeting access, contribution |

**Cost:** Industrial Associate membership varies by organization size.

### IETF

| Level | Requirements | Cost |
|-------|--------------|------|
| Individual | None | Free |
| Working Group | IETF participation | Meeting fees |
| Author | Draft submission | None |

---

## Key Contacts and Resources

### CCSDS

| Resource | URL |
|----------|-----|
| CCSDS Homepage | https://ccsds.org |
| SIS Area | https://ccsds.org/publications/sis/ |
| Standards Process | https://ccsds.org/publications/standardsdevprocess/ |
| Participation | https://ccsds.org/participation/ |
| Contact | https://ccsds.org/contact_us/ |

### IETF

| Resource | URL |
|----------|-----|
| IETF Homepage | https://www.ietf.org |
| DTN WG | https://datatracker.ietf.org/wg/dtn/about/ |
| CFRG | https://datatracker.ietf.org/rg/cfrg/about/ |

### ESA

| Resource | URL |
|----------|-----|
| ARTES | https://connectivity.esa.int |
| ISL Project | https://connectivity.esa.int/projects/towards-standardised-rf-intersatellite-link-solutions |

### 3GPP

| Resource | URL |
|----------|-----|
| 3GPP Homepage | https://www.3gpp.org |
| NTN Specifications | https://www.3gpp.org/technologies/ntn |

---

## References

- CCSDS: [Organization and Processes (Yellow Book)](https://public.ccsds.org/Pubs/A02x1y0.pdf)
- CCSDS: [SIS Area Overview](https://ccsds.org/publications/sis/)
- ESA: [ARTES ISL Standardization](https://connectivity.esa.int/projects/towards-standardised-rf-intersatellite-link-solutions)
- IETF: [RFC 9171 - Bundle Protocol v7](https://www.rfc-editor.org/rfc/rfc9171)
- 3GPP: [TR 38.811 - Study on NTN](https://www.3gpp.org/ftp/Specs/archive/38_series/38.811/)

---

*Document maintained for SCRAP/SISL standardization tracking. Last updated: 2025-12-29.*
