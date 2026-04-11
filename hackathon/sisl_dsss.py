"""SISL DSSS / FHSS code generation — unchanged between v2 and v3.

Ported from spec/SISL.md §4.5 and §21.6. Uses ChaCha20 as a cryptographically
secure PRNG with domain-separated nonces for DSSS and FHSS.
"""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms


DSSS_NONCE_INPUT = b"SISL-dsss-nonce"
FHSS_NONCE_INPUT = b"SISL-fhss-nonce"

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


def generate_dsss_code(seed: bytes, length: int = DEFAULT_CODE_LENGTH) -> list[int]:
    """Generate a bipolar ±1 DSSS spreading code of `length` chips."""
    n_bytes = (length + 7) // 8
    random_bytes = _chacha20_stream(seed, DSSS_NONCE_INPUT, n_bytes)
    code = []
    for i in range(length):
        bit = (random_bytes[i // 8] >> (i % 8)) & 1
        code.append(1 if bit else -1)
    return code


def generate_fhss_sequence(seed: bytes, num_channels: int,
                           num_hops: int) -> list[int]:
    """Generate a frequency-hopping sequence of `num_hops` channel indices."""
    n_bytes = num_hops * 2
    random_bytes = _chacha20_stream(seed, FHSS_NONCE_INPUT, n_bytes)
    sequence = []
    for i in range(num_hops):
        val = int.from_bytes(random_bytes[i * 2:(i + 1) * 2], "big")
        sequence.append(val % num_channels)
    return sequence
