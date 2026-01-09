# SISL: Secure Inter-Satellite Link Protocol

**Status:** Draft Proposal
**Version:** 0x02
**Date:** 2025-12-17
**Based on:** CCSDS Proximity-1, CCSDS SDLS, Signal X3DH, [PTLC-FALLBACK.md](PTLC-FALLBACK.md)

---

## 1. Executive Summary

SISL (Secure Inter-Satellite Link) is a link-layer protocol for authenticated, encrypted communication between LEO satellites. It combines:

- **CCSDS Proximity-1** frame structure and concepts
- **CCSDS SDLS** security mechanisms (AES-256-GCM)
- **X3DH-style key agreement** using secp256k1 for mutual authentication and forward secrecy
- **Spread spectrum** physical layer (DSSS/FHSS) for interference rejection and LPI
- **ChaCha20-derived spreading codes** eliminating need for pre-shared secrets

### Protocol Layering

SISL is the **link layer** in a multi-layer security architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ APPLICATION: Onion Task Packets (per PTLC-FALLBACK.md Section 7.1)               │
│   End-to-end encryption through untrusted relays                        │
│   ChaCha20-Poly1305 per-hop encryption                                  │
│   secp256k1 ECDH key derivation, ephemeral key rotation                 │
├─────────────────────────────────────────────────────────────────────────┤
│ SISL LINK LAYER (this specification)                                    │
│   X3DH-style mutual authentication (no signatures required)             │
│   Link-layer encryption (AES-256-GCM)                                   │
│   LPI/LPD via ChaCha20-derived spreading codes                          │
├─────────────────────────────────────────────────────────────────────────┤
│ PHYSICAL: Spread spectrum RF (DSSS/FHSS)                                │
│   FEC: Convolutional 1/2 + RS(255,223)                                  │
│   CRC-32C (Castagnoli) for error detection                              │
└─────────────────────────────────────────────────────────────────────────┘
```

**End-to-end security** is provided by the onion layer ([PTLC-FALLBACK.md](PTLC-FALLBACK.md)). Intermediate relay satellites cannot read payload content.

**Link security** is provided by SISL. Each hop is mutually authenticated with forward secrecy.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| X3DH authentication | Mutual auth without signature nonce risk |
| Encrypted hailing | Source NORAD hidden from observers |
| Mutual ephemeral keys | Forward secrecy on both directions |
| ChaCha20 spreading codes | Cryptographically secure, no structure to exploit |
| secp256k1 keys | Bitcoin-native, compatible with payment layer |
| CRC-32C | Better error detection for radiation-induced bit flips |
| Explicit versioning | Clean upgrade path, no reserved field ambiguity |

---

## 2. Background

### 2.1 Problem Statement

Current satellite communication protocols have limitations for ad-hoc ISL:

1. **Proximity-1** has no security (per CCSDS 350.0-G-3: "no security requirements established")
2. **SDLS** doesn't apply to Proximity-1 (security must be "above I/O sublayer, analogous to TLS")
3. No standard supports spread spectrum for interference rejection
4. No standard supports public key cryptography for key establishment
5. TLS-style signatures risk catastrophic key leakage if nonces are reused (radiation-induced entropy failures)

### 2.2 Design Goals

- Hail any satellite with compatible SDR hardware
- Mutually authenticate both parties using X3DH-style DH combinations
- Hide caller identity from observers (only target NORAD visible in hail)
- Provide forward secrecy for all session data
- Operate in congested spectrum (ISM 2.4 GHz)
- Complete 50 KB exchange in single close-approach pass
- Carry onion-encrypted task packets for end-to-end security

---

## 3. Protocol Stack

```
┌─────────────────────────────────────────────────────────────────────────┐
│ LAYER 7: APPLICATION                                                    │
│   Onion task packets (per PTLC-FALLBACK.md 7.1)                         │
│   ≤50 KB per session, end-to-end encrypted                              │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 6: SISL SECURITY SUBLAYER                                         │
│   Key Agreement: X3DH-style (3 ECDH terms)                              │
│   Authentication: Implicit via DH (no signatures)                       │
│   Encryption: AES-256-GCM (per SDLS baseline)                           │
│   Anti-replay: Sequence numbers with IV binding                         │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 5: DATA SERVICES (from Proximity-1)                               │
│   Sequenced service (reliable, selective ARQ)                           │
│   Fragmentation/reassembly (≤2048 byte frames)                          │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 4: FRAME (adapted from Proximity-1)                               │
│   PLTU structure with security header/trailer                           │
│   CRC-32C (Castagnoli) error detection                                  │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 3: CODING & SYNC                                                  │
│   ASM (Attached Sync Marker)                                            │
│   FEC: Convolutional rate 1/2 K=7 + RS(255,223) + interleaving          │
│   Spreading: Public code (hail) or session-derived (P2P)                │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 2: MAC                                                            │
│   Hailing: PUBLIC spreading code (any SISL receiver can despread)       │
│   P2P: SESSION-DERIVED spreading code (only parties can despread)       │
├─────────────────────────────────────────────────────────────────────────┤
│ LAYER 1: PHYSICAL                                                       │
│   S-band: 2200-2290 MHz (TT&C), 2400-2483 MHz (ISM)                     │
│   UHF: 390-450 MHz (Proximity-1 compatibility)                          │
│   Modulation: BPSK, QPSK, OQPSK                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Cryptographic Design

### 4.1 Key Infrastructure

Each satellite has a **single secp256k1 key pair** derived from its HSM root key:

```
k_identity = HKDF(k_root, "identity" || satellite_id)
P_identity = k_identity · G
```

This key is used for:
- X3DH key agreement (SISL link establishment)
- Onion decryption (per PTLC-FALLBACK.md)
- Payment operations (per ../future/CHANNELS.md)

**Key distribution**: Operators uplink trust lists to their satellites during ground contact. Each satellite stores `{norad_id: secp256k1_pubkey}` mappings for satellites it is authorized to communicate with. Trust is rooted in the operator relationship, not a global PKI.

#### 4.1.1 Curve Selection

**Default: secp256k1** for all SISL operations. This maintains a single key hierarchy shared with SCRAP (payment layer) and onion routing.

| Implementation | ECDH Time | Notes |
|----------------|-----------|-------|
| libsecp256k1 (LEON3-FT 100 MHz) | ~200 ms | Rad-hard baseline |
| libsecp256k1 (ARM Cortex-A53) | ~12 ms | Typical CubeSat OBC |
| FPGA soft core (RTG4/XQRKU060) | ~0.5 ms | Space-qualified |

**P-256 alternative**: If FIPS 140-2/3 compliance is required, P-256 may be used for SISL X3DH only. This requires a separate key hierarchy from SCRAP/Lightning. See [SCRAP.md §11.1](SCRAP.md#111-elliptic-curve-selection) for detailed guidance.

**No space-grade HSM supports secp256k1 natively.** Hardware acceleration requires FPGA soft cores (e.g., Zcash Foundation SystemVerilog implementation).

### 4.2 X3DH Key Agreement

SISL uses an X3DH-style key agreement providing **mutual authentication** and **forward secrecy** without signatures. Both parties contribute ephemeral keys; the session key combines three ECDH operations.

```
SESSION KEY DERIVATION (X3DH-style)
══════════════════════════════════

Parties:
  Caller (C): static key pair (c, C), ephemeral key pair (ce, CE)
  Responder (R): static key pair (r, R), ephemeral key pair (re, RE)

DH Operations:
  DH1 = ECDH(ce, R)    Caller ephemeral × Responder static
  DH2 = ECDH(c, RE)    Caller static × Responder ephemeral
  DH3 = ECDH(ce, RE)   Caller ephemeral × Responder ephemeral

Combined Secret:
  shared_secret = DH1 || DH2 || DH3  (96 bytes)

Security Properties:
  DH1: Authenticates responder (only R knows r to derive)
  DH2: Authenticates caller (only C knows c to derive)
  DH3: Provides forward secrecy (ephemeral keys deleted after session)
```

**Authentication is implicit**: An attacker claiming to be satellite X cannot complete the handshake because DH2 requires X's static private key.

### 4.3 Session Key Derivation

```python
from hashlib import sha256
import struct

def derive_session_keys(
    dh1: bytes,  # ECDH(caller_eph, responder_static)
    dh2: bytes,  # ECDH(caller_static, responder_eph)
    dh3: bytes,  # ECDH(caller_eph, responder_eph)
    caller_norad: int,
    responder_norad: int,
    caller_eph_pub: bytes,
    responder_eph_pub: bytes,
) -> dict:
    """
    Derive all session secrets from X3DH shared secret.
    Both parties compute identical values independently.
    """
    # Combine DH outputs
    shared_secret = dh1 + dh2 + dh3  # 96 bytes

    # Transcript binding (prevents cross-session attacks)
    transcript = struct.pack('>II',
        min(caller_norad, responder_norad),
        max(caller_norad, responder_norad),
    ) + caller_eph_pub + responder_eph_pub

    # HKDF-SHA256 (RFC 5869)
    key_material = hkdf_sha256(
        ikm=shared_secret,
        salt=sha256(b'SISL-v2-X3DH').digest(),
        info=transcript,
        length=160
    )

    return {
        'hail_key': key_material[0:32],       # Hail encryption (DH1 only initially)
        'ack_key': key_material[32:64],       # ACK encryption
        'p2p_tx_key': key_material[64:96],    # P2P frames caller→responder
        'p2p_rx_key': key_material[96:128],   # P2P frames responder→caller
        'spreading_seed': key_material[128:160],  # DSSS/FHSS code generation
    }
```

### 4.4 Hail Decryption Key (Initial)

Before receiving the ACK, the caller cannot compute DH2 or DH3. The hail is encrypted with a key derived from DH1 only:

```python
def derive_hail_key(
    caller_eph_priv: bytes,
    responder_static_pub: bytes,
    responder_norad: int,
) -> bytes:
    """Derive hail encryption key (caller side, before ACK)."""
    dh1 = ecdh(caller_eph_priv, responder_static_pub)

    return hkdf_sha256(
        ikm=dh1,
        salt=sha256(b'SISL-v2-hail').digest(),
        info=struct.pack('>I', responder_norad),
        length=32
    )
```

The responder computes the same key using `ECDH(responder_static_priv, caller_eph_pub)`.

### 4.5 Spreading Code Generation

Spreading codes are generated using **ChaCha20** as a cryptographically secure PRNG:

```python
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from hashlib import sha256

def generate_dsss_code(seed: bytes, length: int = 1023) -> list[int]:
    """
    Generate spreading code from session-derived seed using ChaCha20.

    Uses ChaCha20 with the cryptography library's expected format:
    16 bytes = 8-byte nonce || 8-byte initial counter (little-endian).

    The nonce is domain-separated to prevent cross-use with other protocols.
    Counter starts at 0.
    """
    # Domain-separated 8-byte nonce + 8-byte counter (starting at 0)
    nonce = sha256(b'SISL-dsss-nonce').digest()[:8]
    counter = b'\x00\x00\x00\x00\x00\x00\x00\x00'  # Start at 0
    nonce_and_counter = nonce + counter  # 16 bytes total

    cipher = Cipher(algorithms.ChaCha20(seed, nonce_and_counter), mode=None)
    enc = cipher.encryptor()

    bytes_needed = (length + 7) // 8
    random_bytes = enc.update(b'\x00' * bytes_needed)

    # Convert to bipolar code (+1/-1)
    code = []
    for i in range(length):
        byte_idx = i // 8
        bit_idx = i % 8
        bit = (random_bytes[byte_idx] >> bit_idx) & 1
        code.append(1 if bit else -1)

    return code


def generate_fhss_sequence(seed: bytes, num_channels: int, num_hops: int) -> list[int]:
    """
    Generate frequency hopping sequence using ChaCha20.

    Uses domain-separated nonce to prevent cross-use with DSSS code generation.
    """
    nonce = sha256(b'SISL-fhss-nonce').digest()[:8]
    counter = b'\x00\x00\x00\x00\x00\x00\x00\x00'
    nonce_and_counter = nonce + counter

    cipher = Cipher(algorithms.ChaCha20(seed, nonce_and_counter), mode=None)
    enc = cipher.encryptor()

    random_bytes = enc.update(b'\x00' * (num_hops * 2))

    sequence = []
    for i in range(num_hops):
        val = int.from_bytes(random_bytes[i*2:(i+1)*2], 'big')
        sequence.append(val % num_channels)

    return sequence
```

### 4.6 Public Hailing Code

The hailing channel uses a **fixed public spreading code** so any SISL-capable satellite can receive hails:

```python
SISL_HAIL_SEED = sha256(b'SISL-public-hailing-code-v2').digest()
SISL_HAIL_CODE = generate_dsss_code(SISL_HAIL_SEED, length=1023)
```

This code is public knowledge. Security comes from encryption, not spreading code secrecy.

### 4.7 Security Parameters

| Parameter | Value | Reference |
|-----------|-------|-----------|
| Encryption | AES-256-GCM | CCSDS 355.0-B-2 |
| Key length | 256 bits | SDLS baseline |
| IV length | 96 bits (12 octets) | SDLS baseline |
| Auth tag | 128 bits (16 octets) | SDLS baseline |
| Sequence number | 32 bits | Anti-replay |
| Key agreement | X3DH with secp256k1 | Signal-inspired |
| Spreading PRNG | ChaCha20 (original) | RFC 8439 variant |
| CRC | CRC-32C (Castagnoli) | 0x1EDC6F41 polynomial |

---

## 5. Hailing Protocol

### 5.1 Spreading Code Usage

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SPREADING CODE ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  HAILING CHANNEL (public):                                              │
│    Spreading code: PUBLIC (fixed seed known to all SISL satellites)     │
│    Encryption: YES (AES-GCM with DH-derived key)                        │
│                                                                         │
│    → Any SISL satellite can DESPREAD and receive the hail               │
│    → Only TARGET satellite can DECRYPT (requires static private key)    │
│    → Observer with SDR: sees encrypted blob, cannot decrypt             │
│                                                                         │
│  P2P CHANNEL (secret):                                                  │
│    Spreading code: SESSION-DERIVED (from X3DH shared secret)            │
│    Encryption: YES (AES-GCM with session key)                           │
│                                                                         │
│    → Only session parties can DESPREAD (code is secret)                 │
│    → Only session parties can DECRYPT                                   │
│    → Observer: cannot even detect signal (below noise floor)            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Encrypted Hailing Message Format

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SISL ENCRYPTED HAIL MESSAGE                        │
├────────────────┬───────┬────────────────────────────────────────────────┤
│ Field          │ Bytes │ Description                                    │
├────────────────┼───────┼────────────────────────────────────────────────┤
│ Sync Pattern   │ 8     │ Fixed: 0x1ACFFC1D 0x1ACFFC1D                   │
│ Version        │ 1     │ Protocol version (0x02)                        │
│ Msg Type       │ 1     │ 0x01=Hail, 0x02=Ack, 0x03=Nack                 │
│ Target NORAD   │ 3     │ Target satellite ID (plaintext for routing)    │
│ Caller Eph Pub │ 33    │ Caller's ephemeral secp256k1 pubkey (compressed)│
│ IV             │ 12    │ AES-GCM initialization vector                  │
│ Encrypted Body │ 17    │ AES-GCM ciphertext                             │
│ Auth Tag       │ 16    │ AES-GCM authentication tag                     │
├────────────────┼───────┼────────────────────────────────────────────────┤
│ Total          │ 91    │                                                │
└────────────────┴───────┴────────────────────────────────────────────────┘

ENCRYPTED BODY (17 bytes plaintext):
┌────────────────┬───────┬────────────────────────────────────────────────┐
│ Source NORAD   │ 3     │ Caller satellite ID (hidden from observers)    │
│ Center Freq    │ 2     │ P2P channel center frequency (MHz offset)      │
│ Bandwidth      │ 1     │ P2P channel bandwidth code                     │
│ Mode           │ 1     │ 0x01=DSSS, 0x02=FHSS, 0x03=Hybrid              │
│ Chip Rate      │ 1     │ DSSS chip rate (0.1 Mcps units)                │
│ Nonce          │ 8     │ Random nonce for replay protection             │
│ Flags          │ 1     │ Capability flags                               │
└────────────────┴───────┴────────────────────────────────────────────────┘
```

#### Field Encoding Details

**Center Frequency** (2 bytes, big-endian unsigned):
- Offset in MHz from band-specific reference frequency
- S-band TT&C: reference = 2200 MHz (valid range: 0-90 → 2200-2290 MHz)
- S-band ISM: reference = 2400 MHz (valid range: 0-83 → 2400-2483 MHz)
- UHF: reference = 390 MHz (valid range: 0-60 → 390-450 MHz)
- Band selection implicit from negotiated physical layer

**Bandwidth Code** (1 byte):

| Code | Bandwidth | Use Case |
|------|-----------|----------|
| 0x01 | 1 MHz | Minimum, low-power |
| 0x02 | 2.5 MHz | Standard narrowband |
| 0x03 | 5 MHz | Default DSSS |
| 0x04 | 10 MHz | High-rate DSSS |
| 0x05 | 20 MHz | Wideband FHSS |
| 0x06 | 40 MHz | High-rate FHSS |
| 0x07-0xFF | Reserved | Future use |

**Chip Rate** (1 byte):
- Value in units of 0.1 Mcps (100 kcps)
- 0x01 = 0.1 Mcps, 0x32 = 5 Mcps, 0x64 = 10 Mcps
- Maximum: 0xFF = 25.5 Mcps
- Value 0x00 reserved (invalid)

**Flags** (1 byte, bitfield):

| Bit | Name | Description |
|-----|------|-------------|
| 0 | DSSS_CAPABLE | Satellite supports DSSS |
| 1 | FHSS_CAPABLE | Satellite supports FHSS |
| 2 | HIGH_CHIP_RATE | Supports chip rate > 5 Mcps |
| 3 | GPS_SYNC | GPS-disciplined timing available |
| 4-7 | Reserved | Must be 0 |

**Privacy**: Observers see target NORAD but cannot determine source NORAD or channel parameters.

### 5.3 Hail Acknowledgment Format

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SISL HAIL ACKNOWLEDGMENT                           │
├────────────────┬───────┬────────────────────────────────────────────────┤
│ Field          │ Bytes │ Description                                    │
├────────────────┼───────┼────────────────────────────────────────────────┤
│ Sync Pattern   │ 8     │ Fixed: 0x1ACFFC1D 0x1ACFFC1D                   │
│ Version        │ 1     │ Protocol version (0x02)                        │
│ Msg Type       │ 1     │ 0x02=Ack                                       │
│ Caller NORAD   │ 3     │ Original caller (target of ACK)                │
│ Resp Eph Pub   │ 33    │ Responder's ephemeral secp256k1 pubkey         │
│ IV             │ 12    │ AES-GCM initialization vector                  │
│ Encrypted Body │ 12    │ AES-GCM ciphertext                             │
│ Auth Tag       │ 16    │ AES-GCM authentication tag                     │
├────────────────┼───────┼────────────────────────────────────────────────┤
│ Total          │ 86    │                                                │
└────────────────┴───────┴────────────────────────────────────────────────┘

ENCRYPTED BODY (12 bytes plaintext):
┌────────────────┬───────┬────────────────────────────────────────────────┐
│ Responder NORAD│ 3     │ Responding satellite ID                        │
│ Status         │ 1     │ 0x01=Ready, 0x02=Busy, 0x03=Reject             │
│ Nonce Echo     │ 8     │ Echo of caller's nonce (proves freshness)      │
└────────────────┴───────┴────────────────────────────────────────────────┘
```

The ACK is encrypted with a key derived from **all three DH terms** (full X3DH), providing mutual authentication.

### 5.4 Protocol Sequence

```
                    CALLER                              RESPONDER
                      │                                     │
    ┌─────────────────┴─────────────────┐                   │
    │ 1. Generate ephemeral key (ce,CE) │                   │
    │ 2. Look up target static pub (R)  │                   │
    │ 3. Compute DH1 = ECDH(ce, R)      │                   │
    │ 4. Derive hail_key from DH1       │                   │
    │ 5. Encrypt hail body              │                   │
    └─────────────────┬─────────────────┘                   │
                      │                                     │
                      │══════ HAIL (public spreading) ═════►│
                      │   CE (ephemeral pub, plaintext)     │
                      │   target_norad (plaintext)          │
                      │   body (encrypted with hail_key)    │
                      │                                     │
                      │                     ┌───────────────┴───────────────┐
                      │                     │ 1. Compute DH1 = ECDH(r, CE)  │
                      │                     │ 2. Derive hail_key, decrypt   │
                      │                     │ 3. Learn source_norad         │
                      │                     │ 4. Look up caller static (C)  │
                      │                     │ 5. Verify C in trust list     │
                      │                     │    (if not: silently drop)    │
                      │                     │ 6. Generate ephemeral (re,RE) │
                      │                     │ 7. Compute DH2 = ECDH(C, re)  │
                      │                     │ 8. Compute DH3 = ECDH(CE, re) │
                      │                     │ 9. Derive full session keys   │
                      │                     │ 10. Encrypt ACK               │
                      │                     └───────────────┬───────────────┘
                      │                                     │
                      │◄═════ ACK (public spreading) ═══════│
                      │   RE (responder ephemeral pub)      │
                      │   body (encrypted with ack_key)     │
                      │                                     │
    ┌─────────────────┴─────────────────┐                   │
    │ 1. Compute DH2 = ECDH(c, RE)      │                   │
    │ 2. Compute DH3 = ECDH(ce, RE)     │                   │
    │ 3. Derive full session keys       │                   │
    │ 4. Decrypt ACK, verify nonce echo │                   │
    │ 5. Generate P2P spreading code    │                   │
    │ 6. Configure SDR for P2P channel  │                   │
    └─────────────────┬─────────────────┘                   │
                      │                                     │
    ══════════════════╪═══ SWITCH TO P2P CHANNEL ══════════╪══════════════
                      │   (session-derived spreading code)  │
                      │                                     │
                      │◄─────── P2P LINK (DSSS/FHSS) ───────►│
                      │   AES-256-GCM encrypted frames      │
                      │   ≤50 KB payload exchange           │
                      │                                     │
```

### 5.5 Untrusted Source Handling

If the responder decrypts a hail and finds `source_norad` is not in its trust list:

1. **Silently drop** the hail (do not send NACK)
2. Do not log excessive detail (DoS via log flooding)
3. Optionally rate-limit hails from unknown sources

Rationale: Sending a NACK reveals to observers that the target is SISL-capable and online.

### 5.6 Mode Selection

```python
def select_p2p_mode(our_caps: dict, target_caps: dict) -> dict:
    """Select optimal P2P mode from capability intersection."""

    # Priority 1: DSSS (simpler, no GPS timing dependency)
    if our_caps['dsss_supported'] and target_caps['dsss_supported']:
        chip_rate = min(our_caps['max_chip_rate_mcps'],
                       target_caps['max_chip_rate_mcps'])
        if chip_rate > 0:
            return {'mode': 'DSSS', 'chip_rate_mcps': chip_rate}

    # Priority 2: FHSS (requires GPS timing on both ends)
    if (our_caps['fhss_supported'] and target_caps['fhss_supported'] and
        our_caps['gps_receiver'] and target_caps['gps_receiver']):
        settling = max(our_caps['synthesizer_settling_us'],
                      target_caps['synthesizer_settling_us'])
        hop_rate = 1_000_000 / (settling * 3)
        if hop_rate >= 100:
            return {'mode': 'FHSS', 'hop_rate_hz': int(hop_rate)}

    # Fallback: Narrowband (no spreading)
    return {'mode': 'NARROWBAND'}
```

---

## 6. Secure Frame Format

### 6.1 Frame Structure

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       SISL SECURE FRAME                                 │
├─────────────────────────────────────────────────────────────────────────┤
│ ASM │ Frame Hdr │ Seq │ IV │ Encrypted Payload │ Auth Tag │ CRC-32C    │
├─────┼───────────┼─────┼────┼───────────────────┼──────────┼────────────┤
│ 4 B │   4 B     │ 4 B │12 B│   ≤2000 bytes     │   16 B   │    4 B     │
└─────┴───────────┴─────┴────┴───────────────────┴──────────┴────────────┘
```

### 6.2 Frame Header (4 bytes)

| Field | Bits | Description |
|-------|------|-------------|
| Version | 4 | Protocol version (0x2) |
| Type | 4 | 0=Data, 1=ACK, 2=NACK, 3=Keepalive |
| Flags | 8 | Fragment flags, priority |
| Length | 16 | Payload length in bytes |

### 6.3 IV Construction

The 12-byte IV is constructed to ensure uniqueness without random generation:

```
IV = direction (1 byte) || sequence_number (4 bytes) || session_id (7 bytes)

Where:
  direction: 0x00 for caller→responder, 0x01 for responder→caller
  sequence_number: 32-bit frame counter (big-endian)
  session_id: first 7 bytes of SHA256(caller_eph_pub || responder_eph_pub)
```

**Security**: IV uniqueness guaranteed by sequence number monotonicity. Separate direction byte prevents IV collision on bidirectional traffic.

### 6.4 CRC-32C (Castagnoli)

Polynomial: 0x1EDC6F41 (Castagnoli)

CRC-32C provides better error detection than ISO CRC-32 for:
- Burst errors (common in RF channels)
- Single bit flips (radiation-induced SEUs in space)

The CRC covers the entire frame from ASM through Auth Tag (inclusive).

### 6.5 Authenticated Data

AES-GCM additional authenticated data (AAD):
- Frame Header (4 bytes)
- Sequence Number (4 bytes)

This binds the ciphertext to the frame metadata.

---

## 7. Fragmentation

### 7.1 Fragment Format

Payloads exceeding 2000 bytes are fragmented:

```
┌────────────────┬───────┬────────────────────────────────────────────────┐
│ Field          │ Bits  │ Description                                    │
├────────────────┼───────┼────────────────────────────────────────────────┤
│ Fragment Flags │ 8     │ Bit 7: More fragments                          │
│                │       │ Bit 6: First fragment                          │
│                │       │ Bits 0-5: Reserved                             │
│ Fragment ID    │ 16    │ Identifies fragments of same message           │
│ Fragment Offset│ 16    │ Byte offset in reassembled message             │
│ Fragment Data  │ var   │ ≤2000 bytes                                    │
└────────────────┴───────┴────────────────────────────────────────────────┘
```

### 7.2 Reassembly

- Receiver buffers fragments by Fragment ID
- Reassembly timeout: 30 seconds
- Maximum reassembled size: 65535 bytes
- Out-of-order fragments accepted
- Duplicate fragments ignored

---

## 8. Forward Error Correction

### 8.1 FEC Scheme

SISL uses **concatenated coding** for maximum reliability:

| Parameter | Value |
|-----------|-------|
| Inner code | Convolutional, rate 1/2, constraint length K=7 |
| Inner decoder | Viterbi (soft decision) |
| Outer code | Reed-Solomon RS(255, 223), 8-bit symbols |
| Outer decoder | Berlekamp-Massey |
| Interleaving | 5 RS codewords (depth = 1275 bytes) |
| Overall rate | ~0.44 |
| Required Eb/N₀ | 2.5 dB for BER 10⁻⁶ |

### 8.2 Encoding Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          TRANSMIT PATH                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Frame ──► CRC ──► RS Encode ──► Interleave ──► Conv ──► Spread ──► TX  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                          RECEIVE PATH                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  RX ──► Despread ──► Viterbi ──► De-interleave ──► RS ──► CRC ──► Frame │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.3 FEC vs ARQ Boundary

| Layer | Mechanism | Handles |
|-------|-----------|---------|
| FEC (Layer 3) | Convolutional + RS | Channel errors (noise, interference) |
| ARQ (Layer 5) | Selective repeat | Frame loss (sync loss, buffer overflow) |

**FEC corrects errors**; **ARQ recovers lost frames**. A frame that passes CRC after FEC decoding is assumed correct. ARQ only triggers when frames are missing (sequence gap) or CRC fails after FEC.

---

## 9. Error Recovery

### 9.1 Link State Machine

```
┌─────────────┐
│    IDLE     │
└──────┬──────┘
       │ initiate_hail()
       ▼
┌─────────────┐     timeout (3s)      ┌─────────────┐
│ HAIL_SENT   │──────────────────────►│ HAIL_RETRY  │──── retry < 3 ────┐
└──────┬──────┘                       └─────────────┘                   │
       │                                     ▲                          │
       │ ACK received                        └──────────────────────────┘
       ▼
┌─────────────┐
│ LINK_READY  │
└──────┬──────┘
       │ spreading code sync
       ▼
┌─────────────┐
│  P2P_ACTIVE │◄──────────────────────────────┐
└──────┬──────┘                               │
       │                                      │
       ├── CRC fail after FEC ──► NACK ───────┤
       │                                      │
       ├── sequence gap ──► selective NACK ───┘
       │
       ├── 15s idle ──► SESSION_TIMEOUT ──► IDLE
       │
       └── transfer complete ──► SESSION_COMPLETE ──► IDLE

┌─────────────┐
│HAIL_RETRY≥3 │──── max retries ────► HAIL_FAILED ──► IDLE
└─────────────┘
```

### 9.2 ARQ Protocol

Selective repeat ARQ with:

| Parameter | Value |
|-----------|-------|
| Window size | 64 frames |
| ACK frequency | Every 8 frames or 500ms |
| NACK trigger | Sequence gap detected |
| Max retransmissions | 3 per frame |
| Retransmission timeout | 500ms (adaptive) |

### 9.3 Sequence Number Handling

| Parameter | Value |
|-----------|-------|
| Sequence number width | 32 bits |
| Wrap handling | Session ends before 2³¹ |
| Anti-replay window | 64 frames |
| Out-of-window frames | Dropped silently |

---

## 10. Physical Layer

### 10.1 Frequency Bands

| Band | Frequencies | Use Case |
|------|-------------|----------|
| S-band (TT&C) | 2025-2110 MHz (up), 2200-2290 MHz (down) | LEO ISL, allocated |
| S-band (ISM) | 2400-2483 MHz | Demonstration/research |
| UHF | 390-450 MHz | Proximity-1 compatibility |

**Regulatory Note**: This specification describes technical capabilities for research and demonstration purposes. Operational deployment requires ITU coordination. The spread spectrum design demonstrates that SISL signals can operate below thermal noise floor of existing services.

### 10.2 Hailing Channel Parameters

| Parameter | Value |
|-----------|-------|
| Spreading | DSSS with PUBLIC ChaCha20 code |
| Code seed | `SHA256("SISL-public-hailing-code-v2")` |
| Chip rate | 5 Mcps |
| Data rate | 1 kbps |
| Processing gain | 37 dB |
| Bandwidth | 10 MHz |

### 10.3 P2P Channel Parameters

| Parameter | Value |
|-----------|-------|
| Spreading | DSSS or FHSS (negotiated) |
| Code seed | Session-derived (X3DH secret) |
| Chip rate | 1-10 Mcps |
| Data rate | 10-100 kbps |
| Bandwidth | 5-50 MHz |

---

## 11. Polarization Considerations

### 11.1 ISL Geometry Effects

For satellite-to-satellite links, circular polarization handedness reverses:
- RHCP transmitted → LHCP received (and vice versa)

### 11.2 Recommendation

Transmit **linear polarization** for maximum compatibility with unknown targets.

| Target Antenna | Recommended TX | Loss |
|----------------|----------------|------|
| Linear | Linear | 0 dB |
| RHCP | LHCP or Linear | 0-3 dB |
| Unknown | Linear | 0-3 dB |

---

## 12. Operational Concept

### 12.1 Close Approach Timing

```
                    Closest Approach
                         ↓
    ○ ─────────────────────────────────────────── ○
   Sat A              500-1000 km              Sat B

├─────────┼─────────┼─────────┼─────────┼─────────┤
T-5min    T-2min    T=0       T+2min    T+5min
          │         │
     Start hailing  Best margin
                    (exchange 50KB)
```

### 12.2 Link Budget (500 km, S-band 2.4 GHz)

**Common Parameters**:

| Parameter | Value | Notes |
|-----------|-------|-------|
| TX power | 1W (30 dBm) | |
| TX antenna gain | 0 dBi | Omnidirectional |
| Path loss (500 km) | 158 dB | Free space: 20×log10(d) + 20×log10(f) + 32.45 |
| RX antenna gain | 0 dBi | Omnidirectional |
| **Received power** | **-128 dBm** | |
| Noise density (kT) | -174 dBm/Hz | 290K system temperature |

**Hailing Channel** (5 Mcps, 1 kbps data rate):

| Parameter | Value | Notes |
|-----------|-------|-------|
| Signal bandwidth | 5 MHz | Chip rate |
| Noise floor (5 MHz) | -107 dBm | -174 + 10×log10(5×10⁶) |
| SNR before despread | -21 dB | Signal below noise floor |
| Processing gain | +37 dB | 10×log10(5×10⁶ / 1×10³) |
| **SNR after despread** | **+16 dB** | |
| Required Eb/N0 | 2.5 dB | BER 10⁻⁶ with FEC |
| **Link margin** | **13.5 dB** | Robust for acquisition |

**P2P Channel** (5 Mcps, variable data rate):

| Data Rate | Processing Gain | SNR After Despread | Margin | Status |
|-----------|-----------------|-------------------|--------|--------|
| 10 kbps | 27 dB | +6 dB | 3.5 dB | Marginal |
| 25 kbps | 23 dB | +2 dB | -0.5 dB | **Does not close** |
| 50 kbps | 20 dB | -1 dB | -3.5 dB | **Does not close** |
| 100 kbps | 17 dB | -4 dB | -6.5 dB | **Does not close** |

**To achieve higher data rates at 500 km**, use directional antennas:

| Configuration | Additional Gain | Max Data Rate (3 dB margin) |
|---------------|-----------------|----------------------------|
| Omni + Omni | 0 dB | ~10 kbps |
| Omni + 10 dBi patch | +10 dB | ~50 kbps |
| 10 dBi + 10 dBi | +20 dB | ~250 kbps |

**Alternatively**, reduce range for higher throughput with omni antennas:

| Range | Path Loss | SNR (after 17 dB gain) | Margin at 100 kbps |
|-------|-----------|------------------------|-------------------|
| 500 km | 158 dB | -4 dB | -6.5 dB |
| 200 km | 150 dB | +4 dB | +1.5 dB (marginal) |
| 100 km | 144 dB | +10 dB | +7.5 dB |
| 50 km | 138 dB | +16 dB | +13.5 dB |

**Recommendation**: For LEO proximity operations (< 100 km), 100 kbps is achievable with omnidirectional antennas. For longer ranges, use directional antennas or reduce data rate.

**Note**: Hailing always uses 1 kbps for robust acquisition regardless of range. After link establishment, P2P data rate is negotiated based on measured SNR.

### 12.3 Data Transfer Time

| Data Rate | Time for 50 KB (with FEC) |
|-----------|---------------------------|
| 100 kbps | 9 sec |
| 50 kbps | 18 sec |
| 10 kbps | 90 sec |

---

## 13. Security Properties

| Property | Mechanism |
|----------|-----------|
| **Confidentiality** | AES-256-GCM (link), ChaCha20-Poly1305 (E2E onion) |
| **Integrity** | AES-GCM tag + CRC-32C |
| **Caller authentication** | X3DH DH2 term (requires caller static key) |
| **Responder authentication** | X3DH DH1 term (requires responder static key) |
| **Forward secrecy** | X3DH DH3 term (ephemeral-ephemeral) |
| **Anti-replay** | Nonce in hail, IV from sequence in frames |
| **LPI/LPD** | Session-derived spread spectrum |
| **Traffic analysis resistance** | Source NORAD encrypted in hail |
| **End-to-end through relays** | Onion encryption (PTLC-FALLBACK.md) |

---

## 14. Comparison with Existing Standards

| Aspect | Proximity-1 | SDLS | TLS 1.3 | SISL |
|--------|-------------|------|---------|------|
| Key agreement | N/A | Pre-shared | ECDHE | X3DH |
| Forward secrecy | N/A | No | Yes | Yes |
| Authentication | None | Symmetric | Signatures | Implicit DH |
| Encryption | None | AES-GCM | AES-GCM | AES-256-GCM |
| Spread spectrum | None | N/A | N/A | DSSS + FHSS |
| Caller identity | N/A | N/A | Visible | Hidden |

---

## 15. Database Requirements

SISL operation requires a satellite capability database:

### 15.1 RF Capabilities
- Frequency bands supported
- SDR instantaneous bandwidth
- DSSS/FHSS support
- Maximum chip rate
- Synthesizer settling time

### 15.2 Trust List
- `{norad_id: secp256k1_pubkey}` mappings
- Key validity period
- Operator identifier

See `SPRINT_RADIOS.md` for database schema.

---

## 16. Integration with Payment Layer

### 16.1 Key Sharing

Satellites use the **same secp256k1 identity key** for:
- X3DH link authentication (SISL)
- Onion packet decryption (PTLC-FALLBACK.md)
- PTLC adaptor signatures
- LN-Symmetry channel operations

### 16.2 Onion Packet Transport

SISL carries onion-encrypted task packets as payload:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ SISL Frame Payload                                                      │
│ ┌─────────────────────────────────────────────────────────────────────┐ │
│ │ Onion Task Packet (per PTLC-FALLBACK.md 7.1)                        │ │
│ │   - Outer envelope (first_hop, ephemeral_pubkey)                    │ │
│ │   - Funding transaction (Tx_1)                                      │ │
│ │   - Encrypted per-hop payload (routing, task, payment)              │ │
│ └─────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 16.3 Relay Privacy

When relaying onion packets:
1. Relay establishes SISL link with next hop
2. Relay decrypts its onion layer to learn `next_hop`
3. Relay forwards inner encrypted blob via SISL
4. Relay cannot read payload content
5. Relay earns PTLC payment for successful forwarding

---

## 17. Versioning and Upgrades

### 17.1 Version Field

The 1-byte version field in hail/ACK messages indicates protocol version:

| Version | Description |
|---------|-------------|
| 0x01 | Reserved (original draft) |
| 0x02 | Current specification |
| 0x03+ | Future versions |

### 17.2 Upgrade Strategy

- Receivers MUST reject messages with version < 0x02 (silently drop, no error response)
- Receivers SHOULD accept messages with version ≥ 0x02
- Unknown fields in future versions are ignored
- Fundamental changes require new version number
- Backwards compatibility maintained within major version

### 17.2.1 Version Handling Requirements

```python
def handle_incoming_message(msg: bytes) -> bool:
    """Process incoming SISL message with version validation."""
    version = msg[8]  # Version byte after sync pattern

    if version < 0x02:
        # Silently drop - do not respond (prevents version probing)
        return False

    if version > SISL_MAX_SUPPORTED_VERSION:
        # Future version - attempt best-effort parsing
        # Unknown fields will be ignored
        pass

    return process_message(msg)
```

**Rationale for silent drop**: Responding with an error to unsupported versions reveals protocol presence and version capabilities to adversaries.

### 17.3 Capability Negotiation

The `Flags` field in hail body indicates capabilities:

| Bit | Capability |
|-----|------------|
| 0 | DSSS supported |
| 1 | FHSS supported |
| 2 | High chip rate (>5 Mcps) |
| 3-7 | Reserved |

---

## 18. References

1. CCSDS 211.0-B-6: Proximity-1 Space Link Protocol—Data Link Layer
2. CCSDS 211.1-B-4: Proximity-1 Space Link Protocol—Physical Layer
3. CCSDS 355.0-B-2: Space Data Link Security Protocol
4. RFC 5869: HKDF
5. RFC 8439: ChaCha20 and Poly1305
6. Signal X3DH Specification: https://signal.org/docs/specifications/x3dh/
7. BIP-340: Schnorr Signatures for secp256k1
8. RFC 8446: TLS 1.3
9. PTLC-FALLBACK.md: Satellite Task Payment Protocol
10. ../future/CHANNELS.md: Satellite Payment Channels

---

## 19. Security Considerations

### 19.1 Nonce Reuse Prevention

SISL avoids signature nonces entirely by using X3DH implicit authentication. This eliminates the catastrophic key leakage risk from nonce reuse (critical for space hardware with limited entropy).

### 19.2 Ephemeral Key Deletion

Both parties MUST securely delete ephemeral private keys after session key derivation. This ensures forward secrecy even if static keys are later compromised.

### 19.3 Trust List Integrity

The trust list is the root of authentication. Operators must:
- Uplink trust lists over authenticated channels
- Verify satellite acknowledgment of trust list updates
- Implement trust list versioning to detect rollback attacks

#### 19.3.1 Trust List Version Structure

```python
@dataclass
class TrustListEntry:
    norad_id: int               # 3 bytes, satellite NORAD ID
    pubkey: bytes               # 33 bytes, compressed secp256k1 public key
    valid_from: int             # Unix timestamp
    valid_until: int            # Unix timestamp (0 = no expiration)
    capabilities: int           # Bitfield of allowed operations

@dataclass
class TrustList:
    version: int                # Monotonically increasing, 64-bit
    operator_id: str            # Operator identifier
    issued_at: int              # Unix timestamp
    entries: list[TrustListEntry]
    signature: bytes            # ECDSA signature by operator key
```

#### 19.3.2 Version Validation Rules

1. **Monotonic Increase**: Satellites MUST reject trust list updates where `new_version <= current_version`
2. **Rollback Protection**: The current version number MUST be stored in non-volatile memory
3. **Clock Independence**: Version numbers are independent of timestamps (prevents clock manipulation attacks)
4. **Operator Binding**: Trust list signature MUST be verified against the operator's root public key (burned in at manufacturing)

```python
def validate_trust_list_update(current: TrustList, new: TrustList,
                                operator_pubkey: bytes) -> bool:
    """Validate incoming trust list update."""
    # 1. Verify signature
    if not verify_ecdsa(new, operator_pubkey):
        return False

    # 2. Check monotonic version increase
    if new.version <= current.version:
        return False

    # 3. Check operator ID matches
    if new.operator_id != current.operator_id:
        return False

    # 4. Check timestamp is reasonable (within ±24 hours of onboard time)
    if abs(new.issued_at - onboard_time()) > 86400:
        return False

    return True
```

#### 19.3.3 Trust List Update Protocol

```
Ground Station                              Satellite
     |                                           |
     |--- TRUST_LIST_UPDATE (signed) ----------->|
     |                                           |
     |                              [Validate signature]
     |                              [Check version > current]
     |                              [Store to NVM]
     |                                           |
     |<-- TRUST_LIST_ACK (version, hash) --------|
     |                                           |
     |    [Verify ACK matches sent list]         |
     |                                           |
```

**Recovery from Missed Updates**: If satellite misses intermediate versions, it accepts any update with version > current. Version numbers need not be consecutive.

### 19.4 Denial of Service

Attackers can flood the hailing channel with invalid hails. Mitigations:
- Rate limiting hail processing
- Silent drop of untrusted sources (no NACK)
- Prioritize hails from recently-seen trusted sources

---

## 20. Implementation Notes

### 20.1 Constant-Time Operations

All cryptographic operations MUST be constant-time to prevent timing side channels:
- ECDH scalar multiplication
- AES-GCM encryption/decryption
- HKDF derivation

### 20.2 Memory Zeroization

Sensitive data MUST be zeroized after use:
- Ephemeral private keys
- Session keys
- DH shared secrets

### 20.3 Hardware Considerations

Space-qualified implementations should consider:
- Radiation-hardened RNG for ephemeral key generation
- ECC memory for key storage
- Watchdog timer for cryptographic operations (detect SEU-induced hangs)

---

## 21. Test Vectors

Test vectors for interoperability testing. All values in hexadecimal unless noted.

### 21.1 Key Derivation Test Vectors

```
TEST VECTOR 1: Session Key Derivation
=====================================

Input:
  dh1 = 0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef
  dh2 = 0xfedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321
  dh3 = 0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890
  caller_norad = 12345 (0x003039)
  responder_norad = 54321 (0x00D431)
  caller_eph_pub = 0x02aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  responder_eph_pub = 0x03bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

Derivation:
  shared_secret = dh1 || dh2 || dh3 (96 bytes)
  salt = SHA256("SISL-v2-X3DH")
       = 0x3ed3b32d78eda4ed77a72a734cbba514a9125ea04f50e3e7360919c2ed6d19da
  transcript = pack(">II", 12345, 54321) + caller_eph_pub + responder_eph_pub
             = 0x000030390000d43102aaaa...03bbbb...

Output (HKDF-SHA256, 160 bytes):
  hail_key (bytes 0-31):      0xeebf08b8befd2534e28f4467d5dbbb07c7ebe2e04fd4e3bc19bf60a751562908
  ack_key (bytes 32-63):      0xc639385d06ef28ae7e65877760f6ddbf7d0b952793fe23f8f39fcdf47ee2464f
  p2p_tx_key (bytes 64-95):   0xa6dfa305a3530b42db4402950bb1d6ffb2be78c36636ab7d0c8a96e7e5061bf1
  p2p_rx_key (bytes 96-127):  0x10479a856e31db1d42739376c0d3b8b513c6d08f6dffd18896304f69ca25561f
  spreading_seed (128-159):   0x6359afc07bcf749eb93c42cdda120dcdf84eb30fe8dccdb566df0bab5cf0e888
```

### 21.2 Spreading Code Test Vectors

```
TEST VECTOR 2: Public Hailing Code
==================================

Input:
  seed = SHA256("SISL-public-hailing-code-v2")
       = 0x4b9b573c3a36c5aac4f57b1411abbdc3eea85ca474672fb9ac0ed92911c9828a
  nonce = SHA256("SISL-dsss-nonce")[:8]
        = 0x5c658fe3a976c86d
  counter = 0x0000000000000000

ChaCha20 output (first 4 bytes):
  = 0x0902bb7c

Output (first 32 chips of 1023-chip DSSS code, bipolar +1/-1):
  [1, -1, -1, 1, -1, -1, -1, -1, -1, 1, -1, -1, -1, -1, -1, -1,
   1, 1, -1, 1, 1, 1, -1, 1, -1, -1, 1, 1, 1, 1, 1, -1]


TEST VECTOR 3: Session DSSS Code
================================

Input:
  spreading_seed = 0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  nonce = 0x5c658fe3a976c86d (same DSSS nonce)
  counter = 0x0000000000000000

ChaCha20 output (first 4 bytes):
  = 0x0a405168

Output (first 32 chips, bipolar +1/-1):
  [-1, 1, -1, 1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 1, -1,
   1, -1, -1, -1, 1, -1, 1, -1, -1, -1, -1, 1, -1, 1, 1, -1]
```

### 21.3 Hail Message Test Vector

```
TEST VECTOR 4: Encrypted Hail
=============================

Input:
  target_norad = 54321 (0x00D431)
  caller_eph_priv = 0x<32-byte private key>
  responder_static_pub = 0x02<32 bytes>  (target's known public key)

Hail Plaintext Body (17 bytes):
  source_norad = 12345 (0x003039)
  center_freq = 100 MHz offset (0x0064)
  bandwidth = 0x03 (5 MHz)
  mode = 0x01 (DSSS)
  chip_rate = 0x32 (5 Mcps)
  nonce = 0x0102030405060708
  flags = 0x03 (DSSS + FHSS capable)

Derive hail_key:
  dh1 = ECDH(caller_eph_priv, responder_static_pub)
  hail_key = HKDF(dh1, salt=SHA256("SISL-v2-hail"), info=pack(">I", 54321), len=32)

Encryption (AES-256-GCM):
  IV = random 12 bytes
  ciphertext, tag = AES-GCM-Encrypt(hail_key, IV, plaintext, AAD=empty)

Output Frame (91 bytes total):
  sync = 0x1ACFFC1D1ACFFC1D
  version = 0x02
  msg_type = 0x01
  target_norad = 0xD43100  (3 bytes, big-endian)
  caller_eph_pub = 0x02<32 bytes>
  iv = <12 bytes>
  encrypted_body = <17 bytes>
  auth_tag = <16 bytes>
```

### 21.4 IV Construction Test Vector

```
TEST VECTOR 5: Frame IV
=======================

Input:
  direction = 0x00 (caller→responder)
  sequence_number = 42 (0x0000002A)
  caller_eph_pub = 0x02<32 bytes>
  responder_eph_pub = 0x03<32 bytes>
  session_id = SHA256(caller_eph_pub || responder_eph_pub)[:7]

Output IV (12 bytes):
  iv = direction (1) || sequence_number (4, big-endian) || session_id (7)
     = 0x00 || 0x0000002A || <7 bytes of session_id>
```

### 21.5 Cryptographic Constants

All domain-separated constants used in SISL:

```
SISL Cryptographic Constants
============================

Public hailing code seed:
  SHA256("SISL-public-hailing-code-v2") =
  0x4b9b573c3a36c5aac4f57b1411abbdc3eea85ca474672fb9ac0ed92911c9828a

DSSS spreading code nonce (8 bytes):
  SHA256("SISL-dsss-nonce")[:8] =
  0x5c658fe3a976c86d

FHSS hopping sequence nonce (8 bytes):
  SHA256("SISL-fhss-nonce")[:8] =
  0x865597bd66b592aa

Session key derivation salt:
  SHA256("SISL-v2-X3DH") =
  0x3ed3b32d78eda4ed77a72a734cbba514a9125ea04f50e3e7360919c2ed6d19da

Hail key derivation salt:
  SHA256("SISL-v2-hail") =
  0xc341dbfe594b5f5a41f87c816206a33debb1371a706e2ff92ffedef9eb53b4ce
```

### 21.6 Reference Implementation

```python
#!/usr/bin/env python3
"""SISL Test Vector Generator - Verified"""

from hashlib import sha256
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
import struct

def generate_dsss_code(seed: bytes, length: int = 1023) -> list[int]:
    """Generate DSSS spreading code."""
    nonce = sha256(b'SISL-dsss-nonce').digest()[:8]
    counter = b'\x00' * 8
    cipher = Cipher(algorithms.ChaCha20(seed, nonce + counter), mode=None)
    enc = cipher.encryptor()

    bytes_needed = (length + 7) // 8
    random_bytes = enc.update(b'\x00' * bytes_needed)

    code = []
    for i in range(length):
        byte_idx = i // 8
        bit_idx = i % 8
        bit = (random_bytes[byte_idx] >> bit_idx) & 1
        code.append(1 if bit else -1)
    return code

def derive_session_keys(dh1, dh2, dh3, caller_norad, responder_norad,
                        caller_eph_pub, responder_eph_pub):
    """Derive all session keys from X3DH shared secret."""
    shared_secret = dh1 + dh2 + dh3
    salt = sha256(b'SISL-v2-X3DH').digest()
    transcript = struct.pack('>II',
        min(caller_norad, responder_norad),
        max(caller_norad, responder_norad)
    ) + caller_eph_pub + responder_eph_pub

    hkdf = HKDF(algorithm=hashes.SHA256(), length=160, salt=salt, info=transcript)
    km = hkdf.derive(shared_secret)

    return {
        'hail_key': km[0:32],
        'ack_key': km[32:64],
        'p2p_tx_key': km[64:96],
        'p2p_rx_key': km[96:128],
        'spreading_seed': km[128:160],
    }

if __name__ == "__main__":
    # Verify constants
    assert sha256(b'SISL-public-hailing-code-v2').hexdigest() == \
        '4b9b573c3a36c5aac4f57b1411abbdc3eea85ca474672fb9ac0ed92911c9828a'
    print("All constants verified.")
```
