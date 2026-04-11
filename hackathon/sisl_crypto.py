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

import hashlib
import secrets
import struct
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ── Protocol constants ──────────────────────────────────────────────────────

SISL_VERSION = 0x03
MSG_HAIL = 0x01
MSG_ACK = 0x02
MSG_NACK = 0x03

ASM = b"\x1A\xCF\xFC\x1D"

CURVE = ec.SECP256K1()

SALT_HAIL_KEY = hashlib.sha256(b"SISL-v3-hail-key").digest()
SALT_HAIL_IV = hashlib.sha256(b"SISL-v3-hail-iv").digest()
SALT_ACK_KEY = hashlib.sha256(b"SISL-v3-ack-key").digest()
SALT_ACK_IV = hashlib.sha256(b"SISL-v3-ack-iv").digest()
SALT_X3DH = hashlib.sha256(b"SISL-v3-X3DH").digest()

# Frame layouts (bytes)
HAIL_FRAME_LEN = 100            # 4+1+1+64+14+16
ACK_FRAME_LEN = 95              # 4+1+1+64+9+16
HAIL_BODY_LEN = 14
ACK_BODY_LEN = 9
ELLIGATOR_LEN = 64
TAG_LEN = 16


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
    center_freq_offset: int       # 2 B big-endian
    bandwidth_code: int           # 1 B
    mode: int                     # 1 B  (1=DSSS, 2=FHSS, 3=Hybrid)
    chip_rate_code: int           # 1 B  (0.1 Mcps units)
    body_nonce: bytes             # 8 B  (replay window)
    flags: int                    # 1 B

    def pack(self) -> bytes:
        if len(self.body_nonce) != 8:
            raise ValueError("body_nonce must be 8 bytes")
        return (
            struct.pack(">H", self.center_freq_offset)
            + bytes([self.bandwidth_code, self.mode, self.chip_rate_code])
            + self.body_nonce
            + bytes([self.flags])
        )

    @classmethod
    def unpack(cls, data: bytes) -> "HailBody":
        if len(data) != HAIL_BODY_LEN:
            raise ValueError(f"hail body must be {HAIL_BODY_LEN} bytes")
        center = struct.unpack(">H", data[0:2])[0]
        return cls(
            center_freq_offset=center,
            bandwidth_code=data[2],
            mode=data[3],
            chip_rate_code=data[4],
            body_nonce=data[5:13],
            flags=data[13],
        )


# ── Hail encode / decode ────────────────────────────────────────────────────

class Ephemeral:
    """One-shot ephemeral private key holder.

    Enforces the §5.2 normative MUST: "caller MUST generate a fresh ephemeral
    key pair for every hail transmission, including retransmissions". The
    deterministic IV scheme (IV=HKDF(dh1)) makes Poly1305 nonce reuse
    catastrophic; zeroizing after first use is the cheapest enforcement.
    """

    def __init__(self) -> None:
        self._priv: Optional[ec.EllipticCurvePrivateKey] = generate_keypair()
        self._pub = self._priv.public_key()

    @property
    def pub(self) -> ec.EllipticCurvePublicKey:
        return self._pub

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


def decode_hail(
    frame: bytes,
    my_static_priv: ec.EllipticCurvePrivateKey,
) -> Optional[DecodedHail]:
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
    ciphertext = frame[70:84]
    tag = frame[84:100]

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

    return DecodedHail(
        body=HailBody.unpack(plaintext),
        caller_eph_pub=caller_eph_pub,
        dh1=dh1,
        caller_eph_pub_canonical=pubkey_to_compressed(caller_eph_pub),
    )


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


def encode_ack(
    responder_static_priv: ec.EllipticCurvePrivateKey,
    responder_eph: Ephemeral,
    caller_eph_pub: ec.EllipticCurvePublicKey,
    decoded_hail: DecodedHail,
    status: int = 1,
) -> bytes:
    """Produce a 95-byte SISL v3 ACK frame bound to the given hail.

    Uses the responder's own fresh ephemeral. Consumes it (same one-shot
    rule). Echoes the hail's body_nonce for freshness.
    """
    resp_eph_enc = encode_ephemeral_pub(responder_eph.pub)
    responder_eph_pub = responder_eph.pub
    resp_eph_priv = responder_eph.consume()

    # SPEC NOTE (v3 departure from plan §5.3 full-X3DH claim):
    #
    # The plan §5.3 draft asserts the ACK is encrypted under a key derived
    # from "full X3DH shared secret (DH1||DH2||DH3)". But DH2 is defined as
    # ECDH(caller_static, responder_eph) and the responder computes it as
    # ECDH(responder_eph_priv, caller_static_pub). In v3 the responder does
    # NOT learn caller_static_pub from the hail — there is no plaintext
    # caller ID and no caller static field in the encrypted body.
    #
    # Options the spec must choose between:
    #   (A) Carry caller_static_pub (33 B) inside the encrypted hail body.
    #       Responder learns it on successful trial decrypt, computes full
    #       X3DH, encrypts ACK with full session key. Plan text then correct.
    #   (B) Accept that v3 ACK uses DH1||DH3 only. Responder authenticates
    #       to caller (DH1 needs target_static_priv, DH3 needs responder_eph).
    #       Caller authenticates to responder post-handshake via Merkle proof
    #       in first P2P frame. ACK alone provides responder-only auth.
    #
    # For this implementation we choose (B): keeps the hail frame at 108 B,
    # defers caller auth to the P2P layer (which already has a plan to carry
    # the Merkle proof). Follow-up issue filed to resolve in the spec draft.
    dh1 = decoded_hail.dh1
    dh3 = ecdh(resp_eph_priv, caller_eph_pub)
    dh2 = b""                                       # see note above
    _ = responder_static_priv                       # not needed under option (B)

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


def decode_ack(
    frame: bytes,
    caller_eph_priv: ec.EllipticCurvePrivateKey,
    dh1: bytes,
    expected_nonce_echo: bytes,
) -> Optional[DecodedAck]:
    """Verify and decrypt an ACK frame. Caller-side.

    Requires the caller's hail-time DH1 (= ECDH(caller_eph, target_static))
    and the expected nonce echo from the hail body.
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

    try:
        responder_eph_pub = decode_ephemeral_pub(resp_eph_enc)
    except Exception:
        return None

    dh3 = ecdh(caller_eph_priv, responder_eph_pub)
    dh2 = b""

    # Transcript: caller ephemeral (we have our pub) || responder ephemeral
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
    except Exception:
        return None

    body = AckBody.unpack(plaintext)
    if not secrets.compare_digest(body.nonce_echo, expected_nonce_echo):
        return None                                 # replay / wrong hail

    return DecodedAck(body=body, responder_eph_pub=responder_eph_pub, dh3=dh3)


# ── Session key derivation (§4.3 v3) ────────────────────────────────────────

def derive_session_keys(
    dh1: bytes, dh3: bytes,
    caller_eph_pub_canonical: bytes,
    responder_eph_pub_canonical: bytes,
) -> dict:
    """Derive v3 session keys from available DH terms.

    In v3, DH2 = ECDH(caller_static, responder_eph) is not available at ACK
    time (caller identity unknown). The session-key schedule uses dh1||dh3
    only; mutual authentication of caller completes at first P2P frame via
    Merkle proof (§15.3 future).
    """
    shared = dh1 + dh3                              # 64 bytes
    transcript = caller_eph_pub_canonical + responder_eph_pub_canonical
    km = hkdf_sha256(shared, SALT_X3DH, transcript, 128)
    return {
        "p2p_tx_key": km[0:32],
        "p2p_rx_key": km[32:64],
        "spreading_seed": km[64:96],
        "reserved": km[96:128],
    }
