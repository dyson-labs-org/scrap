from __future__ import annotations

import hashlib
import struct

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from sisl_crypto import derive_payload_iv, derive_rlnc_ack_iv


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
) -> bytes:
    h = hashlib.sha256(session_id + payload).digest()
    iv = derive_rlnc_ack_iv(session_prk)
    aad = session_id + b"sisl-ack"
    tag = ChaCha20Poly1305(reverse_direction_key).encrypt(iv, b"", aad)
    return h + tag


def decode_ack(
    frame: bytes,
    payload: bytes,
    reverse_direction_key: bytes,
    session_prk: bytes,
    session_id: bytes,
) -> bool:
    expected_hash = hashlib.sha256(session_id + payload).digest()
    if frame[:32] != expected_hash:
        return False
    iv = derive_rlnc_ack_iv(session_prk)
    aad = session_id + b"sisl-ack"
    try:
        ChaCha20Poly1305(reverse_direction_key).decrypt(iv, frame[32:], aad)
    except Exception:
        return False
    return True
