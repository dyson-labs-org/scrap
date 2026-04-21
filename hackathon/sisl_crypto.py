"""SISL v3 crypto layer — single-correlator trial-decryption hail.

Implements the crypto primitives for PLAN-sisl-trial-decrypt Rev. 3:

    X3DH key agreement (secp256k1)
    ChaCha20-Poly1305 AEAD
    Elligator² ephemeral encoding (STUB — not spec-compliant)
    Hail and ACK frame encode/decode
    Deterministic IV derivation from DH1 via HKDF

DoS mitigation is NOT PoW-based. See §4.6.6: rate-limit + HW ECDH MUST for
production. PoW was removed from the design after review — at any difficulty
that doesn't hurt legit callers, it provides no real asymmetry against a
determined attacker.

References:
    spec/SISL.md §4.2, §4.3, §4.6, §4.7, §5.2, §5.3 (pending v3 drafts)
    PLAN-sisl-trial-decrypt Rev. 3

Dependencies: `cryptography` (pyca).
"""

from __future__ import annotations

import functools
import hashlib
import secrets
import struct
from dataclasses import dataclass

import numpy as np

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand

import sisl_fec
import sisl_framer as sf  # for differential_encode_bits used in encode_hail_fec


# ── Protocol constants ──────────────────────────────────────────────────────

SISL_VERSION = 0x03
MSG_HAIL = 0x01
MSG_ACK = 0x02
MSG_PAYLOAD = 0x03

ASM = b"\x1A\xCF\xFC\x1D"

CURVE = ec.SECP256K1()

SALT_HAIL_KEY = hashlib.sha256(b"SISL-v3-hail-key").digest()
SALT_HAIL_IV = hashlib.sha256(b"SISL-v3-hail-iv").digest()
SALT_ACK_KEY = hashlib.sha256(b"SISL-v3-ack-key").digest()
SALT_ACK_IV = hashlib.sha256(b"SISL-v3-ack-iv").digest()
SALT_X3DH = hashlib.sha256(b"SISL-v3-X3DH").digest()

# Frame layouts (bytes)
#
# Hail carries caller_static_pub (33 B compressed) inside the encrypted body
# so the responder can compute DH2 = ECDH(responder_eph, caller_static) on
# hail decrypt. This restores full X3DH mutual authentication at ACK time.
HAIL_FRAME_LEN = 135            # 4+1+1+64+49+16
ACK_FRAME_LEN = 95              # 4+1+1+64+9+16 (unchanged)
HAIL_BODY_LEN = 49              # 33 (caller_static_pub) + 14 (channel params) + 2 (payload_len)
ACK_BODY_LEN = 9
ELLIGATOR_LEN = 64
COMPRESSED_PUBKEY_LEN = 33
TAG_LEN = 16

# ── FEC frame layout ───────────────────────────────────────────────────────
#
# The FEC variant of the hail leaves the first 6 bytes (ASM + version + type)
# UNCODED so the receiver's coherent decoder can use them as a known pilot
# for phase tracking, and rate-1/2 K=9 convolutionally encodes the rest of
# the frame (eph_enc + ciphertext + tag = 127 bytes = 1016 bits).
#
# Channel layout:
#   [0   ..   48)   uncoded header bits (ASM + ver + type) — pilot
#   [48  .. 2096)   coded body bits (FEC over 1016 payload bits)
#
# Total channel bits: 48 + 2*(1016 + 8) = 48 + 2048 = 2096 (262 bytes).
HAIL_HEADER_LEN = 6                                          # ASM+ver+type
HAIL_BODY_PAYLOAD_LEN = HAIL_FRAME_LEN - HAIL_HEADER_LEN     # 127
HAIL_FEC_HEADER_BITS = HAIL_HEADER_LEN * 8                   # 48
HAIL_FEC_BODY_PAYLOAD_BITS = HAIL_BODY_PAYLOAD_LEN * 8       # 1016
HAIL_FEC_BODY_CODED_BITS = sisl_fec.coded_length(
    HAIL_FEC_BODY_PAYLOAD_BITS)                              # 2048
HAIL_FEC_TOTAL_BITS = HAIL_FEC_HEADER_BITS + HAIL_FEC_BODY_CODED_BITS  # 2096

# ── Block interleaver for FEC body bits ────────────────────────────────────
#
# A burst of interference (e.g., a WiFi frame at 2.4 GHz) wipes out a
# contiguous run of symbols. Without interleaving, those errors hit
# adjacent coded bits and exceed Viterbi's burst-correction capability.
# A block interleaver writes bits row-wise into a matrix and reads them
# column-wise (or vice versa), spreading any contiguous burst across the
# entire codeword so Viterbi sees scattered single-bit errors instead.
#
# Matrix dimensions: 32 rows × 64 columns = 2048 bits = HAIL_FEC_BODY_CODED_BITS.
# A 64-symbol burst (65 ms at 1 Mcps) becomes 64 single-bit errors
# spaced 32 symbols apart — well within Viterbi's correction capability
# (d_free = 12, can correct ~6 adjacent errors per constraint length).

_INTERLEAVE_ROWS = 32
_INTERLEAVE_COLS = HAIL_FEC_BODY_CODED_BITS // _INTERLEAVE_ROWS  # 64
assert _INTERLEAVE_ROWS * _INTERLEAVE_COLS == HAIL_FEC_BODY_CODED_BITS

# Pre-computed permutation indices (row-major write, column-major read)
_INTERLEAVE_PERM = np.arange(HAIL_FEC_BODY_CODED_BITS).reshape(
    _INTERLEAVE_ROWS, _INTERLEAVE_COLS
).T.ravel()
_DEINTERLEAVE_PERM = np.argsort(_INTERLEAVE_PERM)


def _interleave_bits(bits: np.ndarray) -> np.ndarray:
    """Block-interleave FEC coded body bits (uint8 array)."""
    return bits[_INTERLEAVE_PERM]


# ── ACK FEC frame layout ──────────────────────────────────────────────────
ACK_HEADER_LEN = 6                                          # ASM+ver+type
ACK_BODY_PAYLOAD_LEN = ACK_FRAME_LEN - ACK_HEADER_LEN       # 89
ACK_FEC_HEADER_BITS = ACK_HEADER_LEN * 8                    # 48
ACK_FEC_BODY_PAYLOAD_BITS = ACK_BODY_PAYLOAD_LEN * 8        # 712
ACK_FEC_BODY_CODED_BITS = sisl_fec.coded_length(
    ACK_FEC_BODY_PAYLOAD_BITS)                              # 1440
ACK_FEC_TOTAL_BITS = ACK_FEC_HEADER_BITS + ACK_FEC_BODY_CODED_BITS  # 1488

_ACK_INTERLEAVE_ROWS = 32
_ACK_INTERLEAVE_COLS = ACK_FEC_BODY_CODED_BITS // _ACK_INTERLEAVE_ROWS  # 45
assert _ACK_INTERLEAVE_ROWS * _ACK_INTERLEAVE_COLS == ACK_FEC_BODY_CODED_BITS

_ACK_INTERLEAVE_PERM = np.arange(ACK_FEC_BODY_CODED_BITS).reshape(
    _ACK_INTERLEAVE_ROWS, _ACK_INTERLEAVE_COLS
).T.ravel()
_ACK_DEINTERLEAVE_PERM = np.argsort(_ACK_INTERLEAVE_PERM)


def _deinterleave_llrs(llrs: np.ndarray) -> np.ndarray:
    """Undo block interleaving on soft LLR array (float32)."""
    return llrs[_DEINTERLEAVE_PERM]


def deinterleave_hail_body_llrs(llrs: np.ndarray) -> np.ndarray:
    """Public alias for hail body LLR deinterleaving (used by sisl_rx)."""
    return llrs[_DEINTERLEAVE_PERM]


# ── Key utilities ───────────────────────────────────────────────────────────

def generate_keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(CURVE)


def pubkey_to_compressed(pub: ec.EllipticCurvePublicKey) -> bytes:
    """Return 33-byte compressed secp256k1 pubkey (canonical form)."""
    return pub.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint,
    )


def compressed_to_pubkey(compressed: bytes) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(CURVE, compressed)


def ecdh(priv: ec.EllipticCurvePrivateKey,
         pub: ec.EllipticCurvePublicKey) -> bytes:
    """Return 32-byte ECDH shared secret (x-coordinate of shared point)."""
    return priv.exchange(ec.ECDH(), pub)


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=length, salt=salt, info=info
    ).derive(ikm)


# ── Elligator² stub (NOT spec-compliant) ────────────────────────────────────
#
# The spec §5.2 mandates Elligator² encoding of the ephemeral pubkey to make
# the wire bytes indistinguishable from uniform random. This is a STUB that
# preserves the 64-byte wire size but is trivially distinguishable from
# random (31 zero bytes + 1 sign byte + 32 x-coord bytes).
#
# Replace before any deployment claiming v3 compliance. See PLAN §2.1e.

def encode_ephemeral_pub_stub(pub: ec.EllipticCurvePublicKey) -> bytes:
    """STUB — NOT Elligator²."""
    compressed = pubkey_to_compressed(pub)       # 33 B: [0x02|0x03] || x
    sign_byte = compressed[0:1]
    x_coord = compressed[1:]                      # 32 B
    padding = b"\x00" * 31 + sign_byte            # 32 B
    return x_coord + padding                      # 64 B


def decode_ephemeral_pub_stub(encoded: bytes) -> ec.EllipticCurvePublicKey:
    """STUB — NOT Elligator². Single candidate via explicit sign byte."""
    if len(encoded) != ELLIGATOR_LEN:
        raise ValueError(f"expected {ELLIGATOR_LEN} bytes, got {len(encoded)}")
    x_coord = encoded[:32]
    sign_byte = encoded[63:64]
    if sign_byte not in (b"\x02", b"\x03"):
        raise ValueError("invalid sign byte in stub encoding")
    return compressed_to_pubkey(sign_byte + x_coord)


# Export the stub under the spec-level names so callers can swap
# implementations by re-binding these two symbols.
encode_ephemeral_pub = encode_ephemeral_pub_stub
decode_ephemeral_pub = decode_ephemeral_pub_stub


# ── Hail key / IV derivation ────────────────────────────────────────────────

def derive_hail_key(dh1: bytes) -> bytes:
    return hkdf_sha256(dh1, SALT_HAIL_KEY, b"", 32)


def derive_hail_iv(dh1: bytes) -> bytes:
    return hkdf_sha256(dh1, SALT_HAIL_IV, b"", 12)


# ── Hail body plaintext layout (14 bytes) ───────────────────────────────────

@dataclass
class HailBody:
    """Plaintext of the encrypted hail body.

    Byte layout (49 bytes total):
        0..33   caller_static_pub   33 B  (compressed secp256k1 pubkey)
        33..35  center_freq_offset   2 B  big-endian
        35      bandwidth_code       1 B
        36      mode                 1 B  (1=DSSS, 2=FHSS, 3=Hybrid)
        37      chip_rate_code       1 B  (0.1 Mcps units)
        38..46  body_nonce           8 B  (replay window)
        46      flags                1 B
        47..49  payload_len          2 B  little-endian uint16 (RLNC payload length)
    """
    caller_static_pub: bytes      # 33 B compressed
    center_freq_offset: int
    bandwidth_code: int
    mode: int
    chip_rate_code: int
    body_nonce: bytes             # 8 B
    flags: int
    payload_len: int              # RLNC payload length in bytes (0 = not specified)

    def pack(self) -> bytes:
        if len(self.caller_static_pub) != COMPRESSED_PUBKEY_LEN:
            raise ValueError(
                f"caller_static_pub must be {COMPRESSED_PUBKEY_LEN} bytes")
        if len(self.body_nonce) != 8:
            raise ValueError("body_nonce must be 8 bytes")
        packed = (
            self.caller_static_pub
            + struct.pack(">H", self.center_freq_offset)
            + bytes([self.bandwidth_code, self.mode, self.chip_rate_code])
            + self.body_nonce
            + bytes([self.flags])
            + struct.pack("<H", self.payload_len)
        )
        assert len(packed) == HAIL_BODY_LEN, (len(packed), HAIL_BODY_LEN)
        return packed

    @classmethod
    def unpack(cls, data: bytes) -> "HailBody":
        if len(data) != HAIL_BODY_LEN:
            raise ValueError(f"hail body must be {HAIL_BODY_LEN} bytes")
        return cls(
            caller_static_pub=data[0:33],
            center_freq_offset=struct.unpack(">H", data[33:35])[0],
            bandwidth_code=data[35],
            mode=data[36],
            chip_rate_code=data[37],
            body_nonce=data[38:46],
            flags=data[46],
            payload_len=struct.unpack("<H", data[47:49])[0],
        )


def make_test_hail_body(**overrides):
    defaults = dict(
        caller_static_pub=pubkey_to_compressed(generate_keypair().public_key()),
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        flags=0x03,
        payload_len=0,
    )
    defaults.update(overrides)
    return HailBody(**defaults)


# ── Hail encode / decode ────────────────────────────────────────────────────

class Ephemeral:
    """One-shot ephemeral private key holder.

    Enforces the §5.2 normative MUST: "caller MUST generate a fresh ephemeral
    key pair for every hail transmission, including retransmissions". The
    deterministic IV scheme (IV=HKDF(dh1)) makes Poly1305 nonce reuse
    catastrophic; zeroizing after first use is the cheapest enforcement.
    """

    def __init__(self) -> None:
        self._priv: ec.EllipticCurvePrivateKey | None = generate_keypair()
        self._pub = self._priv.public_key()

    @property
    def pub(self) -> ec.EllipticCurvePublicKey:
        return self._pub

    def peek(self) -> ec.EllipticCurvePrivateKey:
        """Return the private key WITHOUT consuming it.

        The caller side needs to retain the ephemeral private key to
        decode the ACK (compute DH3 = ECDH(caller_eph, responder_eph)).
        Use peek() before encode_hail_fec (which consume()s the key).
        """
        if self._priv is None:
            raise RuntimeError("Ephemeral already consumed")
        return self._priv

    def consume(self) -> ec.EllipticCurvePrivateKey:
        if self._priv is None:
            raise RuntimeError(
                "Ephemeral already consumed — generate a fresh one for each "
                "hail transmission (SISL v3 §5.2 normative MUST)"
            )
        priv = self._priv
        self._priv = None
        return priv


def encode_hail(
    caller_eph: Ephemeral,
    responder_static_pub: ec.EllipticCurvePublicKey,
    body: HailBody,
) -> bytes:
    """Produce a 100-byte SISL v3 hail frame.

    Consumes `caller_eph` (enforces ephemeral uniqueness). Returns the raw
    on-wire bytes: ASM || ver || type || eph_enc || ct || tag.
    """
    eph_enc = encode_ephemeral_pub(caller_eph.pub)
    caller_eph_priv = caller_eph.consume()

    # DH1 and key/IV derivation
    dh1 = ecdh(caller_eph_priv, responder_static_pub)
    hail_key = derive_hail_key(dh1)
    hail_iv = derive_hail_iv(dh1)

    header = bytes([SISL_VERSION, MSG_HAIL])
    aad = ASM + header + eph_enc

    aead = ChaCha20Poly1305(hail_key)
    ct_with_tag = aead.encrypt(hail_iv, body.pack(), aad)
    # pyca returns ciphertext||tag concatenated; split for clarity
    ciphertext = ct_with_tag[:HAIL_BODY_LEN]
    tag = ct_with_tag[HAIL_BODY_LEN:]
    assert len(tag) == TAG_LEN

    frame = aad + ciphertext + tag
    assert len(frame) == HAIL_FRAME_LEN, (len(frame), HAIL_FRAME_LEN)
    return frame


@dataclass
class DecodedHail:
    body: HailBody
    caller_eph_pub: ec.EllipticCurvePublicKey
    dh1: bytes                                     # for session key derivation
    caller_eph_pub_canonical: bytes                # 33 B transcript input
    caller_static_pub: ec.EllipticCurvePublicKey   # decoded from body


def decode_hail(
    frame: bytes,
    my_static_priv: ec.EllipticCurvePrivateKey,
) -> DecodedHail | None:
    """Trial-decrypt a hail. Return DecodedHail iff addressed to us.

    §5.2.1 workflow. Returns None on any cheap-reject (ASM, version,
    Elligator decode, GCM tag).
    """
    if len(frame) != HAIL_FRAME_LEN:
        return None

    # 1. ASM + version + type
    if frame[0:4] != ASM:
        return None
    if frame[4] != SISL_VERSION:
        return None
    if frame[5] != MSG_HAIL:
        return None

    eph_enc = frame[6:70]
    ciphertext_end = 70 + HAIL_BODY_LEN            # 70 + 47 = 117
    ciphertext = frame[70:ciphertext_end]
    tag = frame[ciphertext_end:ciphertext_end + TAG_LEN]

    # 2. Elligator decode (constant-time in real impl; stub is trivial)
    try:
        caller_eph_pub = decode_ephemeral_pub(eph_enc)
    except Exception:
        return None

    # 3. ECDH (the expensive step)
    dh1 = ecdh(my_static_priv, caller_eph_pub)

    # 4. Key/IV derivation
    hail_key = derive_hail_key(dh1)
    hail_iv = derive_hail_iv(dh1)

    # 5. Trial decrypt — Poly1305 tag is the identity oracle
    aad = frame[0:70]                              # ASM||ver||type||eph
    try:
        plaintext = ChaCha20Poly1305(hail_key).decrypt(
            hail_iv, ciphertext + tag, aad
        )
    except Exception:
        return None                                # not for us

    # Parse body; extract caller's static pubkey for full X3DH at ACK time
    body = HailBody.unpack(plaintext)
    try:
        caller_static_pub = compressed_to_pubkey(body.caller_static_pub)
    except Exception:
        return None                                # malformed static pubkey

    return DecodedHail(
        body=body,
        caller_eph_pub=caller_eph_pub,
        dh1=dh1,
        caller_eph_pub_canonical=pubkey_to_compressed(caller_eph_pub),
        caller_static_pub=caller_static_pub,
    )


# ── FEC-wrapped hail encode / decode ───────────────────────────────────────
#
# Production-path encode/decode that puts a rate-1/2 K=9 convolutional code
# over the body of the hail (eph_enc + ciphertext + tag) while leaving the
# 6-byte header (ASM + ver + msg_type) uncoded as a coherent-decoder pilot.
#
# At the operating point this buys ~6-8 dB of coding gain, pushing the chip-
# SNR floor from ~-22 dB (uncoded) to ~-28 dB (KSP-WCC §5).
#
# The crypto layer is unchanged: encode_hail_fec calls encode_hail to build
# the standard 133-byte frame and only changes the channel representation.
# decode_hail_fec_from_llrs runs the soft Viterbi over the body LLRs, packs
# the recovered bits into bytes, prepends the known header, and hands the
# reconstructed 133-byte frame to the unmodified decode_hail.

def encode_hail_fec(
    caller_eph: Ephemeral,
    responder_static_pub: ec.EllipticCurvePublicKey,
    body: HailBody,
) -> np.ndarray:
    """Produce a FEC-coded channel bit stream for one hail.

    Returns a uint8 ndarray of HAIL_FEC_TOTAL_BITS = 2096 bits, formed as
    [header_bits (48) || diff_encoded(coded_body_bits) (2048)]. Pass directly
    to sisl_framer.tx_bits_to_chips for transmission.

    Consumes `caller_eph` exactly once via the underlying encode_hail call.

    Encoder pipeline order (as documented in the panel review Q6):
        plaintext → ChaCha20-Poly1305 encrypt → frame bytes
                  → split header / body
                  → conv FEC encode body (rate-1/2 K=9, sisl_fec)
                  → differential encode coded body (seed = last header bit)
                  → concatenate uncoded header + diff-encoded coded body

    The differential encoding step is required by the DBPSK fast path on
    the receiver side: dbpsk_decode_from_pilot recovers the original
    code-bit sense via z_k = Re(y_k · conj(y_{k-1})), and that only
    decodes to the right bits if the TX side did differential encoding
    with the matching seed convention. The seed is the last header bit so
    the receiver's first body-bit differential decode anchors on the
    coherently-recovered last pilot symbol.
    """
    frame = encode_hail(caller_eph, responder_static_pub, body)
    header_bytes = frame[:HAIL_HEADER_LEN]
    body_bytes = frame[HAIL_HEADER_LEN:]
    assert len(body_bytes) == HAIL_BODY_PAYLOAD_LEN

    header_bits = np.unpackbits(np.frombuffer(header_bytes, dtype=np.uint8))
    body_bits = np.unpackbits(np.frombuffer(body_bytes, dtype=np.uint8))
    coded_body_bits = sisl_fec.encode(body_bits)
    assert len(coded_body_bits) == HAIL_FEC_BODY_CODED_BITS

    # Interleave: spread burst errors across the codeword so Viterbi
    # sees scattered single-bit errors instead of uncorrectable bursts.
    coded_body_bits = _interleave_bits(coded_body_bits)

    # Differential encode the FEC body. Seed = last header bit so the
    # receiver can anchor the first body-bit differential decode on the
    # coherently-recovered last pilot symbol.
    seed = int(header_bits[-1])
    diff_coded_body = sf.differential_encode_bits(coded_body_bits, seed=seed)

    out = np.empty(HAIL_FEC_TOTAL_BITS, dtype=np.uint8)
    out[:HAIL_FEC_HEADER_BITS] = header_bits
    out[HAIL_FEC_HEADER_BITS:] = diff_coded_body
    return out


def decode_hail_fec_from_llrs(
    llrs: np.ndarray,
    my_static_priv: ec.EllipticCurvePrivateKey,
) -> DecodedHail | None:
    """Trial-decrypt a FEC-coded hail from per-bit LLRs.

    `llrs` must be a length-HAIL_FEC_TOTAL_BITS float array using the
    sisl_framer convention (positive → bit 0, negative → bit 1). The first
    HAIL_FEC_HEADER_BITS LLRs are hard-decided into the uncoded header
    (ASM + version + msg_type) and used as a structural cheap-reject; the
    remaining HAIL_FEC_BODY_CODED_BITS LLRs are soft-Viterbi-decoded into
    HAIL_FEC_BODY_PAYLOAD_BITS payload bits and reassembled into the
    standard 133-byte hail frame for the existing decode_hail pipeline.
    """
    if len(llrs) < HAIL_FEC_TOTAL_BITS:
        return None
    llrs = np.asarray(llrs[:HAIL_FEC_TOTAL_BITS], dtype=np.float32)

    # The uncoded header (48 bits = ASM + version + msg_type) has no FEC
    # protection. At marginal SNR a few header bits may be wrong even
    # when the FEC body (which IS protected) would decode cleanly. Skip
    # the hard-decision cheap-reject on the header and let the FEC body
    # + Poly1305 tag be the definitive integrity check. The header bytes
    # used below are the KNOWN canonical values, not the received bits.

    coded_body_llrs = _deinterleave_llrs(llrs[HAIL_FEC_HEADER_BITS:])
    body_bits = sisl_fec.decode(coded_body_llrs, HAIL_FEC_BODY_PAYLOAD_BITS)
    body_bytes = np.packbits(body_bits).tobytes()
    assert len(body_bytes) == HAIL_BODY_PAYLOAD_LEN

    header_bytes = ASM + bytes([SISL_VERSION, MSG_HAIL])
    frame = header_bytes + body_bytes
    return decode_hail(frame, my_static_priv)


# ── ACK encode / decode (§5.3) ──────────────────────────────────────────────

@dataclass
class AckBody:
    status: int                                     # 1 B  (1=Ready, 2=Busy, 3=Reject)
    nonce_echo: bytes                               # 8 B  echoes hail body_nonce

    def pack(self) -> bytes:
        if len(self.nonce_echo) != 8:
            raise ValueError("nonce_echo must be 8 bytes")
        return bytes([self.status]) + self.nonce_echo

    @classmethod
    def unpack(cls, data: bytes) -> "AckBody":
        if len(data) != ACK_BODY_LEN:
            raise ValueError(f"ack body must be {ACK_BODY_LEN} bytes")
        return cls(status=data[0], nonce_echo=data[1:9])


def derive_ack_key(dh1: bytes, dh2: bytes, dh3: bytes, transcript: bytes) -> bytes:
    shared = dh1 + dh2 + dh3
    return hkdf_sha256(shared, SALT_ACK_KEY, transcript, 32)


def derive_ack_iv(dh1: bytes, dh2: bytes, dh3: bytes, transcript: bytes) -> bytes:
    shared = dh1 + dh2 + dh3
    return hkdf_sha256(shared, SALT_ACK_IV, transcript, 12)


def encode_ack_frame(
    responder_eph: Ephemeral,
    decoded_hail: DecodedHail,
    status: int = 1,
) -> bytes:
    """Produce a 95-byte SISL v3 ACK frame bound to the given hail.

    Uses the responder's own fresh ephemeral (consumed, one-shot rule).
    Echoes the hail's body_nonce for freshness. Encrypted under the full
    X3DH session key (DH1||DH2||DH3), providing mutual authentication:

        DH1 = ECDH(responder_static,  caller_ephemeral)   -- from hail decode
        DH2 = ECDH(responder_ephemeral, caller_static)    -- needs caller_static
        DH3 = ECDH(responder_ephemeral, caller_ephemeral)

    `decoded_hail` must include caller_static_pub (decoded from the hail
    body) and dh1 (already computed during hail decryption). The responder's
    static private key is no longer needed at ACK time — dh1 was computed
    from it at hail decode.
    """
    resp_eph_enc = encode_ephemeral_pub(responder_eph.pub)
    responder_eph_pub = responder_eph.pub
    resp_eph_priv = responder_eph.consume()

    # Full X3DH
    dh1 = decoded_hail.dh1
    dh2 = ecdh(resp_eph_priv, decoded_hail.caller_static_pub)
    dh3 = ecdh(resp_eph_priv, decoded_hail.caller_eph_pub)

    transcript = (
        decoded_hail.caller_eph_pub_canonical
        + pubkey_to_compressed(responder_eph_pub)
    )
    ack_key = derive_ack_key(dh1, dh2, dh3, transcript)
    ack_iv = derive_ack_iv(dh1, dh2, dh3, transcript)

    header = bytes([SISL_VERSION, MSG_ACK])
    aad = ASM + header + resp_eph_enc

    body = AckBody(status=status, nonce_echo=decoded_hail.body.body_nonce)
    ct_with_tag = ChaCha20Poly1305(ack_key).encrypt(ack_iv, body.pack(), aad)
    ciphertext = ct_with_tag[:ACK_BODY_LEN]
    tag = ct_with_tag[ACK_BODY_LEN:]
    assert len(tag) == TAG_LEN

    frame = aad + ciphertext + tag
    assert len(frame) == ACK_FRAME_LEN, (len(frame), ACK_FRAME_LEN)
    return frame


@dataclass
class DecodedAck:
    body: AckBody
    responder_eph_pub: ec.EllipticCurvePublicKey
    dh3: bytes


def decode_ack_frame(
    frame: bytes,
    caller_static_priv: ec.EllipticCurvePrivateKey,
    caller_eph_priv: ec.EllipticCurvePrivateKey,
    dh1: bytes,
    expected_nonce_echo: bytes,
) -> DecodedAck | None:
    """Verify and decrypt an ACK frame. Caller-side, full X3DH.

    Requires:
        caller_static_priv — to compute DH2 = ECDH(static, responder_eph)
        caller_eph_priv    — to compute DH3 = ECDH(caller_eph, responder_eph)
        dh1                — precomputed at hail-transmit time
                             (ECDH(caller_eph, target_static))
        expected_nonce_echo — from the hail body

    Successful decryption is the mutual-auth proof: the ack_key derives
    from dh1||dh2||dh3, so verifying the Poly1305 tag proves the responder
    possessed both `responder_static_priv` (needed to compute the matching
    dh1) AND `responder_ephemeral_priv` (needed to compute matching
    dh2 and dh3).
    """
    if len(frame) != ACK_FRAME_LEN:
        return None
    if frame[0:4] != ASM:
        return None
    if frame[4] != SISL_VERSION:
        return None
    if frame[5] != MSG_ACK:
        return None

    resp_eph_enc = frame[6:70]
    ciphertext = frame[70:79]                       # 9 B
    tag = frame[79:95]

    import os as _os
    _ACK_DEBUG = _os.environ.get("SISL_ACK_DEBUG")
    try:
        responder_eph_pub = decode_ephemeral_pub(resp_eph_enc)
    except Exception as _e:
        if _ACK_DEBUG:
            print(f"  [ACK_DEBUG] decode_ephemeral_pub failed: {_e}", flush=True)
        return None

    # Full X3DH — caller side
    dh2 = ecdh(caller_static_priv, responder_eph_pub)
    dh3 = ecdh(caller_eph_priv, responder_eph_pub)

    caller_eph_pub_canonical = pubkey_to_compressed(
        caller_eph_priv.public_key()
    )
    transcript = caller_eph_pub_canonical + pubkey_to_compressed(responder_eph_pub)

    ack_key = derive_ack_key(dh1, dh2, dh3, transcript)
    ack_iv = derive_ack_iv(dh1, dh2, dh3, transcript)

    aad = frame[0:70]
    try:
        plaintext = ChaCha20Poly1305(ack_key).decrypt(
            ack_iv, ciphertext + tag, aad
        )
    except Exception as _e:
        if _ACK_DEBUG:
            print(f"  [ACK_DEBUG] Poly1305 failed: {_e}", flush=True)
            print(f"  [ACK_DEBUG] resp_eph_enc[:8]={resp_eph_enc[:8].hex()} "
                  f"cipher={ciphertext.hex()} tag[:4]={tag[:4].hex()}", flush=True)
        return None

    body = AckBody.unpack(plaintext)
    if not secrets.compare_digest(body.nonce_echo, expected_nonce_echo):
        if _ACK_DEBUG:
            print(f"  [ACK_DEBUG] nonce mismatch: got={body.nonce_echo.hex()} "
                  f"expected={expected_nonce_echo.hex()}", flush=True)
        return None                                 # replay / wrong hail

    return DecodedAck(body=body, responder_eph_pub=responder_eph_pub, dh3=dh3)


# ── ACK FEC encode / decode ────────────────────────────────────────────────

def encode_ack_fec(
    responder_eph: Ephemeral,
    decoded_hail: DecodedHail,
    status: int = 1,
) -> np.ndarray:
    """Produce FEC-coded channel bits for one ACK.

    Returns uint8 ndarray of ACK_FEC_TOTAL_BITS = 1488 bits.
    Same pipeline as encode_hail_fec but for the 95-byte ACK frame.
    """
    frame = encode_ack_frame(responder_eph, decoded_hail, status)
    header_bytes = frame[:ACK_HEADER_LEN]
    body_bytes = frame[ACK_HEADER_LEN:]
    assert len(body_bytes) == ACK_BODY_PAYLOAD_LEN

    header_bits = np.unpackbits(np.frombuffer(header_bytes, dtype=np.uint8))
    body_bits = np.unpackbits(np.frombuffer(body_bytes, dtype=np.uint8))
    coded_body_bits = sisl_fec.encode(body_bits)
    assert len(coded_body_bits) == ACK_FEC_BODY_CODED_BITS

    coded_body_bits = coded_body_bits[_ACK_INTERLEAVE_PERM]
    seed = int(header_bits[-1])
    diff_coded_body = sf.differential_encode_bits(coded_body_bits, seed=seed)

    out = np.empty(ACK_FEC_TOTAL_BITS, dtype=np.uint8)
    out[:ACK_FEC_HEADER_BITS] = header_bits
    out[ACK_FEC_HEADER_BITS:] = diff_coded_body
    return out


def decode_ack_fec_from_llrs(
    llrs: np.ndarray,
    caller_static_priv: ec.EllipticCurvePrivateKey,
    caller_eph_priv: ec.EllipticCurvePrivateKey,
    dh1: bytes,
    expected_nonce_echo: bytes,
) -> DecodedAck | None:
    """Trial-decrypt a FEC-coded ACK from per-bit LLRs."""
    import os as _os
    _ACK_DEBUG = _os.environ.get("SISL_ACK_DEBUG")
    if len(llrs) < ACK_FEC_TOTAL_BITS:
        return None
    llrs = np.asarray(llrs[:ACK_FEC_TOTAL_BITS], dtype=np.float32)

    coded_body_llrs = llrs[ACK_FEC_HEADER_BITS:][_ACK_DEINTERLEAVE_PERM]
    body_bits = sisl_fec.decode(coded_body_llrs, ACK_FEC_BODY_PAYLOAD_BITS)
    body_bytes = np.packbits(body_bits).tobytes()
    assert len(body_bytes) == ACK_BODY_PAYLOAD_LEN

    if _ACK_DEBUG:
        # Check how many LLR bits have low confidence (near zero)
        low_conf = int(np.sum(np.abs(llrs[ACK_FEC_HEADER_BITS:]) < 1.0))
        print(f"  [ACK_DEBUG] FEC decode: {ACK_FEC_BODY_PAYLOAD_BITS} payload bits, "
              f"low-conf LLRs={low_conf}/{ACK_FEC_BODY_CODED_BITS}, "
              f"body[0:4]={body_bytes[:4].hex()}", flush=True)

    header_bytes = ASM + bytes([SISL_VERSION, MSG_ACK])
    frame = header_bytes + body_bytes
    return decode_ack_frame(frame, caller_static_priv, caller_eph_priv,
                            dh1, expected_nonce_echo)


# ── Session key derivation (§4.3 v3) ────────────────────────────────────────

def derive_session_keys(
    dh1: bytes, dh2: bytes, dh3: bytes,
    caller_eph_pub_canonical: bytes,
    responder_eph_pub_canonical: bytes,
) -> dict:
    """Derive v3 session keys from full X3DH shared secret.

    All three DH terms are combined: dh1||dh2||dh3 = 96 bytes. Both sides
    compute identical values independently. The transcript binds to
    canonical-compressed decoded ephemeral pubkeys (not Elligator bytes).
    """
    shared = dh1 + dh2 + dh3                        # 96 bytes
    transcript = caller_eph_pub_canonical + responder_eph_pub_canonical
    km = hkdf_sha256(shared, SALT_X3DH, transcript, 128)
    return {
        "p2p_tx_key": km[0:32],
        "p2p_rx_key": km[32:64],
        "spreading_seed": km[64:96],
        "session_id": km[96:112],
        "reserved": km[112:128],
    }


def derive_session_prk(session_keys: dict) -> bytes:
    ikm = (session_keys["p2p_tx_key"] + session_keys["p2p_rx_key"]
           + session_keys["session_id"])
    return hkdf_sha256(ikm, b"SISL-RLNC-v1", b"", 32)


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    return HKDFExpand(algorithm=hashes.SHA256(), length=length, info=info).derive(prk)


def derive_payload_iv(session_prk: bytes, comb_id: int) -> bytes:
    return _hkdf_expand(session_prk, b"sisl-payload-iv" + comb_id.to_bytes(4, 'big'), 12)


def derive_coef_stream(session_prk: bytes, comb_id: int, length: int) -> bytes:
    return _hkdf_expand(session_prk, b"sisl-rlnc-coef" + comb_id.to_bytes(4, 'big'), length)


def derive_rlnc_ack_iv(session_prk: bytes, seq: int) -> bytes:
    """Derive a per-retransmission IV for the RLNC payload ACK.

    ``seq`` is the retransmit sequence number (0, 1, 2, …).  Including it in
    the HKDF info string guarantees a unique (key, nonce) pair for every ACK
    burst, preventing the catastrophic nonce-reuse that a fixed IV would cause
    when the ACK is retransmitted multiple times per session.
    """
    return _hkdf_expand(session_prk, b"sisl-ack-iv" + seq.to_bytes(4, 'big'), 12)


# ── RLNC payload FEC frame layout ────────────────────────────────────────────
#
# Each RLNC payload symbol is framed identically to hail/ACK:
#   Header (uncoded, 6 B): ASM(4) + SISL_VERSION(1) + MSG_PAYLOAD(1)
#   Body (FEC-coded, rate-1/2 convolutional): encode_payload_symbol() output
#
# n_payload_bytes = len(encode_payload_symbol(...)) = 4 + frag_size + 16
# PAYLOAD_FEC_HEADER_BITS = 48 (same as hail/ACK)

PAYLOAD_HEADER_LEN = 6
PAYLOAD_FEC_HEADER_BITS = PAYLOAD_HEADER_LEN * 8  # 48


def payload_fec_total_bits(n_payload_bytes: int) -> int:
    """Total channel bits for one RLNC payload symbol frame."""
    return PAYLOAD_FEC_HEADER_BITS + sisl_fec.coded_length(n_payload_bytes * 8)


@functools.lru_cache(maxsize=8)
def _payload_deinterleave_perm(n_coded_bits: int) -> np.ndarray:
    """Return the inverse of _payload_interleave_perm (cached alongside it)."""
    return np.argsort(_payload_interleave_perm(n_coded_bits))


@functools.lru_cache(maxsize=8)
def _payload_interleave_perm(n_coded_bits: int) -> np.ndarray:
    """Return row-major→column-major interleave permutation for n_coded_bits.

    Selects the largest power-of-2 rows (up to 32) that evenly divides
    n_coded_bits, guaranteeing a non-trivial interleave for any coded length.
    Example: 912 bits → rows=16, cols=57 (16 is largest power-of-2 divisor ≤32).
    """
    for rows in (32, 16, 8, 4, 2):
        if n_coded_bits % rows == 0:
            cols = n_coded_bits // rows
            return np.arange(n_coded_bits).reshape(rows, cols).T.ravel()
    return np.arange(n_coded_bits)  # n_coded_bits==1: identity


def encode_payload_symbol_fec(payload_symbol_bytes: bytes) -> np.ndarray:
    """Produce FEC-coded channel bits for one RLNC payload symbol.

    payload_symbol_bytes — output of sisl_payload.encode_payload_symbol().
    Returns uint8 ndarray of payload_fec_total_bits(len(payload_symbol_bytes)) bits.
    """
    header = ASM + bytes([SISL_VERSION, MSG_PAYLOAD])
    header_bits = np.unpackbits(np.frombuffer(header, dtype=np.uint8))
    body_bits = np.unpackbits(np.frombuffer(payload_symbol_bytes, dtype=np.uint8))
    coded_body = sisl_fec.encode(body_bits)
    perm = _payload_interleave_perm(len(coded_body))
    coded_body = coded_body[perm]
    seed = int(header_bits[-1])
    diff_body = sf.differential_encode_bits(coded_body, seed=seed)
    return np.concatenate([header_bits, diff_body]).astype(np.uint8)


def decode_payload_symbol_fec_from_llrs(
    llrs: np.ndarray,
    n_payload_bytes: int,
) -> bytes | None:
    """FEC-decode RLNC payload symbol from per-bit LLRs.

    n_payload_bytes — expected output length (= 4 + frag_size + 16).
    Returns raw payload_symbol_bytes on success, None on FEC failure
    (caller is responsible for AEAD verify).
    """
    n_fec_bits = payload_fec_total_bits(n_payload_bytes)
    if len(llrs) < n_fec_bits:
        return None
    llrs = np.asarray(llrs[:n_fec_bits], dtype=np.float32)
    body_llrs = llrs[PAYLOAD_FEC_HEADER_BITS:]
    n_coded = len(body_llrs)
    body_llrs = body_llrs[_payload_deinterleave_perm(n_coded)]
    body_bits = sisl_fec.decode(body_llrs, n_payload_bytes * 8)
    return np.packbits(body_bits).tobytes()[:n_payload_bytes]
