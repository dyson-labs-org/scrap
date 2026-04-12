"""SISL DSSS spreading code generation.

Uses ChaCha20 as a cryptographically secure PRNG with a domain-separated
nonce. Ported from spec/SISL.md §4.5 and §21.6.
"""

from __future__ import annotations

import hashlib

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms


DSSS_NONCE_INPUT = b"SISL-dsss-nonce"

HAIL_CODE_SEED_INPUT = b"SISL-public-hailing-code-v3"

DEFAULT_CODE_LENGTH = 1023


def hail_code_seed() -> bytes:
    """32-byte seed for the public hailing spreading code (§4.6.1)."""
    return hashlib.sha256(HAIL_CODE_SEED_INPUT).digest()


def _chacha20_stream(seed: bytes, nonce_input: bytes, n_bytes: int) -> bytes:
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    nonce = hashlib.sha256(nonce_input).digest()[:8]
    counter = b"\x00" * 8
    cipher = Cipher(algorithms.ChaCha20(seed, nonce + counter), mode=None)
    enc = cipher.encryptor()
    return enc.update(b"\x00" * n_bytes)


def generate_dsss_code(seed: bytes, length: int = DEFAULT_CODE_LENGTH) -> np.ndarray:
    """Generate a bipolar ±1 DSSS spreading code of `length` chips.

    Returns an int8 ndarray of shape ``(length,)``.
    """
    n_bytes = (length + 7) // 8
    random_bytes = _chacha20_stream(seed, DSSS_NONCE_INPUT, n_bytes)
    bits = np.unpackbits(np.frombuffer(random_bytes, dtype=np.uint8),
                         bitorder="little")[:length]
    return (bits.astype(np.int8) * 2 - 1)


