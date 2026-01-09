# Satellite Command and Control Protocols Research

## Executive Summary

This document surveys the protocols, formats, and infrastructure used for satellite command and control (C2). Understanding these systems is essential for designing a satellite tasking library that can interface with various spacecraft types, from CubeSats to commercial imaging constellations.

---

## 1. Communication Architecture

### Link Types

Satellite communication consists of three distinct data streams:

1. **Payload Data** - Mission-specific data (imagery, sensor readings, etc.)
2. **Telemetry (TM)** - Spacecraft health and status data sent to ground
3. **Telecommand (TC)** - Instructions sent from ground to spacecraft

In most missions, the payload link is physically separated from the telemetry and telecommand (TT&C) link. The TT&C link carries the C2 traffic.

### Data Flow Architecture

```
+-----------------+     RF Link      +-----------------+
|   Spacecraft    |<---------------->|  Ground Station |
|  Flight Computer|                  |    Antenna      |
+-----------------+                  +--------+--------+
                                              |
                                     Space Data Link
                                              |
                                     +--------v--------+
                                     |  Space Link     |
                                     |  Extension (SLE)|
                                     +--------+--------+
                                              |
                                     Ground Network (IP)
                                              |
                                     +--------v--------+
                                     | Mission Control |
                                     |     Center      |
                                     +-----------------+
```

---

## 2. Radio Frequency Bands

### Band Allocations

| Band | Frequency Range | Primary Use | Characteristics |
|------|-----------------|-------------|-----------------|
| **VHF** | 144-148 MHz | CubeSat uplink/downlink | Long range, low bandwidth, good penetration |
| **UHF** | 400-450 MHz | CubeSat/SmallSat TT&C | Common for amateur satellites |
| **S-Band** | 2.0-4.0 GHz | TT&C, Deep space | Resilient, good atmospheric penetration |
| **X-Band** | 7.25-8.4 GHz | Military, Earth observation | Higher bandwidth, moderate weather sensitivity |
| **Ku-Band** | 12-18 GHz | Commercial satellite | High bandwidth, weather sensitive |
| **Ka-Band** | 26.5-40 GHz | High-throughput data | Very high bandwidth, rain fade issues |

### Uplink vs Downlink

- **Uplink frequency > Downlink frequency** (typically)
- Reason: Satellites have power constraints; lower downlink frequencies reduce path loss
- Frequency separation prevents receiver jamming when using single antenna

### Deep Space Network Bands

NASA's Deep Space Network (DSN) progression:
- 1960s: S-band (2.0-2.3 GHz)
- 1990s: X-band (7.9-8.4 GHz uplink, 8.4-8.5 GHz downlink)
- 2000s+: Ka-band (31.8-32.3 GHz downlink)

---

## 3. Protocol Standards

### 3.1 CCSDS (Consultative Committee for Space Data Systems)

The primary international standard for space data systems, established in 1982.

#### Space Packet Protocol (CCSDS 133.0-B)

**Primary Header Structure (48 bits / 6 bytes):**

```
Bits 0-15:   Packet ID
             +-- Version (3 bits)      - Always 000 for CCSDS v1
             +-- Type (1 bit)          - 0=TM, 1=TC
             +-- Secondary Header (1 bit) - Presence flag
             +-- APID (11 bits)        - Application Process ID (0-2047)

Bits 16-31:  Packet Sequence Control
             +-- Sequence Flags (2 bits) - 00=continuation, 01=first, 10=last, 11=standalone
             +-- Sequence Count (14 bits) - Packet counter per APID (0-16383)

Bits 32-47:  Packet Data Length (16 bits) - (length in bytes) - 1
```

**Packet Structure:**
```
+------------------+------------------+-----------------+
|  Primary Header  | Secondary Header |   User Data     |
|    (6 bytes)     |   (optional)     |  (variable)     |
+------------------+------------------+-----------------+
```

**Maximum packet size:** 65,542 bytes (6-byte header + 65,536 data bytes)

#### Transfer Frame Protocol

Wraps space packets for reliable transmission:

**TC Frame Structure:**
```
+----------------+------------------+-------------+
|  Frame Header  |  Data Field      |  CRC-16     |
|   (5 bytes)    |  (variable)      |  (2 bytes)  |
+----------------+------------------+-------------+
```

Contains: Spacecraft ID, Virtual Channel ID, Frame sequence count

#### Key CCSDS Protocols

| Protocol | Function |
|----------|----------|
| **TM Space Data Link** | Telemetry framing |
| **TC Space Data Link** | Telecommand framing |
| **AOS (Advanced Orbiting Systems)** | High-rate multiplexed data |
| **USLP (Unified Space Data Link)** | Modern unified protocol |
| **CFDP (File Delivery Protocol)** | Reliable file transfer |
| **SLE (Space Link Extension)** | Ground network extension |

### 3.2 ECSS PUS (Packet Utilization Standard)

European standard (ECSS-E-ST-70-41C) defining application-layer services over CCSDS packets.

**PUS Header (added to CCSDS secondary header):**
```
+-- Service Type (8 bits)    - Identifies the service
+-- Service Subtype (8 bits) - Specific operation within service
+-- Source ID (variable)     - Originator identification
+-- Time (variable)          - Timestamp
```

**Standard Services (PUS-C, ECSS-E-ST-70-41C):**

| Service ID | Name | Purpose |
|------------|------|---------|
| 1 | Request Verification | Confirm command receipt/execution |
| 2 | Device Access | Direct hardware control |
| 3 | Housekeeping | Periodic parameter reporting |
| 4 | Parameter Statistics | Statistical parameter reporting |
| 5 | Event Reporting | Anomaly and event notification |
| 7 | Memory Management | Upload/download memory contents |
| 8 | Function Management | Execute onboard functions |
| 10 | Time Management | Synchronize spacecraft clock |
| 11 | Time-based Scheduling | Schedule future commands |
| 12 | On-board Monitoring | Parameter limit checking |
| 13 | Large Packet Transfer | Segmented data transfer |
| 14 | Real-time Forwarding | Telemetry routing control |
| 16 | On-board Storage | Data recording management |
| 17 | Test | Built-in test functions |
| 18 | On-board Control Procedure | Stored command sequences |
| 19 | Event-action | Autonomous event responses |
| 20 | Parameter Management | Parameter definition control |
| 21 | Request Sequencing | Command sequence control |
| 22 | Position-based Scheduling | Orbital position triggers |
| 23 | File Management | On-board file operations |
| 128+ | Mission-specific | Custom services |

**Example Command:** `TC[11,4]` = Time-based Scheduling Service (11), Insert Command (subtype 4)

### 3.3 AX.25 (Amateur Radio Protocol)

Data link layer protocol used extensively by CubeSats and amateur satellites.

**Frame Format:**
```
+------+-------------+-------------+---------+--------+----------+-----+
| Flag | Destination |   Source    | Control |  PID   |   Info   | FCS |
| 0x7E |  Address    |  Address    |  (1-2)  |  (1)   |(variable)|(2)  |
+------+-------------+-------------+---------+--------+----------+-----+
```

**Characteristics:**
- Addresses use amateur radio callsigns (6 bytes + SSID)
- Common modulation: 1200 baud AFSK (VHF), 9600 baud GMSK (UHF)
- No built-in forward error correction (FEC)
- Maximum frame size: 256 bytes (typical)

**Limitations:**
- Not optimized for lossy satellite links
- No native encryption support
- Alternatives emerging: NGHam (with Reed-Solomon FEC)

---

## 4. Space Link Extension (SLE)

SLE extends the space link from ground stations to mission control centers over terrestrial IP networks.

### Services

| Service | Direction | Function |
|---------|-----------|----------|
| **F-CLTU** (Forward Command Link) | Ground -> Space | Send telecommands |
| **RAF** (Return All Frames) | Space -> Ground | Receive all telemetry frames |
| **RCF** (Return Channel Frames) | Space -> Ground | Receive selected virtual channels |

### Implementation Layers

```
+-----------------------------+
|    SLE Application Layer    |  Protocol logic
+-----------------------------+
|    Encoding Layer (DEL)     |  ASN.1 BER encoding
+-----------------------------+
|    Transport Layer (TML)    |  TCP/IP transport
+-----------------------------+
```

### Adoption

Used by: NASA (DSN, SN, GN), ESA, JAXA, and commercial operators for cross-support operations.

---

## 5. Security Protocols

### CCSDS Space Data Link Security (SDLS)

Provides link-layer security for TC, TM, and AOS protocols.

**Security Services:**
1. **Authentication** - Verify command source (MAC)
2. **Encryption** - Data confidentiality (AES)
3. **Authenticated Encryption** - Both (AES-GCM)

**Security Header:**
```
+--------------+----------------+-----------------+
| Security     | Initialization | Authentication  |
| Parameter ID | Vector (96 bit)| Tag (128 bit)   |
+--------------+----------------+-----------------+
```

**Cryptographic Implementation:**
- Algorithm: AES-128 in GCM mode
- IV: 96 bits (transmitted in header)
- MAC: 128 bits

**Anti-Replay Protection:**
- Sequence counter in each frame
- Receiver maintains acceptable window
- Out-of-window frames rejected

### Key Management

- Session keys uploaded via authenticated channel
- Each key has unique Key ID
- Security Associations (SA) define per-channel security parameters

---

## 6. Command Scheduling and Reception

### Visibility Windows

Satellites can only receive commands during **visibility windows** (also called **access windows** or **contact windows**) when the spacecraft is above the horizon relative to a ground station. For LEO satellites:

- **Orbital period**: ~90 minutes
- **Typical pass duration**: 5-12 minutes (depends on elevation)
- **Passes per day per station**: 2-6 (varies with orbital inclination)

```
                    +-------------------------+
                    |      Satellite Pass     |
                    |                         |
    Horizon --------+-------------------------+-------- Horizon
                   AOS                       LOS
              (Acquisition              (Loss of
               of Signal)               Signal)
```

### Pass Prediction

Ground stations use orbital elements (Two-Line Element sets / TLEs) to predict visibility windows:

```
Pass Prediction Parameters:
+-- AOS (Acquisition of Signal) - Pass start time
+-- LOS (Loss of Signal) - Pass end time
+-- Maximum Elevation - Highest point in pass (0-90deg)
+-- Duration - Total contact time
+-- Azimuth Range - Antenna tracking path
```

Higher maximum elevation correlates with longer, higher-quality contacts. Passes below 5-10deg elevation are typically unusable due to atmospheric attenuation and ground clutter.

### Ground Station Scheduling Problem

The satellite scheduling problem is a **constraint optimization problem**:

**Inputs:**
- Satellite orbital parameters
- Ground station locations
- Task priorities and deadlines
- Antenna capabilities (band, gain, slew rate)

**Constraints:**
- One satellite per antenna at a time
- Minimum elevation requirements
- Handoff time between passes
- Power and thermal limits on spacecraft

**Objective:** Maximize task completion while meeting priority and deadline constraints.

Modern GSaaS providers (AWS Ground Station, Azure Orbital, Leaf Space) expose APIs to query available windows and reserve contacts programmatically.

### Command Types

1. **Real-time Commands** - Execute immediately upon receipt
2. **Time-tagged Commands** - Execute at specified absolute time
3. **Position-tagged Commands** - Execute at specified orbital position
4. **Stored Sequence Commands (SSC)** - Pre-loaded command scripts

### Time-tagged Commands

Due to limited contact windows, **time-tagged telecommands** are essential for autonomous satellite operation:

```
+-----------------+-----------------+-----------------+
| Execution Time  |  Command Type   |  Command Data   |
|  (absolute UTC) |    (opcode)     |  (parameters)   |
+-----------------+-----------------+-----------------+
```

The on-board computer (OBC) stores commands in a queue sorted by execution time, executing them autonomously without ground contact.

**Position-tagged commands** trigger at specific orbital positions--useful for Earth observation where data collection must begin over precise ground coordinates.

### Stored Command Queue Operations

Spacecraft maintain an on-board command queue:
- Commands uploaded during ground station passes
- Queue sorted by execution time
- Automatic execution without ground contact
- Verification via telemetry on next pass

### Typical Operations Cycle

```
+-------------+     +-------------+     +-------------+
|   Mission   |---->|   Ground    |---->|  Spacecraft |
|   Planning  |     |   Station   |     |   OBC Queue |
+-------------+     +-------------+     +-------------+
      |                   |                    |
      |  24hr schedule    |  Upload during     |  Execute
      |  generation       |  contact pass      |  autonomously
      |                   |                    |
      +------------------>+------------------->|
                                               |
+-------------+     +-------------+            |
|   Reports   |<----|  Telemetry  |<-----------+
| Verification|     |  Download   |   Next pass
+-------------+     +-------------+
```

---

## 7. Command Authorization and Security

### The Authorization Problem

Satellites must authenticate commands to ensure they originate from authorized operators. Without authentication:

- **Spoofing**: Adversary transmits malicious commands
- **Replay attacks**: Recorded legitimate commands retransmitted
- **Command injection**: Unauthorized control of spacecraft

### CCSDS Space Data Link Security (SDLS) - Detailed

SDLS (CCSDS 355.0-B) provides link-layer security through **Security Associations (SA)**:

**Security Association Parameters:**
```
Security Association:
+-- SA ID - Unique identifier for this association
+-- Service Type - Authentication, Encryption, or Authenticated Encryption
+-- Cryptographic Algorithm - e.g., AES-GCM
+-- Key ID - Reference to active session key
+-- IV Management - Counter or explicit IV
+-- Anti-Replay Window - Acceptable sequence number range
+-- SA State - Operational, Keyed, Unkeyed
```

**Authentication Flow:**

```
Ground Station                              Spacecraft
     |                                           |
     |  1. Construct TC Frame                    |
     |  2. Compute MAC = AES-GCM(Key, Frame)     |
     |  3. Append MAC + Sequence Counter         |
     |                                           |
     +-------- TC Frame + Security Trailer ----->|
     |                                           |
     |                      4. Extract MAC, SeqNum|
     |                      5. Verify SeqNum in window
     |                      6. Recompute MAC     |
     |                      7. Compare MACs      |
     |                      8. Accept or Reject  |
     |                                           |
```

**Security Services:**

| Service | Protection | Algorithm |
|---------|------------|-----------|
| Authentication Only | Integrity + Source Auth | AES-GMAC |
| Encryption Only | Confidentiality | AES-CTR |
| Authenticated Encryption | All three | AES-GCM |

**Anti-Replay Protection:**
- Each frame includes a sequence counter
- Receiver maintains a sliding window of acceptable sequence numbers
- Frames with sequence numbers outside the window are rejected
- Window prevents replay of old commands

### TRANSEC and COMSEC

Military and high-security satellites employ additional protection layers:

**COMSEC (Communications Security):**
- Encrypts the actual data payload
- Protects message content from eavesdropping
- Typically AES-256 encryption

**TRANSEC (Transmission Security):**
- Protects traffic patterns and link availability
- Makes channel appear full even when idle (traffic flow security)
- Techniques include:
  - Frequency Hopping Spread Spectrum (FHSS)
  - Direct Sequence Spread Spectrum (DSSS)
  - Burst transmission at unpredictable times

```
+----------------------------------------------------------+
|                    Security Layers                        |
+-------------------+--------------------------------------+
|     TRANSEC       |  Link-level: Frequency hopping,      |
|                   |  spread spectrum, traffic masking    |
+-------------------+--------------------------------------+
|     COMSEC        |  Data-level: AES encryption of       |
|                   |  payload content                     |
+-------------------+--------------------------------------+
|     SDLS Auth     |  Frame-level: MAC authentication,    |
|                   |  anti-replay protection              |
+-------------------+--------------------------------------+
```

### Key Management

Symmetric keys must be pre-shared between ground and spacecraft:

**Initial Key Load:**
- Master keys loaded during satellite integration (pre-launch)
- Keys stored in tamper-resistant hardware security module (HSM)

**Key Hierarchy:**
```
Master Key (burned in at factory)
    |
    +--> Key Encryption Keys (KEK) - Protect key updates
    |
    +--> Session Keys - Used for actual command authentication
```

**Over-the-Air Rekeying (OTAR):**
1. New session key encrypted with KEK
2. Key change command authenticated with current session key
3. Spacecraft decrypts and installs new key
4. Acknowledgment sent in telemetry

**Key Change Command:**
```
+-------------+--------------+---------------+------------+
| Key Change  | New Key ID   | Encrypted New | MAC (old   |
| Opcode      |              | Session Key   | key)       |
+-------------+--------------+---------------+------------+
```

### Authorization for Third Parties

Third parties can send tasks through several mechanisms:

**1. API Delegation (Commercial Operators)**

Satellite operators issue API credentials with scoped permissions:

```
Authorization Header: Bearer <access_token>

Token Claims:
{
  "sub": "customer-123",
  "scope": ["tasking:create", "tasking:read"],
  "satellites": ["SAT-A", "SAT-B"],
  "max_priority": "standard",
  "aoi_restrictions": { ... },
  "exp": 1704067200
}
```

The operator's ground system validates the token and translates the API request into authenticated spacecraft commands.

**2. Reseller/Partner Programs**

```
+--------------+     +--------------+     +--------------+
|  End User    |---->|   Reseller   |---->|   Operator   |
|  (Customer)  |     |   Platform   |     |   Ground Sys |
+--------------+     +--------------+     +--------------+
      |                    |                     |
   API Key            Operator API           SDLS Auth
   (Reseller)         Credentials            to Spacecraft
```

Examples:
- **Arlula**: Aggregates tasking across multiple operators
- **SkyFi**: White-label platform for ICEYE and others
- **SpyMeSat**: Multi-constellation tasking interface

**3. White-Label Solutions**

Operators provide turnkey platforms that third parties can deploy under their own brand:
- Complete command chain remains with original operator
- Third party manages customer relationships
- Technical authority never leaves the licensed operator

### What Third Parties Cannot Do

**Direct RF Access:** Third parties cannot transmit commands directly to spacecraft without:
1. Licensed ground station equipment
2. Pre-loaded cryptographic keys on the spacecraft
3. Coordination with satellite operator for frequency/timing

**Key Access:** Session keys are never exposed to third parties. Authorization flows through the operator's authenticated systems.

### Authentication Methods Taxonomy

Based on recent surveys of satellite authentication systems:

| Method | Mechanism | Real-time | Security | Quantum-Safe |
|--------|-----------|-----------|----------|--------------|
| **Cryptography (ECDSA/AES)** | Digital signatures, symmetric encryption | High | High | No |
| **Blockchain** | Distributed ledger, consensus | Low | High | Partial |
| **Orbital Parameters** | Position/velocity as auth factor | Low | Medium | Yes |
| **AKA Protocol** | Adapted from mobile networks | Medium | Medium | No |
| **Hardware (PUF/HSM)** | Physical unclonable functions | High | High | Partial |

Cryptography-based methods dominate operational systems due to real-time requirements, though blockchain approaches show promise for audit trails and cross-operator coordination.

### Gap Analysis: What Current Systems Cannot Do

| Capability | CCSDS SDLS | Commercial API | Zero-Trust ISL |
|------------|------------|----------------|----------------|
| Ground-to-satellite auth | ✓ | ✓ (indirect) | — |
| Satellite-to-satellite auth | — | — | ✓ |
| Third-party direct authorization | — | — | — |
| Delegation chains | — | — | — |
| Capability attenuation | — | — | — |
| Payment integration | — | — | — |
| Cross-operator (real-time) | — | — | — |

**Critical limitation**: All current systems use either symmetric keys (CCSDS SDLS) or operator-mediated APIs. There is no mechanism for:

1. **Delegation**: Operator A cannot authorize Satellite X to command Operator B's Satellite Y
2. **Attenuation**: Granted access is all-or-nothing within a category (no "image up to 100 km² only")
3. **Direct cross-operator**: ESA tasking a Planet satellite requires days of business process, not minutes of protocol

The fundamental issue: **symmetric keys cannot support delegation**. Only the key holder can authenticate. Asymmetric signatures allow anyone to verify without being able to forge.

---

## 8. Commercial Tasking APIs

Modern commercial satellite operators expose REST APIs for tasking. These APIs act as the authorization boundary--they validate customer credentials and translate requests into operator-authenticated spacecraft commands.

### API Authentication Methods

| Provider | Method | Token Type | Refresh |
|----------|--------|------------|---------|
| **Planet** | Basic Auth or OAuth2 | API Key or Bearer Token | Keys permanent; OAuth tokens expire |
| **Maxar** | OAuth2 | Bearer Token | Required before expiration |
| **Airbus** | API Key | Header token | Permanent |
| **ICEYE** | OAuth2 | Bearer Token | Required |

**Planet Authentication Example:**

```bash
# Basic Auth with API Key
curl -u $PL_API_KEY: https://api.planet.com/tasking/v2/orders

# OAuth2 Bearer Token
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
     https://api.planet.com/tasking/v2/orders
```

**OAuth2 Machine-to-Machine Flow:**

```
+--------------+                    +--------------+
|   Client     |                    |   Auth       |
|   App        |                    |   Server     |
+------+-------+                    +------+-------+
       |                                   |
       |  POST /oauth/token                |
       |  grant_type=client_credentials    |
       |  client_id=xxx                    |
       |  client_secret=yyy                |
       +---------------------------------->|
       |                                   |
       |  { "access_token": "...",         |
       |    "expires_in": 3600 }           |
       |<----------------------------------+
       |                                   |
```

Tokens are short-lived (typically 1 hour) and must be refreshed. This limits damage from token theft.

### Common Request Parameters

```json
{
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]
  },
  "start_time": "2024-01-15T00:00:00Z",
  "end_time": "2024-01-20T23:59:59Z",
  "priority": "standard",
  "off_nadir_angle_max": 25,
  "cloud_cover_max": 20,
  "resolution": "0.30m",
  "product_type": "visual"
}
```

### Maxar Tasking Tiers

| Tier | Lead Time | Priority |
|------|-----------|----------|
| Select | Flexible window | Standard |
| Select Plus | Higher priority | Elevated |
| Assured | 6-24 hours | High |
| Direct Access | 15 minutes | Immediate |

### Planet Tasking Parameters

- **Area of Interest (AOI)**: GeoJSON polygon (50-1000 km^2)
- **Time of Interest (TOI)**: ISO 8601 datetime range
- **sat_elevation_angle_min/max**: Restrict viewing geometry
- **imaging_mode**: mono, stereo

### Response Format (STAC)

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "id": "order-12345",
  "geometry": { ... },
  "properties": {
    "datetime": "2024-01-16T14:30:00Z",
    "platform": "WorldView-3",
    "gsd": 0.31,
    "status": "scheduled"
  },
  "assets": {
    "data": { "href": "s3://bucket/path/image.tif" }
  }
}
```

---

## 9. Ground Station Networks

### Ground Station as a Service (GSaaS)

| Provider | Locations | Orbit Support | Key Features |
|----------|-----------|---------------|--------------|
| **AWS Ground Station** | 12 worldwide | LEO, MEO | S/X-band, VITA-49, pay-per-use |
| **KSAT** | 25+ global | LEO to GEO | Legacy + NewSpace |
| **ATLAS** | Federated network | LEO | Software-defined, AWS integrated |
| **Leaf Space** | Europe, Americas | LEO | CubeSat focused |
| **RBC Signals** | 50+ locations | LEO, MEO | Multi-provider aggregation |

Note: Azure Orbital Ground Station was retired in December 2024.

### AWS Ground Station Architecture

```
+-------------+     +-----------------+     +--------------+
|  Satellite  |<--->| AWS Antenna     |---->| AWS VPC      |
|             |     | (S/X-band, 5.4m)|     | (Customer)   |
+-------------+     +-----------------+     +--------------+
                           |
                    VITA-49 Protocol
                    (RF over IP)
```

### Contact Scheduling

Typical workflow:
1. Query satellite visibility windows via API
2. Reserve antenna time for specific passes
3. Configure uplink/downlink parameters
4. Execute contact
5. Data delivered to cloud storage

---

## 10. Current State of Inter-Satellite Communication

Before proposing new mechanisms, we survey what exists today for satellite-to-satellite communication and command relay.

### 10.1 Relay Constellations (Ground -> GEO -> LEO)

These systems relay ground-originated commands through intermediary satellites:

**NASA TDRSS (1983-present):**
- GEO satellites relay commands from White Sands to LEO spacecraft
- Provides 85-100% orbital coverage vs ~10% with direct ground contact
- Commands still **originate from ground**, just relayed through space
- Supports up to 26 user spacecraft simultaneously
- Being phased out in favor of commercial alternatives (no new missions after Nov 2024)

**ESA EDRS (2016-present):**
- Laser ISL (1.8 Gbps) between GEO relay and LEO satellites
- Can relay commands to **reprogram LEO satellites in near-real-time**
- 50,000+ successful inter-satellite links as of mid-2021
- Ground stations at Weilheim, Redu, and Harwell
- Still ground-originated: operator sends command -> EDRS relays -> LEO executes

**SpaceLink (planned 2024+):**
- Commercial MEO relay constellation
- Similar architecture to TDRSS but commercially operated
- U.S. Army studying use for tactical data relay

### 10.2 Mesh Networks (Data Routing)

**Starlink (2019-present):**
```
+---------+   Laser ISL   +---------+   Laser ISL   +---------+
|Starlink |<------------>|Starlink |<------------>|Starlink |
|  Sat A  |    200 Gbps   |  Sat B  |    200 Gbps   |  Sat C  |
+---------+               +---------+               +---------+
                               |
                          RF Downlink
                               |
                               v
                        +-------------+
                        |Ground Station|
                        +-------------+
```

- 9,000+ satellites with laser crosslinks
- 42 petabytes/day traversing the mesh
- Third parties (e.g., Muon Space) can integrate Starlink mini lasers
- Enables "real-time tasking, continuous command-and-control"
- **Key limitation**: Commands still originate from SpaceX/operator ground systems
- The mesh routes data; it doesn't autonomously generate or authorize commands

### 10.3 Satellite Servicing (Physical, Not RF)

**Northrop Grumman MEV-1/2 (2020-present):**
- Physically docks with client satellite (e.g., Intelsat 901)
- Takes over attitude control using MEV's own thrusters
- Does **NOT send commands to client's flight computer**
- Client satellite becomes passive cargo
- Required FCC and NOAA licensing for approach

**NASA OSAM-1 (planned):**
- Will grapple and refuel Landsat 7
- Command-driven robotic mechanisms
- Target was not designed for servicing

### 10.4 Autonomous Constellation Operations (Single Operator)

Within a single operator's constellation, satellites can coordinate autonomously:

**Lockheed Martin HiveStar:**
- Bid-auction task allocation across constellation
- No human intervention required
- Demonstrated on Pony Express 2 mission
- All satellites share same operator's trust domain

**Academic Systems (TeamAgent, CBBA implementations):**
- Multi-agent distributed task planning
- Satellites negotiate via ISL
- Proven in simulation and limited flight experiments

### 10.5 The Gap: Cross-Operator Commanding

| Capability | Exists Today? | Notes |
|------------|---------------|-------|
| Ground -> Relay -> LEO command | (yes) | TDRSS, EDRS |
| Data mesh routing | (yes) | Starlink |
| Single-operator autonomous coordination | (yes) | HiveStar, CBBA |
| Cross-operator satellite commanding | (no) | **No mechanism exists** |
| Delegated authorization tokens | (no) | Proposed below |
| Third-party ISL command injection | (no) | Would require new protocols |

**Today's workaround for cross-operator tasking:**
```
Satellite A's Operator                    Satellite B's Operator
        |                                         |
        |  1. "Please image coordinates X"        |
        +--------> (Email/API/Phone) ------------>|
        |                                         |
        |                    2. Operator B sends  |
        |                       command via their |
        |                       ground station    |
        |                                         v
        |                                    Satellite B
```

This requires terrestrial coordination and ground station passes--no direct satellite-to-satellite authorized commanding.

---

## 11. Inter-Satellite Command Authorization (Hypothesis)

This section explores how a satellite might receive and authorize commands from another satellite during a close approach, without real-time ground station involvement.

### 11.1 The Problem Space

Current satellite C2 assumes ground-to-space communication with pre-shared symmetric keys. Inter-satellite commanding introduces new challenges:

1. **No pre-shared keys**: Commanding satellite doesn't have target's session keys
2. **No real-time ground contact**: Can't query operator during close approach
3. **Identity verification**: Target must verify commander's identity
4. **Authorization scope**: What commands is the commander permitted to execute?
5. **Freshness**: Prevent replay of old authorization tokens

### 11.2 Physical Layer: Close Approach Communication

During Rendezvous and Proximity Operations (RPO), satellites can communicate via:

**RF Inter-Satellite Link (ISL):**
```
Commanding Satellite                    Target Satellite
       |                                      |
       |  +-----------------------------+    |
       |  |   S-band/UHF Omnidirectional |    |
       |  |   TT&C Antenna (target)      |    |
       |  +-----------------------------+    |
       |              ^                       |
       |              | RF Link              |
       |              | (< 10 km range)      |
       |              |                       |
       |  +----------+----------+            |
       |  | Directional or Omni |            |
       |  | Antenna (commander) |            |
       |  +---------------------+            |
       |                                      |
```

**Characteristics:**
- Target's omnidirectional TT&C antenna (typically S-band 2.0-2.3 GHz or UHF 400-450 MHz)
- Very short range reduces power requirements (inverse square law)
- Link budget at 1 km: ~60 dB less path loss than GEO-to-ground
- Achievable data rates: 9.6 kbps to several Mbps depending on equipment

**Optical ISL (Alternative):**
- Higher bandwidth (Gbps) but requires precise pointing
- Narrow beam (~10 urad) provides inherent security
- Not suitable for omnidirectional reception

### 11.3 Proposed Authorization Model: Delegated Capability Tokens

Inspired by [UCAN (User Controlled Authorization Networks)](https://blog.web3.storage/posts/intro-to-ucan) and OAuth2 delegation, we propose a **Capability Token** model where the target satellite's operator pre-signs authorization tokens that the commanding satellite presents.

#### Key Insight

The target satellite already has its operator's **public key** (for verifying software updates, etc.). This enables asymmetric verification: the operator signs tokens offline, and the target verifies them on-orbit without needing the operator's private key or real-time communication.

### Capability Token Structure

```
+----------------------------------------------------------------+
|                    CAPABILITY TOKEN (JWT-like)                  |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- alg: "ES256" (ECDSA with P-256)                          |
|  +-- typ: "SAT-CAP"                                           |
+----------------------------------------------------------------+
|  Payload                                                       |
|  +-- iss: "OP-12345"          # Issuer (target's operator)    |
|  +-- sub: "SAT-CMD-001"       # Subject (commanding satellite)|
|  +-- aud: "SAT-TGT-042"       # Audience (target satellite)   |
|  +-- iat: 1704067200          # Issued at (Unix timestamp)    |
|  +-- nbf: 1704067200          # Not valid before              |
|  +-- exp: 1704153600          # Expiration (24-48 hr window)  |
|  +-- jti: "a1b2c3d4..."       # Unique token ID (nonce)       |
|  +-- cap: [                   # Capabilities granted          |
|  |     "cmd:imaging:start",                                   |
|  |     "cmd:imaging:stop",                                    |
|  |     "cmd:attitude:point"                                   |
|  |   ]                                                        |
|  +-- cns: {                   # Constraints                   |
|  |     "max_range_km": 10,    # Proximity requirement         |
|  |     "orbital_zone": {...}, # Allowed region (optional)     |
|  |     "max_commands": 5      # Rate limiting                 |
|  |   }                                                        |
|  +-- cmd_pub: "04a1b2..."     # Commander's public key        |
+----------------------------------------------------------------+
|  Signature                                                     |
|  +-- ECDSA signature by operator's private key                |
+----------------------------------------------------------------+
```

### Command Message Structure

The commanding satellite sends:

```
+----------------------------------------------------------------+
|                    INTER-SATELLITE COMMAND                      |
+----------------------------------------------------------------+
|  CCSDS Primary Header (6 bytes)                                |
|  +-- Version: 000                                              |
|  +-- Type: 1 (TC)                                              |
|  +-- APID: Target's ISL command APID                          |
|  +-- Sequence Count                                            |
+----------------------------------------------------------------+
|  Extended Security Header                                      |
|  +-- Security Type: 0x03 (Delegated Capability)               |
|  +-- Token Length: Variable                                    |
|  +-- Capability Token: [Base64-encoded JWT]                   |
+----------------------------------------------------------------+
|  Command Payload                                               |
|  +-- Timestamp: Current UTC (for freshness)                   |
|  +-- Command Type: e.g., "cmd:imaging:start"                  |
|  +-- Parameters: Command-specific data                        |
|  |   {                                                        |
|  |     "target_coords": [lat, lon],                           |
|  |     "duration_sec": 30,                                    |
|  |     "sensor": "IR-CAM-1"                                   |
|  |   }                                                        |
|  +-- Commander Signature: ECDSA(commander_privkey, payload)   |
+----------------------------------------------------------------+
|  Frame Check (CRC-16)                                          |
+----------------------------------------------------------------+
```

### Verification Protocol

```
Commanding Satellite (C)              Target Satellite (T)
        |                                     |
        |  1. Acquire ISL link                |
        +------------------------------------>|
        |                                     |
        |  2. Send: Token + Command + Sig     |
        +------------------------------------>|
        |                                     |
        |         +---------------------------+
        |         | 3. Verify token:          |
        |         |    a. Check operator sig  |
        |         |       (using stored pubkey)
        |         |    b. Check exp > now     |
        |         |    c. Check aud == self   |
        |         |    d. Check jti not used  |
        |         |       (replay prevention) |
        |         |                           |
        |         | 4. Verify command:        |
        |         |    a. Check cmd in cap[]  |
        |         |    b. Verify commander sig|
        |         |       (using cmd_pub)     |
        |         |    c. Check freshness     |
        |         |    d. Check constraints   |
        |         |       (range, zone, etc.) |
        |         +---------------------------+
        |                                     |
        |  5. ACK/NAK + Execution Status      |
        |<------------------------------------+
        |                                     |
```

### Security Properties

| Property | Mechanism |
|----------|-----------|
| **Authentication** | Operator signature on token; commander signature on command |
| **Authorization** | Explicit capability list in token (`cap` field) |
| **Integrity** | ECDSA signatures over all data |
| **Freshness** | Timestamp in command; expiration in token |
| **Anti-Replay** | Token ID (`jti`) stored in used-token cache |
| **Scope Limitation** | Constraints (`cns`) limit range, region, rate |
| **Revocation** | Short token lifetime (hours, not days) |

### Range Verification

The target satellite can verify proximity through:

1. **Signal Strength (RSSI)**: At S-band, free-space path loss at 10 km ~ 130 dB; at 1 km ~ 110 dB. Received signal strength indicates approximate range.

2. **Two-Way Ranging**: Challenge-response timing. Light-time at 10 km ~ 33 us round-trip.

3. **Orbital Mechanics**: If both satellites broadcast TLE-equivalent state vectors, target can compute expected range and verify consistency.

**Range Verification Methods:**

| Method | Accuracy | Spoofability |
|--------|----------|--------------|
| RSSI | $\pm 50\%$ (crude) | Moderate |
| Two-way ranging | $\pm 1$ m | Difficult |
| State vector comparison | $\pm 100$ m | Requires orbit knowledge |

### Pre-Mission Setup Flow

```
+-------------+     +-------------+     +-------------+
|  Target's   |     | Commanding  |     |  Target     |
|  Operator   |     | Satellite   |     |  Satellite  |
+------+------+     +------+------+     +------+------+
       |                   |                   |
       | 1. Operator pubkey burned in         |
       |   at manufacturing                   |
       +-------------------------------------->|
       |                                       |
       | 2. Commander requests                 |
       |    authorization                      |
       |<------------------+                   |
       |                   |                   |
       | 3. Operator issues|                   |
       |    capability token                   |
       +------------------>|                   |
       |                   |                   |
       |                   | 4. Close approach |
       |                   |    + command      |
       |                   +------------------>|
       |                   |                   |
       |                   | 5. Verification   |
       |                   |    + execution    |
       |                   |<------------------+
       |                   |                   |
```

### Challenges and Mitigations

| Challenge | Mitigation |
|-----------|------------|
| **Clock drift** | Generous validity windows; timestamp tolerance +/-60s |
| **Token storage** | Small flash storage for used `jti` values; expiry-based cleanup |
| **Computational cost** | ECDSA P-256 verification: ~10ms on modern embedded CPU |
| **Key compromise** | Short token lifetimes; operator can update satellite's trust anchor |
| **Man-in-the-middle** | Commander signs command with private key matching `cmd_pub` in token |
| **Rogue satellite** | Target verifies token was issued by *its own* operator |

### 11.4 Use Cases for Inter-Satellite Tasking

1. **Collaborative Observation**: Satellite A instructs Satellite B to image coordinates while A handles downlink
2. **Debris Inspection**: Inspector satellite commands defunct satellite to attempt safe mode or transponder activation
3. **Constellation Coordination**: Lead satellite redistributes tasks among constellation members
4. **Emergency Response**: Nearby satellite commands antenna pointing for distress signal relay
5. **Commercial Services**: Satellite operator sells excess capacity; customer's satellite carries authorization token

### 11.5 Auction-Based Distributed Task Allocation

For constellation-wide task distribution (not just point-to-point commanding), we propose integrating capability tokens with auction-based algorithms.

#### Why Auction/Market Mechanisms?

| Problem | Auction Solution |
|---------|------------------|
| **Centralized bottleneck** | Each satellite decides locally; no single coordinator |
| **Communication delays** | Decisions use only neighbor information |
| **Satellite failure** | Others re-bid for orphaned tasks automatically |
| **Heterogeneous capabilities** | Bids encode cost/capability implicitly |
| **New satellites joining** | Immediately participate in auctions |
| **Conflicting task claims** | Auction resolves conflicts deterministically |

#### The CBBA Algorithm (Consensus-Based Bundle Algorithm)

From MIT's Aerospace Controls Lab, CBBA is a proven decentralized task allocation algorithm:

**Phase 1: Bundle Building (Local)**
```
Each satellite greedily builds a task bundle:
  SAT-1: "Task A costs me 10 units, Task C costs 15"
  SAT-2: "Task A costs me 8 units, Task B costs 12"
```

**Phase 2: Consensus (Distributed)**
```
Satellites exchange bids with ISL neighbors:
  SAT-1 -> SAT-2: "I bid 10 for Task A"
  SAT-2 -> SAT-1: "I bid 8 for Task A"  <- Lower cost wins

  SAT-1: "OK, you take A. I'll rebid on B or C."
```

**Iteration:** Repeat until no conflicts remain.

**Properties:**
- Converges to conflict-free assignment
- Polynomial-time algorithm
- Tolerates partial communication graphs
- Decentralized execution with local information only

#### Cross-Operator Auction with Capability Tokens

Extending CBBA to multi-operator scenarios requires authorization:

```
+-----------------------------------------------------------------+
|                    CROSS-OPERATOR AUCTION BID                    |
+-----------------------------------------------------------------+
|  Bid Header                                                     |
|  +-- bidder_id: "SAT-ALPHA-007"                                |
|  +-- task_id: "IMG-20240115-0042"                              |
|  +-- bid_value: 8.5              # Lower is better             |
|  +-- timestamp: 1705312800                                      |
+-----------------------------------------------------------------+
|  Authorization                                                  |
|  +-- capability_token: <JWT>     # Proves right to bid         |
|  |     +-- cap: ["task:bid:imaging", "task:execute:imaging"]   |
|  +-- bidder_signature: ECDSA(...)                              |
+-----------------------------------------------------------------+
|  Bid Details                                                    |
|  +-- estimated_cost: {                                         |
|  |     "fuel_kg": 0.02,                                        |
|  |     "time_sec": 45,                                         |
|  |     "opportunity_cost": 3.2                                 |
|  |   }                                                         |
|  +-- earliest_execution: "2024-01-15T14:30:00Z"               |
|  +-- capability_match: 0.95      # Sensor suitability          |
+-----------------------------------------------------------------+
```

#### Auction Protocol with Authorization

```
Task Originator (O)          Bidder Satellites (A, B, C)
      |                              |
      |  1. Broadcast: Task + Auth   |
      |     Requirements             |
      +----------------------------->|
      |                              |
      |         +--------------------+
      |         | 2. Each satellite: |
      |         |    - Check if has  |
      |         |      valid cap token|
      |         |    - Compute bid   |
      |         |      (cost/utility)|
      |         +--------------------+
      |                              |
      |  3. Submit bids + tokens     |
      |<-----------------------------+
      |                              |
      |  4. Verify all tokens        |
      |  5. Select winner (lowest bid|
      |     among authorized bidders)|
      |                              |
      |  6. Award + Command Token    |
      +----------------------------->| Winner only
      |                              |
      |  7. Winner executes task     |
      |  8. Result + proof           |
      |<-----------------------------+
      |                              |
```

#### Bid Semantics: Why Lower is Better

The bid value encodes **cost to execute**, not willingness to pay:

```python
def compute_bid(satellite, task) -> float:
    """Lower bid = better suited to execute task"""

    # Fuel cost to slew and maneuver
    fuel_cost = estimate_fuel(satellite.position, task.target)

    # Time until satellite can begin
    time_cost = compute_access_window(satellite.orbit, task.target)

    # Opportunity cost (other tasks displaced)
    opportunity_cost = evaluate_queue_impact(satellite.task_queue, task)

    # Capability mismatch penalty
    capability_penalty = 1.0 / sensor_match(satellite.sensors, task.requirements)

    return fuel_cost + time_cost + opportunity_cost + capability_penalty
```

Satellites with better geometry, appropriate sensors, and lighter queues produce lower bids.

#### Integration with Payment

For commercial cross-operator tasking, the auction can include payment:

```
Capability Token includes:
  +-- cap: ["task:bid:*", "task:execute:*"]
  +-- payment_escrow: "0x1234..."     # Smart contract or escrow ID
  +-- max_bid_value: 100              # Budget ceiling
  +-- payment_per_unit: 0.5           # Rate for execution
```

The winning satellite presents proof-of-execution to claim payment from escrow.

#### Advantages Over Centralized Tasking APIs

| Aspect | Centralized (Today) | Distributed Auction |
|--------|---------------------|---------------------|
| Latency | Ground relay required | Direct ISL negotiation |
| Availability | Depends on ground passes | Always-on via mesh |
| Scalability | API rate limits | Parallel local decisions |
| Failure tolerance | Single point of failure | Graceful degradation |
| Cross-operator | Manual coordination | Automated with tokens |

### 11.6 Delegation Chain Protocol

The basic capability token model assumes single-hop authorization: operator issues token to commander, commander presents to target. Real-world scenarios require **multi-hop delegation** where intermediate satellites relay tasks.

#### The Delegation Problem

```
Original Customer (C)
        |
        |  Requests task via ground station
        v
+-----------------+
|  Relay Sat 1    |  Has token from C's operator
|  (Iridium)      |
+--------+--------+
         |
         |  Must delegate authority to Relay Sat 2
         v
+-----------------+
|  Relay Sat 2    |  Needs to prove chain of authority
|  (Iridium)      |
+--------+--------+
         |
         |  Must command target with valid authorization
         v
+-----------------+
|  Target Sat     |  Must verify entire delegation chain
|  (Sentinel-2C)  |
+-----------------+
```

#### Delegation Token Structure

Each hop in the chain creates a **Delegation Token** that references its parent:

```
+----------------------------------------------------------------+
|                    DELEGATION TOKEN                             |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- alg: "ES256"                                              |
|  +-- typ: "SAT-CAP-DEL"                                        |
|  +-- chn: 2                      # Chain depth (0 = root)      |
+----------------------------------------------------------------+
|  Payload                                                       |
|  +-- iss: "IRIDIUM-168"          # Delegating satellite        |
|  +-- sub: "IRIDIUM-172"          # Delegate (next hop)         |
|  +-- aud: "SENTINEL-2C"          # Final target (unchanged)    |
|  +-- root_iss: "ESA-COPERNICUS"  # Original token issuer       |
|  +-- root_jti: "abc123..."       # Original token ID           |
|  +-- parent_jti: "def456..."     # Parent delegation ID        |
|  +-- iat: 1705330805                                           |
|  +-- exp: 1705334400             # Must be <= parent exp       |
|  +-- jti: "ghi789..."            # This delegation's ID        |
|  +-- cap: [...]                  # Must be subset of parent    |
|  +-- cns: {...}                  # Must be >= restrictive      |
|  +-- del_pub: "04d5e6..."        # Delegate's public key       |
+----------------------------------------------------------------+
|  Delegation Chain (array of previous tokens)                   |
|  +-- chain: [<root_token>, <parent_delegation>, ...]          |
+----------------------------------------------------------------+
|  Signature                                                     |
|  +-- ECDSA signature by delegating satellite's private key    |
+----------------------------------------------------------------+
```

#### Delegation Rules

1. **Capability Attenuation**: Each delegation can only grant capabilities $\subseteq$ parent
   ```
   parent.cap = ["cmd:imaging:*", "cmd:attitude:point"]
   child.cap  = ["cmd:imaging:msi"]  (yes) Valid (subset)
   child.cap  = ["cmd:propulsion:*"] (no) Invalid (not in parent)
   ```

2. **Constraint Tightening**: Constraints can only become $\geq$ restrictive
   ```
   parent.cns.max_range_km = 100
   child.cns.max_range_km  = 50   (yes) Valid (tighter)
   child.cns.max_range_km  = 200  (no) Invalid (looser)
   ```

3. **Expiration Inheritance**: Delegation cannot extend validity beyond parent ($\leq$)
   ```
   parent.exp = 1705334400
   child.exp  = 1705332000  (yes) Valid (earlier)
   child.exp  = 1705340000  (no) Invalid (later)
   ```

4. **Maximum Chain Depth**: Root token specifies maximum delegation depth
   ```
   root.cns.max_delegation_depth = 3
   ```

#### Chain Verification Algorithm

```python
def verify_delegation_chain(command: InterSatelliteCommand,
                            target: Satellite) -> bool:
    """Verify complete delegation chain from root to commander"""

    chain = command.token.chain + [command.token]

    # 1. Verify root token is from target's operator
    root = chain[0]
    if not verify_signature(root, target.operator_pubkey):
        return False
    if root.aud != target.id:
        return False

    # 2. Walk the chain, verifying each delegation
    for i in range(1, len(chain)):
        parent = chain[i-1]
        child = chain[i]

        # Verify parent signed child
        parent_pubkey = parent.cmd_pub if i == 1 else parent.del_pub
        if not verify_signature(child, parent_pubkey):
            return False

        # Verify capability attenuation
        if not is_subset(child.cap, parent.cap):
            return False

        # Verify constraint tightening
        if not is_more_restrictive(child.cns, parent.cns):
            return False

        # Verify expiration inheritance
        if child.exp > parent.exp:
            return False

        # Verify chain depth limit
        if child.chn > root.cns.max_delegation_depth:
            return False

    # 3. Verify final token matches command signer
    final = chain[-1]
    if not verify_signature(command, final.del_pub or final.cmd_pub):
        return False

    return True
```

#### Compact Chain Representation

For bandwidth efficiency, chains can be compressed:

```
Full chain:     [root_token, del_1, del_2, del_3]  (~4 KB)
Compact chain:  [root_jti, del_1_jti, del_2_jti, del_3]  (~1 KB)

Target satellite caches recently-seen tokens by jti.
If cache hit, only final delegation needs full transmission.
```

### 11.7 Data Access Capabilities

Command authorization and data access authorization are distinct concerns. A satellite may be authorized to command another satellite's instrument but have no right to receive the resulting data.

#### Data Capability Types

| Capability | Description | Example |
|------------|-------------|---------|
| `data:receive:<source>` | Receive data from named source | `data:receive:SENTINEL-2C` |
| `data:relay:<destination>` | Relay data toward destination | `data:relay:AWS-GS-OREGON` |
| `data:process:<algorithm>` | Apply processing algorithm | `data:process:atmospheric_correction` |
| `data:store:<duration>` | Cache data for specified time | `data:store:24h` |
| `data:downlink:<station>` | Downlink to ground station | `data:downlink:DLR-WEILHEIM` |

#### Data Access Token

Separate from command tokens, data access tokens authorize data flows:

```
+----------------------------------------------------------------+
|                    DATA ACCESS TOKEN                            |
+----------------------------------------------------------------+
|  Payload                                                       |
|  +-- iss: "ESA-COPERNICUS"       # Data owner/operator         |
|  +-- sub: "STARLINK-FUSION-42"   # Data recipient              |
|  +-- src: "SENTINEL-2C"          # Data source satellite       |
|  +-- data_types: [               # Authorized data types       |
|  |     "OLCI_L1B",                                             |
|  |     "OLCI_L2A"                                              |
|  |   ]                                                         |
|  +-- cap: [                      # Data capabilities           |
|  |     "data:receive:SENTINEL-2C",                             |
|  |     "data:process:ocean_color",                             |
|  |     "data:relay:NOAA-CRW"                                   |
|  |   ]                                                         |
|  +-- cns: {                                                    |
|  |     "max_volume_gb_day": 500,                               |
|  |     "geographic_mask": "ocean_only",                        |
|  |     "retention_hours": 24                                   |
|  |   }                                                         |
|  +-- iat: 1705320000                                           |
|  +-- exp: 1736856000             # Can be long-lived           |
|  +-- jti: "data-access-001"                                    |
+----------------------------------------------------------------+
|  Signature (by data owner)                                     |
+----------------------------------------------------------------+
```

#### Data Flow Authorization

```
+-------------+  cmd token   +-------------+  data token  +-------------+
|   Customer  |------------->|   Target    |------------->|   Relay/    |
|             |              |  Satellite  |              |   ODC       |
+-------------+              +-------------+              +------+------+
                                                                 |
                                                           data token
                                                                 |
                                                                 v
                                                          +-------------+
                                                          |   Ground    |
                                                          |   Station   |
                                                          +-------------+

Token requirements:
1. Customer -> Target: Command capability token
2. Target -> Relay: Data receive token (Relay authorized by Target's operator)
3. Relay -> Ground: Data downlink token (Ground authorized to receive)
```

### 11.8 Extended Constraint Verification

Basic range verification (RSSI, two-way ranging) is insufficient for RPO and servicing scenarios. Extended constraints require richer verification mechanisms.

#### Constraint Types

| Constraint | Verification Method | Accuracy |
|------------|---------------------|----------|
| `max_range_km` | RSSI, two-way ranging | +/-1 m |
| `max_relative_velocity_m_s` | Doppler shift, state vectors | +/-0.01 m/s |
| `approach_corridor` | State vector + geometric check | +/-10 m |
| `keep_out_zones` | LIDAR, camera, state vectors | +/-1 m |
| `lighting_required` | Sun vector calculation | N/A |
| `attitude_tolerance_deg` | IMU comparison, visual | +/-0.1deg |
| `orbital_zone` | State vector vs. boundary | +/-100 m |

#### Constraint Schema

```json
{
  "cns": {
    "proximity": {
      "max_range_km": 10,
      "min_range_m": 30,
      "max_relative_velocity_m_s": 0.1,
      "max_relative_acceleration_m_s2": 0.01
    },
    "approach": {
      "corridor_type": "cone",
      "corridor_axis": "target_velocity_vector",
      "half_angle_deg": 15,
      "waypoints": [
        {"range_m": 1000, "hold_sec": 60, "approval": "autonomous"},
        {"range_m": 100, "hold_sec": 120, "approval": "ground"},
        {"range_m": 10, "hold_sec": 30, "approval": "ground"}
      ]
    },
    "keep_out": [
      {"type": "solar_array", "clearance_m": 5},
      {"type": "antenna", "clearance_m": 3},
      {"type": "radiator", "clearance_m": 2}
    ],
    "environmental": {
      "lighting_required": true,
      "eclipse_operations": false,
      "sun_angle_min_deg": 30
    },
    "abort": {
      "triggers": [
        "relative_velocity_exceeded",
        "attitude_anomaly",
        "ground_abort_command",
        "debris_detection"
      ],
      "action": "radial_retreat",
      "safe_distance_m": 100
    }
  }
}
```

#### Real-Time Constraint Monitoring

For RPO operations, constraints are continuously verified:

```python
class ConstraintMonitor:
    """Continuous constraint verification during proximity operations"""

    def __init__(self, token: CapabilityToken, target: Satellite):
        self.constraints = token.constraints
        self.target = target
        self.abort_triggered = False

    def check_all(self, commander_state: StateVector) -> ConstraintStatus:
        """Check all constraints, return status or trigger abort"""

        relative = compute_relative_state(commander_state, self.target.state)

        # Range check
        if relative.range_m > self.constraints.proximity.max_range_km * 1000:
            return ConstraintStatus.OUT_OF_RANGE

        if relative.range_m < self.constraints.proximity.min_range_m:
            self.trigger_abort("min_range_violated")
            return ConstraintStatus.ABORT

        # Velocity check
        if relative.velocity_m_s > self.constraints.proximity.max_relative_velocity_m_s:
            self.trigger_abort("velocity_exceeded")
            return ConstraintStatus.ABORT

        # Approach corridor check
        if not self.in_approach_corridor(relative):
            self.trigger_abort("corridor_violation")
            return ConstraintStatus.ABORT

        # Keep-out zone check
        for zone in self.constraints.keep_out:
            if self.intersects_keep_out(relative, zone):
                self.trigger_abort("keep_out_violation")
                return ConstraintStatus.ABORT

        return ConstraintStatus.OK

    def trigger_abort(self, reason: str):
        """Execute abort maneuver per token specification"""
        self.abort_triggered = True
        self.execute_abort_maneuver(self.constraints.abort.action)
```

### 11.9 Token Lifecycle Management

Tokens require lifecycle management beyond simple expiration for operational flexibility and security.

#### Token States

```
+-------------+     issue      +-------------+
|   DRAFT     |--------------->|   ACTIVE    |
+-------------+                +------+------+
                                      |
              +-----------------------+-----------------------+
              |                       |                       |
              v                       v                       v
       +-------------+         +-------------+         +-------------+
       |   EXPIRED   |         |   REVOKED   |         |   CONSUMED  |
       | (time-based)|         |  (explicit) |         | (use-based) |
       +-------------+         +-------------+         +-------------+
```

#### Long-Lived Token Patterns

For missions requiring extended authorization (servicing, constellation membership):

**Pattern 1: Renewable Session Tokens**
```
Master Token (5-year validity, stored securely)
    |
    +--> Session Token 1 (24-hour validity) --> expires
    +--> Session Token 2 (24-hour validity) --> expires
    +--> Session Token 3 (24-hour validity) --> active
    +--> ...

Renewal requires ground station pass to verify master token still valid.
```

**Pattern 2: Epoch-Based Validity**
```
Token includes:
  +-- exp: 1736856000              # Absolute expiration (far future)
  +-- epoch: 42                     # Current validity epoch
  +-- epoch_exp: 1705406400         # Epoch expiration (near future)

Target satellite maintains:
  +-- current_epoch: 42             # Updated via ground pass
  +-- min_epoch: 40                 # Reject tokens with epoch < this

Operator increments epoch to invalidate old tokens without revoking individually.
```

**Pattern 3: Heartbeat Validation**
```
Token includes:
  +-- heartbeat_interval_sec: 3600  # Require validation every hour
  +-- last_validated: 1705320000    # Timestamp of last validation

Target rejects commands if:
  now - last_validated > heartbeat_interval_sec

Commander must periodically transmit heartbeat (signed timestamp) to maintain validity.
```

#### Revocation Mechanisms

| Mechanism | Latency | Storage | Use Case |
|-----------|---------|---------|----------|
| Short expiration | Hours | None | Standard operations |
| Epoch increment | Next ground pass | Minimal | Batch revocation |
| Revocation list | Next ground pass | O(n) | Individual revocation |
| Online check | Real-time (if relay available) | None | High-security |

**Revocation List Format:**
```json
{
  "revocation_list": {
    "version": 47,
    "generated": "2025-01-15T12:00:00Z",
    "revoked_tokens": [
      {"jti": "abc123", "reason": "compromised", "revoked_at": "2025-01-15T10:00:00Z"},
      {"jti": "def456", "reason": "mission_cancelled", "revoked_at": "2025-01-15T11:00:00Z"}
    ],
    "revoked_subjects": [
      {"sub": "SAT-COMPROMISED-001", "reason": "operator_request"}
    ],
    "signature": "ECDSA_SIG_BY_OPERATOR"
  }
}
```

### 11.10 Cross-Operator Federation

Multi-operator scenarios (disaster response, shared constellations) require trust relationships between operators who don't share keys.

#### Federation Model

```
+-------------------------------------------------------------------------+
|                         Federation Root                                  |
|                    (e.g., Space Data Association)                       |
|                                                                         |
|  Root Public Key: Published, well-known                                 |
|  Role: Signs operator certificates, not individual tokens               |
+--------------------------------+----------------------------------------+
                                 |
         +-----------------------+-----------------------+
         |                       |                       |
         v                       v                       v
+-----------------+     +-----------------+     +-----------------+
|  ESA-COPERNICUS |     |     MAXAR       |     |     ICEYE       |
|                 |     |                 |     |                 |
|  Operator Cert  |     |  Operator Cert  |     |  Operator Cert  |
|  (signed by     |     |  (signed by     |     |  (signed by     |
|   federation)   |     |   federation)   |     |   federation)   |
+--------+--------+     +--------+--------+     +--------+--------+
         |                       |                       |
         v                       v                       v
   +----------+            +----------+            +----------+
   |Sentinel-1|            |WorldView |            | ICEYE-X  |
   |Sentinel-2|            |  GeoEye  |            |  Fleet   |
   +----------+            +----------+            +----------+
```

#### Operator Certificate

```
+----------------------------------------------------------------+
|                    OPERATOR CERTIFICATE                         |
+----------------------------------------------------------------+
|  +-- operator_id: "ESA-COPERNICUS"                             |
|  +-- operator_name: "European Space Agency - Copernicus"       |
|  +-- operator_pubkey: "04a1b2c3..."                            |
|  +-- satellites: ["SENTINEL-1A", "SENTINEL-1B", ...]           |
|  +-- capabilities_offered: [                                   |
|  |     "imaging:sar", "imaging:msi", "data:relay"              |
|  |   ]                                                         |
|  +-- federation_membership: "SPACE-DATA-ASSOCIATION"           |
|  +-- valid_from: "2024-01-01T00:00:00Z"                        |
|  +-- valid_until: "2029-01-01T00:00:00Z"                       |
|  +-- certificate_signature: <signed by federation root>        |
+----------------------------------------------------------------+
```

#### Cross-Operator Token Verification

```python
def verify_cross_operator_token(token: CapabilityToken,
                                 target: Satellite,
                                 federation_root_pubkey: bytes) -> bool:
    """Verify token from different operator via federation"""

    # 1. Get issuer's operator certificate
    issuer_cert = fetch_operator_certificate(token.iss)

    # 2. Verify certificate is signed by federation root
    if not verify_signature(issuer_cert, federation_root_pubkey):
        return False

    # 3. Verify certificate is still valid
    if issuer_cert.valid_until < now():
        return False

    # 4. Verify token is signed by certified operator
    if not verify_signature(token, issuer_cert.operator_pubkey):
        return False

    # 5. Verify target accepts tokens from this operator
    if token.iss not in target.accepted_issuers:
        return False

    # 6. Standard token verification
    return verify_token_claims(token, target)
```

#### Bilateral vs. Multilateral Trust

| Model | Setup | Use Case |
|-------|-------|----------|
| **Bilateral** | Each operator pair exchanges certificates | Commercial agreements |
| **Multilateral (Federation)** | Single root, all operators certified | Disaster response, shared infrastructure |
| **Hybrid** | Federation for discovery, bilateral for operations | Most practical |

### 11.11 Proof-of-Execution Standards

Payment release and audit require verifiable proof that tasks were executed as specified.

#### Proof Types by Task Category

| Task Type | Proof Contents | Verification Method |
|-----------|----------------|---------------------|
| **Imaging** | Image hash, metadata, thumbnail | Hash matches delivered product |
| **SAR** | Acquisition parameters, scene hash | Parameters match request |
| **AIS Collection** | Message count, sample messages, coverage | Statistical validation |
| **GNSS-RO** | Profile count, tangent points, quality flags | Coverage verification |
| **Relay** | Data volume, timestamps, receipts | End-to-end confirmation |
| **RPO Inspection** | Telemetry log, images, LIDAR data | Proximity verification |
| **Servicing** | Docking telemetry, combined state | Continuous monitoring |

#### Proof-of-Execution Message

```
+----------------------------------------------------------------+
|                    PROOF OF EXECUTION                           |
+----------------------------------------------------------------+
|  Header                                                        |
|  +-- task_id: "IMG-2025-01-15-0042"                           |
|  +-- executor: "SENTINEL-2C"                                   |
|  +-- execution_time: "2025-01-15T14:30:00Z"                   |
|  +-- proof_type: "imaging"                                     |
+----------------------------------------------------------------+
|  Execution Summary                                             |
|  +-- status: "completed"                                       |
|  +-- parameters_as_executed: {                                 |
|  |     "center_lat": 38.5,                                     |
|  |     "center_lon": -122.3,                                   |
|  |     "off_nadir_deg": 12.3,                                  |
|  |     "cloud_cover_pct": 8                                    |
|  |   }                                                         |
|  +-- deviations_from_request: []                               |
+----------------------------------------------------------------+
|  Cryptographic Proof                                           |
|  +-- product_hash: "sha256:a1b2c3d4..."                       |
|  +-- metadata_hash: "sha256:e5f6g7h8..."                       |
|  +-- thumbnail_hash: "sha256:i9j0k1l2..."                      |
|  +-- merkle_root: "sha256:m3n4o5p6..."                         |
+----------------------------------------------------------------+
|  Delivery Confirmation                                         |
|  +-- delivery_method: "isl_relay"                              |
|  +-- delivered_to: "STARLINK-FUSION-42"                        |
|  +-- delivery_time: "2025-01-15T14:45:00Z"                     |
|  +-- receipt_signature: <signed by recipient>                  |
+----------------------------------------------------------------+
|  Executor Signature                                            |
|  +-- ECDSA signature over all above fields                     |
+----------------------------------------------------------------+
```

#### Proof Verification for Payment Release

```python
def verify_proof_and_release_payment(proof: ProofOfExecution,
                                      original_task: SatelliteTask,
                                      escrow: PaymentEscrow) -> bool:
    """Verify execution proof and release escrowed payment"""

    # 1. Verify proof signature
    executor_pubkey = get_satellite_pubkey(proof.executor)
    if not verify_signature(proof, executor_pubkey):
        return False

    # 2. Verify task ID matches
    if proof.task_id != original_task.task_id:
        return False

    # 3. Verify execution parameters meet requirements
    if not parameters_satisfy_requirements(
        proof.parameters_as_executed,
        original_task.requirements
    ):
        return False

    # 4. Verify product hash matches delivered data (if available)
    if escrow.requires_product_verification:
        delivered_product = fetch_product(proof.delivery_destination)
        if hash(delivered_product) != proof.product_hash:
            return False

    # 5. Verify delivery receipt
    recipient_pubkey = get_satellite_pubkey(proof.delivered_to)
    if not verify_signature(proof.receipt_signature, recipient_pubkey):
        return False

    # 6. Release payment
    escrow.release_to(proof.executor)
    return True
```

### 11.12 Emergency Authorization

Time-critical scenarios (disaster response, collision avoidance, search and rescue) require expedited authorization that balances urgency with security.

#### Emergency Capability Class

```json
{
  "emergency_token": {
    "typ": "SAT-CAP-EMERG",
    "emergency_class": "CHARTER_ACTIVATION",
    "priority": "IMMEDIATE",
    "cap": [
      "cmd:imaging:*",
      "cmd:attitude:point",
      "cmd:downlink:any"
    ],
    "cns": {
      "emergency_types": ["earthquake", "tsunami", "volcanic", "flood"],
      "geographic_bounds": "CHARTER_AOI",
      "max_tasks_per_activation": 10,
      "audit_required": true
    },
    "activation": {
      "activation_id": "CHARTER-2025-JAP-001",
      "activated_by": "UN-SPIDER",
      "activation_time": "2025-01-15T06:15:00Z"
    }
  }
}
```

#### Emergency Authorization Levels

| Level | Authorization | Use Case | Post-Hoc Audit |
|-------|---------------|----------|----------------|
| **Level 1: Pre-Authorized** | Standing emergency tokens issued to authorized responders | International Charter, SAR agencies | Optional |
| **Level 2: Rapid Approval** | Expedited token issuance (minutes, not hours) | Government agencies, VAAC | Required |
| **Level 3: Act-First** | Execute with post-hoc authorization | Imminent collision, life safety | Mandatory |

#### Pre-Authorized Emergency Tokens

Operators pre-issue emergency tokens to authorized agencies:

```
+-------------------------------------------------------------------------+
|                    PRE-AUTHORIZED EMERGENCY FRAMEWORK                    |
+-------------------------------------------------------------------------+
|                                                                         |
|  Standing Agreements:                                                   |
|  +-- International Charter: 17 space agencies, 60+ satellites          |
|  +-- COSPAS-SARSAT: Search and rescue                                  |
|  +-- VAAC: Volcanic ash advisories                                     |
|  +-- National agencies: FEMA, EMSA, etc.                               |
|                                                                         |
|  Pre-Issued Tokens:                                                     |
|  +-- Scope: Emergency imaging, data relay                              |
|  +-- Validity: 1 year, renewable                                       |
|  +-- Activation: Requires activation code + emergency declaration      |
|  +-- Audit: All uses logged, reviewed quarterly                        |
|                                                                         |
+-------------------------------------------------------------------------+
```

#### Act-First Protocol (Level 3)

For imminent threats where authorization delay could cause catastrophic harm:

```python
class ActFirstProtocol:
    """Execute critical commands with post-hoc authorization"""

    ALLOWED_ACT_FIRST = [
        "collision_avoidance_maneuver",
        "distress_signal_relay",
        "safe_mode_activation"
    ]

    def execute_act_first(self, command: Command, justification: str) -> bool:
        """Execute immediately, authorize later"""

        # 1. Verify command type is allowed for act-first
        if command.type not in self.ALLOWED_ACT_FIRST:
            raise NotActFirstEligible(command.type)

        # 2. Log intent with cryptographic commitment
        commitment = self.create_audit_commitment(command, justification)
        self.broadcast_commitment(commitment)  # To all nearby satellites

        # 3. Execute command
        result = self.execute(command)

        # 4. Create detailed audit record
        audit = AuditRecord(
            command=command,
            justification=justification,
            commitment=commitment,
            result=result,
            timestamp=now(),
            executor_signature=self.sign(...)
        )

        # 5. Queue for ground review at next pass
        self.queue_audit_review(audit)

        return result
```

#### Emergency Audit Requirements

All emergency authorizations require post-hoc audit:

```json
{
  "emergency_audit_record": {
    "activation_id": "CHARTER-2025-JAP-001",
    "activation_authority": "UN-SPIDER",
    "activation_justification": "M8.9 earthquake, tsunami warning",
    "satellites_tasked": [
      {"satellite": "SENTINEL-1C", "tasks": 3, "data_volume_gb": 45},
      {"satellite": "ICEYE-X14", "tasks": 2, "data_volume_gb": 12}
    ],
    "total_tasks": 5,
    "total_data_gb": 57,
    "products_delivered": ["flood_map", "damage_assessment"],
    "audit_status": "approved",
    "reviewed_by": "ESA-OPS",
    "review_date": "2025-01-20"
  }
}
```

### 11.13 Compact Token Encoding

Full JWT tokens can exceed 1 KB, problematic for bandwidth-constrained links. Compact encoding reduces overhead.

#### Size Analysis

| Component | JSON Size | CBOR Size | Notes |
|-----------|-----------|-----------|-------|
| Header | 50 bytes | 25 bytes | Fixed structure |
| Payload (minimal) | 400 bytes | 200 bytes | Core claims only |
| Payload (full) | 1200 bytes | 600 bytes | With constraints |
| Signature | 88 bytes | 64 bytes | Raw ECDSA |
| **Total (minimal)** | **538 bytes** | **289 bytes** | 46% reduction |
| **Total (full)** | **1338 bytes** | **689 bytes** | 49% reduction |

#### CBOR Encoding

Replace JSON with CBOR (Concise Binary Object Representation, RFC 8949):

```
JSON Token:
{
  "iss": "ESA-COPERNICUS",
  "sub": "STARLINK-8192",
  "aud": "SENTINEL-2C",
  "exp": 1705406400,
  "cap": ["cmd:imaging:msi"],
  ...
}

CBOR Token (hex):
a6                           # map(6)
   01                        # iss (key 1)
   6e 45 53 41 2d ...        # "ESA-COPERNICUS"
   02                        # sub (key 2)
   6c 53 54 41 52 ...        # "STARLINK-8192"
   ...
```

#### Predefined Capability Bundles

Replace verbose capability lists with bundle IDs:

```python
CAPABILITY_BUNDLES = {
    0x01: ["cmd:imaging:*"],
    0x02: ["cmd:imaging:optical", "cmd:attitude:point"],
    0x03: ["cmd:imaging:sar:*", "cmd:attitude:point", "cmd:downlink:edrs"],
    0x04: ["cmd:ais:collection", "data:relay:*"],
    0x05: ["cmd:rpo:approach", "cmd:rpo:inspect", "cmd:rpo:dock"],
    # ... predefined bundles for common use cases
}

# Token payload
{
  "cap_bundle": 0x03,  # Instead of listing all capabilities
  "cap_extra": ["cmd:custom:xyz"]  # Any additions
}
```

#### Token Caching and References

For repeated interactions, use token references:

```
First command:
+---------------------------------------------+
|  Full token (689 bytes)                     |
|  Command payload                            |
|  Signature                                  |
+---------------------------------------------+

Subsequent commands (within session):
+---------------------------------------------+
|  Token reference: jti hash (32 bytes)       |
|  Command payload                            |
|  Signature                                  |
+---------------------------------------------+

Target caches token by jti, validates reference against cache.
Saves ~650 bytes per subsequent command.
```

#### Bandwidth Impact

At 9.6 kbps (typical S-band TT&C):

| Encoding | Token Size | Tx Time | With Caching |
|----------|------------|---------|--------------|
| JSON | 1338 bytes | 1.1 sec | 0.3 sec |
| CBOR | 689 bytes | 0.6 sec | 0.3 sec |
| CBOR + Bundles | 450 bytes | 0.4 sec | 0.3 sec |

For time-critical operations, 0.7 second savings per command is significant.

### 11.14 Implications for SCRAP

The capability token and auction models suggest SCRAP should support:

```python
# === Authorization Layer ===

@dataclass
class CapabilityToken:
    issuer: str                    # Target's operator ID
    subject: str                   # Commanding satellite ID
    audience: str                  # Target satellite ID
    issued_at: datetime
    expires_at: datetime
    token_id: str                  # Unique nonce
    capabilities: list[str]        # Permitted command/bid types
    constraints: TokenConstraints  # Range, region, rate limits
    commander_pubkey: bytes        # For verifying signatures
    payment_terms: PaymentTerms | None  # Optional escrow info
    signature: bytes               # Operator's signature

@dataclass
class InterSatelliteCommand:
    token: CapabilityToken
    timestamp: datetime
    command_type: str
    parameters: dict
    commander_signature: bytes     # Signs (timestamp + type + params)

# === Auction Layer ===

@dataclass
class TaskBid:
    task_id: str
    bidder_id: str
    bid_value: float               # Lower is better (cost-based)
    timestamp: datetime
    capability_token: CapabilityToken  # Proves authorization to bid
    cost_breakdown: CostEstimate
    earliest_execution: datetime
    bidder_signature: bytes

@dataclass
class CostEstimate:
    fuel_kg: float
    time_sec: float
    opportunity_cost: float
    capability_match: float        # 0-1 suitability score

@dataclass
class AuctionRound:
    task: SatelliteTask
    bids: list[TaskBid]
    round_number: int
    consensus_state: dict[str, str]  # task_id -> winning_bidder_id

# === Auction Protocol ===

class CBBAAuction:
    """Consensus-Based Bundle Algorithm for distributed task allocation"""

    def bundle_build(self, satellite: Satellite, tasks: list[Task]) -> list[TaskBid]:
        """Phase 1: Greedily build bundle of tasks this satellite can handle"""
        ...

    def consensus_update(self, local_bids: list[TaskBid],
                         neighbor_bids: list[TaskBid]) -> list[TaskBid]:
        """Phase 2: Resolve conflicts with neighbors, keep winning bids"""
        ...

    def is_converged(self) -> bool:
        """Check if all conflicts resolved"""
        ...
```

---

## 12. Summary: SCRAP Design Considerations

### Key Design Requirements

1. **Protocol Abstraction**
   - Support CCSDS packet construction
   - Abstract over transport mechanisms (SLE, direct RF, GSaaS APIs)
   - Support inter-satellite link command encapsulation

2. **Task Representation**
   - GeoJSON for spatial targets
   - ISO 8601 for temporal constraints
   - Support time-tagged and position-tagged execution

3. **Authorization**
   - Capability token generation and verification
   - Support for encrypted/authenticated commands (SDLS)
   - Cross-operator delegation via signed tokens

4. **Distributed Task Allocation**
   - Auction-based algorithms (CBBA) for constellation coordination
   - Bid structures encoding cost/capability
   - Consensus protocols for conflict resolution

5. **Multi-Path Delivery**
   - Ground-to-satellite (traditional)
   - Ground-to-satellite-to-satellite (relay via TDRSS/EDRS/Starlink)
   - Satellite-to-satellite (direct ISL with capability tokens)

6. **Payment Integration**
   - Escrow references in capability tokens
   - Proof-of-execution for payment release

### Complete Task Structure

```python
@dataclass
class SatelliteTask:
    task_id: str
    target: GeoJSON                 # Area or point
    time_window: TimeRange          # Earliest/latest execution
    execution_mode: Literal["immediate", "time_tagged", "position_tagged"]
    payload: PayloadCommand         # Instrument-specific
    priority: int
    constraints: TaskConstraints    # Sun angle, cloud cover, etc.
    delivery_path: DeliveryPath     # Ground, relay, or ISL
    auction_params: AuctionParams | None  # For distributed allocation

@dataclass
class DeliveryPath:
    method: Literal["ground", "relay", "isl", "auction"]
    ground_station: str | None      # For ground/relay methods
    relay_satellite: str | None     # For relay method
    capability_token: CapabilityToken | None  # For ISL/auction methods

@dataclass
class AuctionParams:
    bidding_window_sec: int         # How long to collect bids
    min_capability_match: float     # Reject bids below this threshold
    max_bid_value: float | None     # Budget ceiling
    require_proof_of_execution: bool
```

---

## References

### Standards Documents
- [CCSDS 133.0-B-2 Space Packet Protocol](https://ccsds.org/Pubs/133x0b2e2.pdf)
- [CCSDS 355.0-B-2 Space Data Link Security](https://ccsds.org/Pubs/355x0b2.pdf)
- [CCSDS 350.0-G-3 Application of Security to CCSDS Protocols](https://ccsds.org/Pubs/350x0g3.pdf)
- [CCSDS 352.0-B-2 Cryptographic Algorithms](https://ccsds.org/Pubs/352x0b2.pdf)
- [ECSS-E-ST-70-41C Packet Utilization Standard](https://ecss.nl/standard/ecss-e-st-70-41c-space-engineering-telemetry-and-telecommand-packet-utilization-15-april-2016/)
- [OMG C2MS Specification](https://www.omg.org/spec/C2MS/)

### Technical Resources
- [Quindar: What is Satellite Command and Control?](https://www.quindar.space/blog-article/what-is-satellite-command-and-control)
- [ESA Satellite Frequency Bands](https://www.esa.int/Applications/Connectivity_and_Secure_Communications/Satellite_frequency_bands)
- [CCSDS Space Link Extension Overview](https://ccsds.org/Pubs/910x3g3.pdf)
- [CCSDSPy Documentation](https://docs.ccsdspy.org/en/latest/user-guide/ccsds.html)
- [Finalizing CCSDS Space-Data Link Layer Security (NASA)](https://ntrs.nasa.gov/api/citations/20150018141/downloads/20150018141.pdf)
- [Protecting Space Systems from Cyber Attack (Aerospace Corp)](https://medium.com/the-aerospace-corporation/protecting-space-systems-from-cyber-attack-3db773aff368)

### Security and TRANSEC
- [TRANSEC Technical Brief (iDirect)](https://www.idirect.net/wp-content/uploads/2020/03/WhitePaper-GovDef-TRANSEC.pdf)
- [Security in IP Satellite Networks: COMSEC and TRANSEC](https://ieeexplore.ieee.org/document/6333089)
- [Zero Trust Authentication for Inter-Satellite Links](https://www.sciencedirect.com/science/article/pii/S1570870525000654)
- [Lightweight Location Key-Based Authentication for S2S Communication](https://www.sciencedirect.com/science/article/abs/pii/S0140366422004169)
- [Comprehensive Survey: Security Authentication Methods for Satellite Systems](https://arxiv.org/html/2503.23277v1)

### Inter-Satellite Links and RPO
- [Inter-Satellite Links Overview (TelecomWorld101)](https://telecomworld101.com/inter-satellite-links/)
- [Hybrid RF and Optical ISL Study (UPC)](https://upcommons.upc.edu/server/api/core/bitstreams/0606cb96-8054-47ce-b56b-d1a9191247df/content)
- [GomSpace ISL Technology](https://gomspace.com/inter-satellite-link-(isl).aspx)
- [OISL vs RF Links for Satcom Constellations](https://www.iridian.ca/learning_center/light-notes/oisl-vs-rf-links-exploring-technologies-for-satcom-constellations/)
- [Rendezvous and Proximity Operations (ISI SERC)](https://www.isi.edu/centers-serc/research/rendezvous-and-proximity-operations-rpo/)
- [U.S. Military RPO Fact Sheet (Secure World Foundation)](https://www.swfound.org/publications-and-reports/u-s-military-and-intelligence-rendezvous-and-proximity-operations-fact-sheet)
- [Learning from Past RPO (Aerospace Corp)](https://aerospace.org/sites/default/files/2018-05/GettingInYourSpace.pdf)

### Relay Systems and Mesh Networks
- [NASA TDRSS Overview](https://www.nasa.gov/mission/tracking-and-data-relay-satellites/)
- [ESA EDRS Overview](https://connectivity.esa.int/european-data-relay-satellite-system-edrs-overview)
- [EDRS eoPortal](https://www.eoportal.org/satellite-missions/edrs)
- [Starlink Technology](https://starlink.com/technology)
- [Starlink Laser ISL Statistics (LightNow)](https://www.lightnowblog.com/2024/02/ir-lasers-link-9000-starlink-satellites-and-move-42-million-gb-per-day/)
- [Lasercom State of Play (Aerospace Corp)](https://aerospace.org/sites/default/files/2023-05/FY23_12205_SOP_Lasercom%20Ppr_r10.pdf)
- [SpaceLink eoPortal](https://www.eoportal.org/satellite-missions/spacelink)

### Satellite Servicing
- [Northrop MEV Wikipedia](https://en.wikipedia.org/wiki/Mission_Extension_Vehicle)
- [NASA OSAM-1 Overview](https://www.nasa.gov/centers-and-facilities/goddard/nasa-satellite-servicing-technologies-licensed-by-northrop-grumman/)
- [OSAM State of Play (Aerospace Corp)](https://aerospace.org/sites/default/files/2021-08/FY21_10570_CTO_State%20of%20Play_Emerging%20in%20Space_r7.pdf)

### Auction-Based Task Allocation
- [CBBA - MIT Aerospace Controls Lab](https://acl.mit.edu/projects/consensus-based-bundle-algorithm)
- [Consensus-Based Decentralized Auctions (IEEE)](https://ieeexplore.ieee.org/document/5072249/)
- [Auction-Based Task Allocation in Multi-Satellite Systems (AIAA)](https://arc.aiaa.org/doi/10.2514/6.2021-0185)
- [Lockheed HiveStar Whitepaper](https://www.lockheedmartin.com/content/dam/lockheed-martin/space/documents/space/hivestar-spacecloud.pdf)
- [Pony Express 2 Mission (SatNews)](https://news.satnews.com/2024/02/15/lockheed-martins-pony-express-2-tech-demo-satellites-are-ready-for-launch/)
- [Market-Based Multirobot Coordination Survey (ResearchGate)](https://www.researchgate.net/publication/2998069_Market-Based_Multirobot_Coordination_A_Survey_and_Analysis)
- [Optimal Satellite Constellation Reconfiguration with Auction Algorithm](https://www.sciencedirect.com/science/article/abs/pii/S0094576507001920)

### Capability-Based Authorization
- [Intro to UCAN (User Controlled Authorization Networks)](https://blog.web3.storage/posts/intro-to-ucan)
- [OAuth 2.0 Token Exchange Delegation Patterns](https://www.scottbrady.io/oauth/delegation-patterns-for-oauth-20)
- [RFC 6750: OAuth 2.0 Bearer Token Usage](https://datatracker.ietf.org/doc/html/rfc6750)

### Commercial Tasking APIs
- [Planet Authentication Documentation](https://docs.planet.com/develop/authentication/)
- [Planet Tasking API](https://docs.planet.com/develop/apis/tasking/)
- [Maxar Tasking Guide](https://developers.maxar.com/docs/tasking/guides/tasking-guide)
- [Arlula API Documentation](https://www.arlula.com/documentation/)
- [Airbus One Tasking](https://space-solutions.airbus.com/imagery/how-to-order-imagery-and-data/one-tasking/)

### Ground Station Services
- [AWS Ground Station](https://aws.amazon.com/ground-station/)
- [AWS Ground Station Scheduling with Python SDK](https://aws.amazon.com/blogs/publicsector/scheduling-satellite-contact-using-aws-ground-station-python-sdk/)
- [Azure Orbital](https://azure.microsoft.com/en-us/products/orbital/)
- [Leaf Space Scheduler](https://leaf.space/inside-the-scheduler/)
- [VisionSpace SLE Provider](https://github.com/visionspacetec/sle-provider)

### Reseller and Aggregation Platforms
- [Arlula - Satellite Data Distribution](https://www.arlula.com/)
- [SkyFi - Consumer Satellite Access](https://www.spymesat.com/)
- [Cognitive Space - Multi-Provider Tasking](https://www.cognitivespace.com/blog/challenges-of-tasking/)

### Open Source Implementations
- [spacepackets (Python)](https://spacepackets.readthedocs.io/)
- [puslib (Python PUS)](https://github.com/pxntus/puslib)
- [gr-satellites (GNU Radio)](https://github.com/daniestevez/gr-satellites)
- [ccsds-spacepacket (Rust)](https://github.com/KubOS-Preservation-Group/ccsds-spacepacket)
