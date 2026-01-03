# Artificial Ground Station (AGS) Satellite Specification Proposal

## Executive Summary

This document specifies a dedicated relay satellite designed to bridge the frequency gap between Earth Observation (EO) satellites and modern ISL-enabled mega-constellations. The AGS satellite receives standard EESS X-band and S-band downlinks from higher-orbit satellites and relays data to ground via optical ISL through Starlink, SpaceLink, or Kepler networks.

## Problem Statement

Existing EO satellites transmit on ITU-allocated Earth Exploration Satellite Service (EESS) frequencies:
- **X-band**: 8.025-8.4 GHz (primary, 100-800 Mbps typical)
- **S-band**: 2.2-2.3 GHz (legacy, 2-50 Mbps typical)
- **Ka-band**: 25.5-27 GHz (emerging, 1+ Gbps)

Modern ISL constellations (Starlink, Kuiper, SpaceLink) use incompatible frequencies:
- **Optical**: 1550 nm laser (proprietary terminals required)
- **Ka-band ISL**: 23 GHz (different allocation than EESS Ka)

This frequency mismatch prevents opportunistic relay of EO data through mega-constellation infrastructure, leaving EO satellites dependent on sparse ground station networks with limited contact windows.

## Mission Concept

```
                    ┌─────────────────┐
                    │  EO Satellite   │
                    │  (Higher Orbit) │
                    │   X-band Tx     │
                    └────────┬────────┘
                             │ 8.1 GHz EESS Downlink
                             ▼
                    ┌─────────────────┐
                    │  AGS Satellite  │◄───── This Proposal
                    │  X-band Rx      │
                    │  Optical ISL Tx │
                    └────────┬────────┘
                             │ Optical ISL (25-100 Gbps)
                             ▼
                    ┌─────────────────┐
                    │ ISL Constellation│
                    │ (Starlink/etc)  │
                    └────────┬────────┘
                             │ Ku/Ka Ground Link
                             ▼
                    ┌─────────────────┐
                    │ Ground Station  │
                    └─────────────────┘
```

## Orbital Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Altitude | 350-400 km | Below most EO satellites (500-800 km), maximizes upward coverage |
| Inclination | 97.8° (SSO) | Matches majority of EO satellite orbits; minimizes slew rate requirements |
| LTAN | 10:30 or 13:30 | Offset from primary EO LTAN clusters |
| Constellation | 12 satellites, 3 planes | Global coverage with <15 min revisit |
| Lifetime | 5 years | Balances cost vs atmospheric drag at low altitude |

### SSO Orbit Selection Rationale

The choice of sun-synchronous orbit (SSO) is driven by **EO satellite slew rate constraints**, not just coverage:

1. **~80% of EO satellites are in SSO** (79.5% per database) - By matching their orbit type, AGS is co-rotating with target satellites
2. **Co-rotating geometry reduces slew rate by 10x** - From ~1.1 °/s (ground station) to 0.03-0.09 °/s
3. **Enables use of existing nadir-pointing antennas** - EO satellites don't need modifications
4. **Extends contact windows** - From 8-12 min (ground) to 20-100+ min (co-rotating LEO-LEO)

See Appendix C for detailed slew rate analysis.

### Altitude Trade Study

| Altitude | Pros | Cons |
|----------|------|------|
| 300 km | Maximum upward coverage cone | High drag, 2-3 year lifetime |
| 400 km | Good coverage, 5+ year lifetime | Some EO satellites below this altitude |
| 500 km | Minimal drag | Reduced coverage of 500-600 km EO band |

**Selected: 350-400 km** - Optimal balance for covering the dense 500-800 km EO population.

## Uplink Receiver Specifications

### Primary: X-band EESS Receiver

| Parameter | Specification |
|-----------|---------------|
| Frequency Range | 8.025 - 8.4 GHz |
| Bandwidth | 375 MHz (full EESS allocation) |
| Antenna Type | Electronically steered phased array |
| Antenna Aperture | 0.5 m equivalent |
| Antenna Gain | 32 dBi peak |
| Scan Range | ±60° from zenith (full upward hemisphere) |
| Simultaneous Beams | 4 independent |
| G/T | 10.2 dB/K | 32 dBi gain, 150 K noise |
| Polarization | RHCP and LHCP (dual-pol capable) |
| System Noise Temperature | 150 K |
| Maximum Data Rate | 800 Mbps per beam, 2 Gbps aggregate |

### Secondary: S-band EESS Receiver

| Parameter | Specification |
|-----------|---------------|
| Frequency Range | 2.2 - 2.3 GHz |
| Bandwidth | 100 MHz |
| Antenna Type | Patch array with electronic steering |
| Antenna Gain | 18 dBi |
| Scan Range | ±70° from zenith |
| Simultaneous Beams | 2 |
| Maximum Data Rate | 150 Mbps aggregate |

### Tertiary: Ka-band EESS Receiver

| Parameter | Specification |
|-----------|---------------|
| Frequency Range | 25.5 - 27.0 GHz |
| Bandwidth | 1.5 GHz |
| Antenna Type | Phased array |
| Antenna Gain | 38 dBi |
| Scan Range | ±45° from zenith |
| Simultaneous Beams | 2 |
| Maximum Data Rate | 3 Gbps aggregate |

## ISL Downlink Specifications

### Option A: Starlink Optical Terminal

| Parameter | Specification |
|-----------|---------------|
| Terminal | Starlink Mini Laser Terminal |
| Data Rate | 25 Gbps bidirectional |
| Wavelength | 1550 nm |
| Range | 4,000 km max |
| Pointing | ±60° hemisphere coverage |
| Acquisition Time | <10 seconds |

### Option B: NASA CSP Partner (SES/Inmarsat/Telesat)

| Parameter | Specification |
|-----------|---------------|
| RF Uplink | Ka-band 26.5-27.5 GHz |
| RF Data Rate | 1-2 Gbps |
| Optical | 1550 nm, 10 Gbps (optional) |
| Target | NASA Commercial Service Provider network |
| Note | SpaceLink (original candidate) ceased operations 2022 |

### Option C: SDA OCT Standard Terminal

| Parameter | Specification |
|-----------|---------------|
| Standard | SDA OCT v4.0.0 |
| Data Rate | 2.5 Gbps (OCT-Low) or 25 Gbps (OCT-High) |
| Wavelength | 1550 nm |
| Compatibility | Kepler, Tesat, CACI terminals |

**Recommendation**: Dual-terminal configuration with Starlink optical (primary) and SDA OCT-compatible terminal (backup/redundancy for government/defense customers).

## Onboard Data Handling

| Parameter | Specification |
|-----------|---------------|
| Mass Storage | 8 TB solid-state (radiation-hardened) |
| Buffer Architecture | Ring buffer with priority queuing |
| Processing | Real-time protocol conversion (CCSDS to IP) |
| Encryption | AES-256 for all stored/relayed data |
| Latency | <50 ms store-and-forward |
| Throughput | 5 Gbps sustained internal bus |

### Data Flow Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  X-band Rx  │───►│   CCSDS     │───►│   Buffer    │───►│  Optical    │
│  Frontend   │    │   Decoder   │    │   Manager   │    │  ISL Tx     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
                          │                  │
                          ▼                  ▼
                   ┌─────────────┐    ┌─────────────┐
                   │  Metadata   │    │  Priority   │
                   │  Extraction │    │  Scheduler  │
                   └─────────────┘    └─────────────┘
```

## Link Budget Analysis

### Link Budget Formula

```
FSPL (dB) = 32.44 + 20·log₁₀(d_km) + 20·log₁₀(f_MHz)
C/N₀ (dBHz) = EIRP(dBW) - FSPL + G/T + 228.6
```

### Uplink: Typical EO Satellite to AGS

**Scenario**: 600 km EO satellite to 400 km AGS (200 km slant range at zenith)

| Parameter | Value | Notes |
|-----------|-------|-------|
| EO Tx Power | 10 W (40 dBm) | Typical X-band SSPA |
| EO Antenna Gain | 6 dBi | Nadir-pointing, used for ground |
| EIRP | 16 dBW (46 dBm) | |
| Frequency | 8.2 GHz | |
| Path Loss | 156.7 dB | FSPL = 32.44 + 46.0 + 78.3 |
| AGS G/T | 10.2 dB/K | 32 dBi - 10·log₁₀(150K) |
| C/N₀ | 98.1 dBHz | 16 - 156.7 + 10.2 + 228.6 |
| Required Eb/N₀ | 4 dB | 8PSK, rate 3/4 (DVB-S2) |
| Bandwidth | 150 MHz | |
| **Achievable Rate** | **300+ Mbps** | With 6 dB margin |

### Uplink: High-Power EO Satellite

**Scenario**: COSMO-SkyMed class (48 dBW EIRP) at 620 km to AGS at 400 km

| Parameter | Value | Notes |
|-----------|-------|-------|
| EIRP | 48 dBW | Verified from database |
| Slant Range | 300 km | Off-zenith geometry |
| Path Loss | 160.3 dB | FSPL at 300 km |
| C/N₀ | 126.5 dBHz | Excellent link margin |
| **Achievable Rate** | **800 Mbps** | Limited by EO Tx bandwidth |

### Downlink: AGS to Starlink

| Parameter | Value |
|-----------|-------|
| Link Type | Optical ISL |
| Data Rate | 25 Gbps |
| Range | Up to 4,000 km |
| Availability | >99% (multiple Starlink satellites in view) |

## Spacecraft Bus Specifications

| Parameter | Specification |
|-----------|---------------|
| Mass | 150-200 kg |
| Form Factor | ESPA Grande compatible |
| Power | 500 W EOL |
| Solar Array | Deployable, body-mounted hybrid |
| Battery | 60 Ah Li-ion |
| Propulsion | Electric (Hall thruster), 300 m/s ΔV |
| ADCS | 3-axis stabilized, 0.1° pointing |
| Design Life | 5 years |

## Concept of Operations

### Autonomous Target Acquisition

1. AGS maintains onboard catalog of EO satellites with:
   - TLE/ephemeris data (updated via ISL)
   - Transmission schedules (if published)
   - Frequency/modulation parameters

2. When EO satellite enters coverage cone:
   - Phased array steers beam to predicted position
   - Wideband search for carrier acquisition
   - Automatic frequency/symbol rate detection
   - CCSDS frame synchronization

3. Data capture and relay:
   - Buffer incoming data stream
   - Tag with source satellite ID, timestamp, signal quality
   - Queue for next ISL contact (typically <30 seconds)

### Coordination Modes

| Mode | Description | Data Sovereignty |
|------|-------------|------------------|
| **Opportunistic** | Receive any detectable EESS signal | Encrypted relay, keys held by satellite operator |
| **Scheduled** | Pre-coordinated contacts | Dedicated buffer allocation |
| **Priority** | Emergency/time-critical | Preemptive relay, minimal latency |

### Ground Segment Interface

- Data delivered via Starlink/SpaceLink ground infrastructure
- API for satellite operators to:
  - Register satellites and frequencies
  - Retrieve captured data
  - Schedule priority contacts
  - Monitor relay statistics

## Regulatory Considerations

### Current ITU Allocation Status

The fundamental regulatory challenge for AGS is that **X-band EESS (8.025-8.4 GHz) is allocated only for space-to-Earth links**. There is currently no ITU allocation for space-to-space reception in this band.

| Band | Current ITU Allocation | Space-to-Space Status |
|------|------------------------|----------------------|
| X-band 8.025-8.4 GHz | EESS (space-to-Earth) | **Not allocated** |
| S-band 2.2-2.3 GHz | EESS (space-to-Earth) | **Not allocated** |
| Ka-band 18.1-18.6 GHz | FSS | Allocated at WRC-23 |
| Ka-band 27.5-30 GHz | FSS | Allocated at WRC-23 |
| Optical (1550 nm) | Unregulated | No allocation required |

### WRC-23 Outcomes

The World Radiocommunication Conference 2023 (Agenda Item 1.17) established a regulatory framework for inter-satellite links—but **only in Ka-band frequencies**:

> "WRC-23 allocated Ka-band frequencies to inter-satellite services for space research, space operation and Earth-observing satellite applications... enabling FSS satellites in higher orbits to serve as relays for satellites operating in low Earth orbit."

**X-band EESS was not included** in WRC-23 inter-satellite allocations due to:

1. **Incumbent protection**: X-band 8 GHz shares spectrum with terrestrial fixed/mobile services
2. **Deep space sensitivity**: Adjacent band 8.4-8.45 GHz hosts extremely sensitive deep space research receivers
3. **No advocacy**: EO satellite operators have not historically pushed for space-to-space allocation
4. **Complexity**: EESS frequencies are chosen to study natural phenomena at frequencies fixed by laws of nature—unlike commercial bands, they cannot easily be relocated

### Historical Context: No Explicit Rejections

Research indicates that AGS-like concepts have **not been explicitly rejected** by ITU or FCC for interference reasons. The barriers are structural rather than adversarial:

- **SpaceLink** (2020-2022): Collapsed due to financial issues, not regulatory rejection. Had valid FCC license and ITU filings through 2028, plus 21 GHz of Ka-band spectrum from Audacy acquisition.
- **Audacy** (2017-2020): Failed to secure funding; spectrum rights were acquired by SpaceLink.
- **NASA TDRSS**: Operates under government spectrum allocations not available to commercial operators.

The pattern shows **market timing and funding** have been the primary obstacles, not regulatory rejection.

### Regulatory Gap Analysis

The AGS concept falls into an **untested regulatory category**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ITU Radio Regulations Gap                        │
├─────────────────────────────────────────────────────────────────────┤
│  Allocated:     Earth Station receiving EESS (space-to-Earth)       │
│  Allocated:     Space Station transmitting EESS (space-to-Earth)    │
│  NOT Allocated: Space Station receiving EESS (space-to-space)  ◄────│
└─────────────────────────────────────────────────────────────────────┘
```

### Regulatory Pathway Options

#### Option 1: New ITU Allocation (Recommended for Long-Term)

| Step | Action | Timeline |
|------|--------|----------|
| 1 | National administration (US/EU) proposes WRC-27 agenda item | 2025 |
| 2 | ITU-R Study Group 7 conducts sharing studies | 2025-2027 |
| 3 | WRC-27 considers allocation for X-band space-to-space | 2027 |
| 4 | National implementation of new allocation | 2028 |

**Pros**: Clear legal basis, international recognition
**Cons**: 3-4 year timeline, uncertain outcome

#### Option 2: Receive-Only Interpretation

ITU Radio Regulations generally do not require coordination for **receive-only earth stations**. A legal argument could extend this to "receive-only space stations":

- AGS causes no interference (receive-only in EESS bands)
- AGS does not claim protection from interference
- Transmissions are on separately-allocated optical/Ka ISL bands

**Pros**: Immediate deployment possible
**Cons**: Untested legal theory, may face challenges from incumbent operators

#### Option 3: Bilateral/Multilateral Agreements

Negotiate directly with national administrations operating EO satellites:

- US (NASA, NOAA, NRO commercial partners)
- ESA member states
- JAXA (Japan)
- CSA (Canada)
- ISRO (India)

**Pros**: Faster than WRC process, builds coalition
**Cons**: Patchwork coverage, doesn't address ITU allocation gap

#### Option 4: Operate Under Existing EESS Authorization

If AGS operator also operates EO satellites, the space-to-space link could potentially be characterized as an extension of existing EESS operations under the same authorization.

**Pros**: Leverages existing spectrum rights
**Cons**: Requires vertical integration, may not cover third-party EO satellites

### Recent Regulatory Developments

**NTIA/NASA 18 GHz Recommendation (2025)**: US agencies recommended FCC adopt 18 GHz for commercial space relay to replace TDRSS. This demonstrates government interest in commercial relay but focuses on Ka-band, not X-band.

**WRC-27 Preparation**: ITU Study Groups are examining expansion of inter-satellite allocations to additional bands (L-band, C-band). X-band EESS is not currently on the study agenda but could be proposed.

### Recommended Regulatory Strategy

```
Phase 1 (Immediate):    Deploy using Option 2 (receive-only interpretation)
                        + Option 3 (bilateral agreements with key EO operators)

Phase 2 (Parallel):     Advocate for WRC-27 agenda item on X-band space-to-space
                        Build coalition with EO satellite operators

Phase 3 (2027+):        Transition to formal ITU allocation if approved
```

### Spectrum Summary

| Band | AGS Function | Regulatory Status | Risk Level |
|------|--------------|-------------------|------------|
| X-band 8.025-8.4 GHz | Uplink Rx | Unallocated for S2S | **High** |
| S-band 2.2-2.3 GHz | Uplink Rx | Unallocated for S2S | **High** |
| Ka-band 25.5-27 GHz | Uplink Rx | Allocated (WRC-23) | Low |
| Optical 1550 nm | ISL Downlink | Unregulated | None |

### Data Handling Compliance

- Encrypted relay ensures data sovereignty
- Operators must opt-in or register satellites
- GDPR compliance for EU operator data
- ITAR compliance for US-origin EO data routing
- Data retention policies per customer agreement

## Cost Estimate

| Item | Cost (USD) |
|------|------------|
| Spacecraft Bus | $8-12M |
| X-band Phased Array | $3-5M |
| Optical ISL Terminal | $2-4M |
| Integration & Test | $2-3M |
| Launch (rideshare) | $3-5M |
| **Per Satellite Total** | **$18-29M** |
| **12-Satellite Constellation** | **$220-350M** |

### Revenue Model

| Service | Price Point |
|---------|-------------|
| Opportunistic relay | $0.10/MB |
| Scheduled contact | $500/pass |
| Priority/emergency | $2,000/pass |
| Dedicated capacity | $50K/month/satellite |

**Break-even**: ~3 years at 30% capacity utilization

## Development Schedule

| Phase | Duration | Milestones |
|-------|----------|------------|
| Phase A: Concept Study | 6 months | Requirements finalized, PDR |
| Phase B: Preliminary Design | 9 months | CDR, long-lead procurement |
| Phase C: Detailed Design | 12 months | Qualification models |
| Phase D: Integration & Test | 12 months | Proto-flight unit complete |
| Phase E: Launch & Commissioning | 3 months | First satellite operational |
| Constellation Deployment | 18 months | Full 12-satellite constellation |

**First Launch**: T+39 months from program start
**Full Capability**: T+57 months from program start

## Technical Analyses Deferred to Phase A

The following detailed analyses are required during Phase A (Concept Study) and are not included in this initial proposal:

| Analysis | Description | Phase A Deliverable |
|----------|-------------|---------------------|
| Thermal Analysis | Heat dissipation from phased array, solar loading | Thermal model, radiator sizing |
| Detailed Mass Budget | Component-level mass breakdown | Mass margin analysis |
| Power Budget | Operational modes, eclipse performance | Battery/solar array sizing |
| Doppler Compensation | Frequency tracking requirements for LEO-LEO | Receiver AFT specification |
| Antenna Pattern Analysis | Sidelobe levels, interference potential | Pattern measurements/simulation |
| Orbit Maintenance | Drag compensation, station-keeping ΔV | Propellant budget |
| Radiation Environment | Total ionizing dose, SEU rates | Shielding/parts selection |
| Ground Segment Architecture | Data routing, customer API design | System architecture document |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **X-band regulatory challenge** | **High** | **High** | Receive-only interpretation + bilateral agreements; pursue WRC-27 allocation |
| S-band regulatory challenge | High | Medium | Same as X-band; lower priority band |
| ISL terminal availability | Medium | High | Dual-source (Starlink + SDA OCT) |
| Phased array performance | Low | High | Heritage X-band technology |
| EO satellite cooperation | Medium | Medium | Opportunistic mode as fallback |
| Orbital debris at 350 km | Low | High | Active collision avoidance, deorbit capability |
| Starlink policy changes | Medium | High | SDA OCT backup terminal |
| Market timing (SpaceLink/Audacy precedent) | Medium | High | Phased deployment, anchor customers before full constellation |
| Deep space interference complaints | Low | Medium | Frequency coordination with DSN operators; avoid 8.4-8.45 GHz |

## Conclusion

The AGS satellite concept addresses a fundamental gap in the current space infrastructure by bridging incompatible frequency allocations between EO satellites and ISL mega-constellations. Key advantages:

1. **No modification to existing EO satellites** - Works with current X-band/S-band transmitters
2. **Leverages commercial ISL infrastructure** - No dedicated ground segment required
3. **Scalable capacity** - Constellation can grow with demand
4. **Fast time-to-data** - Minutes vs hours for traditional ground station passes
5. **Global coverage** - No geographic limitations

The estimated $220-350M constellation cost compares favorably to building equivalent ground station infrastructure while providing superior coverage and latency characteristics.

### Critical Path: Regulatory

The primary risk to AGS deployment is **regulatory uncertainty** around X-band space-to-space reception. While no proposals have been explicitly rejected by ITU or FCC, the absence of allocation creates ambiguity. The recommended strategy is:

1. **Near-term**: Deploy under receive-only interpretation with bilateral operator agreements
2. **Mid-term**: Advocate for WRC-27 agenda item to formalize X-band space-to-space allocation
3. **Fallback**: If X-band proves untenable, pivot to Ka-band-only operation (leveraging WRC-23 allocation) which would require EO satellites to add Ka-band transmitters—reducing the "no modification" advantage but remaining technically viable

The technical and economic case for AGS is strong. The regulatory pathway, while challenging, has no fundamental blockers—only gaps that require proactive engagement with ITU and national administrations.

## References

### Standards and Regulations
1. ITU Radio Regulations, Article 5 - Frequency Allocations
2. CCSDS 131.0-B-4 - TM Synchronization and Channel Coding
3. SDA OCT Standard v4.0.0 - Optical Communications Terminal
4. ECC Report 115, "Use of the frequency band 8025-8400 MHz by EESS"
5. ITU-R Report SA.2430-0, "Technical studies for establishing in-band power limits" (2018)

### ITU/Regulatory Sources
6. ITU, "Inter-satellite links: Why it's important to expand usage in available spectrum" (October 2023) - https://www.itu.int/hub/2023/10/inter-satellite-links-why-its-important-to-expand-usage-in-available-spectrum/
7. ITU, "WRC-23: International regulation of satellite services" (February 2023)
8. NTIA, "NTIA, NASA Recommend 18 GHz Band Allocation to Bolster Commercial Space Activities" (May 2025) - https://www.ntia.gov/blog/2025/ntia-nasa-recommend-18-ghz-band-allocation-bolster-commercial-space-activities

### Industry Sources
9. SpaceNews, "The Space Relayers: NASA's latest bet on the private sector is starting to take shape" (2024)
10. Seradata, "SpaceLink optical data-relay constellation hangs in balance after EOS cuts financial cord" (November 2022)

### Technical Specifications (Not Publicly Available)
11. SpaceX Starlink laser ISL specifications - inferred from press releases and FCC filings
12. NASA CSP contract documentation - available via NASA SEWP/procurement channels

## Appendix A: EO Satellite Population Analysis

Based on current database analysis (December 2025):

| Orbit Band | EO Satellites | X-band Tx Capable | Potential Daily Contacts |
|------------|---------------|-------------------|-------------------------|
| 500-550 km | 263 | ~130 | 15-20 per AGS |
| 550-600 km | 239 | ~120 | 15-18 per AGS |
| 600-700 km | 177 | ~100 | 12-15 per AGS |
| 700-800 km | 126 | ~65 | 8-12 per AGS |
| **Total** | **805** | **~416** | **50-65 per AGS** |

12-satellite AGS constellation: **600-780 daily contact opportunities**

*Note: X-band Tx counts based on satellites with documented 8.0-8.4 GHz downlink transmitters in database. Actual numbers may be higher as many EO satellites have X-band capability not recorded in public databases.*

## Appendix B: Frequency Compatibility Matrix

| EO Tx Band | AGS Rx | Compatible | Notes |
|------------|--------|------------|-------|
| X-band 8.025-8.4 GHz | X-band Rx | Yes | Primary design point |
| S-band 2.2-2.3 GHz | S-band Rx | Yes | Legacy support |
| Ka-band 25.5-27 GHz | Ka-band Rx | Yes | Emerging capability |
| Ku-band 13.4-14 GHz | - | No | Not included in baseline |
| L-band 1.7 GHz | - | No | Low data rate, not prioritized |

## Appendix C: Contact Geometry

```
        EO Satellite @ 600 km
              ◯
             /│\
            / │ \
           /  │  \     Coverage Cone
          /   │   \    (±60° from zenith)
         /    │    \
        /     │     \
       /      │      \
      ────────●────────  AGS @ 400 km
              │
              │ 200 km
              │
      ════════════════   Earth Surface
```

### Geometry Parameters

| Parameter | Value |
|-----------|-------|
| Maximum slant range (60° from zenith) | 346 km |
| Minimum range (zenith) | 200 km |
| Coverage cone radius at EO altitude | 346 km |
| Coverage diameter | 693 km |

### Contact Duration Analysis

Contact duration depends on relative orbital geometry:

| Scenario | Relative Velocity | Contact Duration |
|----------|-------------------|------------------|
| Co-rotating, similar inclination | 0.1-0.5 km/s | 20-100+ minutes |
| Counter-rotating | 15+ km/s | <1 minute |
| Typical (crossing orbits) | 1-3 km/s | 4-12 minutes |

**Note**: Unlike ground station passes (2-10 minutes), LEO-LEO contacts can be significantly longer when satellites are in similar orbital planes, or much shorter for counter-rotating passes.

### EO Satellite Slew Rate Requirements

A critical consideration is whether EO satellites can track the AGS during a pass. Most EO satellites use body-fixed or slowly-steerable antennas designed for ground station contacts.

**Slew rate analysis** (at 200 km minimum slant range):

| Orbital Geometry | Relative Velocity | Required Slew Rate | EO Satellite Compatibility |
|------------------|-------------------|-------------------|---------------------------|
| **Co-rotating SSO** | 0.1-0.3 km/s | 0.03-0.09 °/s | ✓ All platforms (10x easier than ground) |
| Similar inclination | 0.3-0.8 km/s | 0.09-0.23 °/s | ✓ All platforms |
| Crossing polar | 1.5-3.0 km/s | 0.43-0.86 °/s | ✓ Most platforms |
| Counter-rotating | 14-16 km/s | 4.0-4.6 °/s | ✗ Only agile platforms |

**Comparison to ground station tracking**: ~1.1 °/s at 400 km slant range

**Why SSO orbit is optimal**: The majority of EO satellites (~80%, verified 79.5% in database) operate in sun-synchronous orbits. By placing the AGS constellation in SSO, most target satellites are co-rotating, resulting in:

1. **Lower slew rates** than ground station passes (0.03-0.09 °/s vs 1.1 °/s)
2. **Longer contact windows** (20-100+ minutes vs 8-12 minutes for ground)
3. **No attitude maneuver required** for satellites with nadir-pointing antennas

**Limitation**: Non-SSO EO satellites have crossing or incompatible geometry:

| EO Orbit Type | Satellites | Relative Velocity | Slew Rate | AGS Compatible? |
|---------------|------------|-------------------|-----------|-----------------|
| SSO (96-100°) | 602 (79.5%) | 0.1-0.3 km/s | 0.03-0.09 °/s | ✓ Yes |
| Mid-inclination (45-55°) | 47 (6.2%) | 6-8 km/s | 1.7-2.3 °/s | △ Agile only |
| Other polar | 95 (12.5%) | 1-5 km/s | 0.3-1.4 °/s | ✓ Most platforms |
| **Equatorial (<15°)** | **6 (0.8%)** | **11.5 km/s** | **3.3 °/s** | **✗ No** |

**Equatorial satellites incompatible with SSO AGS**: The 97.8° inclination difference creates 11.5 km/s relative velocity, requiring 3.3 °/s slew rate at closest approach—exceeding most spacecraft capabilities.

Known equatorial EO satellites (not serviceable by SSO AGS):
- LAPAN-A2 (Indonesia, 6°)
- RAZAKSAT (Malaysia, 9°)
- TELEOS-2 (Singapore, 10°)
- DS-EO, KENT RIDGE 1 (Singapore)

**Mitigation options**:
1. Accept limitation (only 6 satellites, <1% of fleet)
2. Future equatorial AGS plane (adds cost, serves small market)
3. Use GEO relay (TDRS, commercial) for equatorial missions
