from __future__ import annotations

import hashlib
import math
import secrets
import struct

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from sisl_crypto import derive_payload_iv, derive_rlnc_ack_iv


def _padded_block(payload: bytes, K: int) -> bytes:
    """Return the full zero-padded RLNC block (K * frag_size bytes).

    Both caller and responder hash this block for the ACK, so they agree
    regardless of whether the responder knows the original payload_len.
    The frag_size is derived identically from len(payload) and K on both sides.
    """
    frag_size = math.ceil(len(payload) / K)
    frag_size = math.ceil(frag_size / 16) * 16
    if frag_size == 0:
        frag_size = 16
    total = frag_size * K
    return payload + b'\x00' * (total - len(payload))


def encode_payload_symbol(
    comb_id: int,
    encoded_bytes: bytes,
    direction_key: bytes,
    session_prk: bytes,
    session_id: bytes,
) -> bytes:
    iv = derive_payload_iv(session_prk, comb_id)
    comb_id_bytes = struct.pack(">I", comb_id)
    aad = session_id + comb_id_bytes
    ct_and_tag = ChaCha20Poly1305(direction_key).encrypt(iv, encoded_bytes, aad)
    return comb_id_bytes + ct_and_tag


def decode_payload_symbol(
    frame: bytes,
    direction_key: bytes,
    session_prk: bytes,
    session_id: bytes,
) -> tuple[int, bytes]:
    comb_id_bytes = frame[:4]
    comb_id = struct.unpack(">I", comb_id_bytes)[0]
    iv = derive_payload_iv(session_prk, comb_id)
    aad = session_id + comb_id_bytes
    try:
        plaintext = ChaCha20Poly1305(direction_key).decrypt(iv, frame[4:], aad)
    except Exception as e:
        raise ValueError("AEAD authentication failed") from e
    return comb_id, plaintext


def encode_ack(
    payload: bytes,
    reverse_direction_key: bytes,
    session_prk: bytes,
    session_id: bytes,
    seq: int = 0,
    K: int = 1,
) -> bytes:
    """Encode a payload ACK frame.

    Frame layout (52 bytes):
      seq_bytes (4 B, big-endian uint32)  — retransmit sequence number
      AEAD ciphertext+tag (48 B)          — encrypts sha256(session_id+padded_block)

    The ACK hash covers the full zero-padded RLNC block (K * frag_size bytes)
    so both caller and responder hash the same bytes regardless of payload_len
    negotiation. ``seq`` is included in both the IV derivation and the AAD so
    every retransmission uses a unique (key, nonce) pair.
    """
    seq_bytes = struct.pack(">I", seq)
    block = _padded_block(payload, K)
    h = hashlib.sha256(session_id + block).digest()
    iv = derive_rlnc_ack_iv(session_prk, seq)
    aad = session_id + b"sisl-ack" + seq_bytes
    ct_and_tag = ChaCha20Poly1305(reverse_direction_key).encrypt(iv, h, aad)
    return seq_bytes + ct_and_tag


def decode_ack(
    frame: bytes,
    payload: bytes,
    reverse_direction_key: bytes,
    session_prk: bytes,
    session_id: bytes,
    K: int = 1,
) -> bool:
    """Decode and verify a payload ACK frame.

    Reads ``seq`` from the frame, derives the matching IV, decrypts the hash
    from inside the AEAD envelope, and verifies it against the expected padded
    block hash using a constant-time comparison.
    """
    if len(frame) < 4 + 32 + 16:
        return False
    seq_bytes = frame[:4]
    seq = struct.unpack(">I", seq_bytes)[0]
    iv = derive_rlnc_ack_iv(session_prk, seq)
    aad = session_id + b"sisl-ack" + seq_bytes
    try:
        h_decrypted = ChaCha20Poly1305(reverse_direction_key).decrypt(
            iv, frame[4:], aad)
    except Exception:
        return False
    block = _padded_block(payload, K)
    expected_hash = hashlib.sha256(session_id + block).digest()
    if not secrets.compare_digest(h_decrypted, expected_hash):
        print(f"  [ACK ERROR] hash mismatch: decoded {len(payload)} bytes "
              f"(padded block {len(block)}B, K={K})", flush=True)
        return False
    return True
