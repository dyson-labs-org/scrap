#!/usr/bin/env python3
"""
Generate cryptographic test vectors for the SCRAP protocol.

Uses the pure-Python `ecdsa` library (RFC 6979 deterministic nonces) with low-s
canonicalization, which matches libsecp256k1's signatures byte-for-byte, plus
`cbor2` for CBOR encoding. No C build required.

    python -m venv venv && venv/bin/pip install ecdsa cbor2
    venv/bin/python generate.py > computed.json

Capability-token signing scheme (normative, see spec/SCRAP.md §2.2.1 and
schemas/scap.cddl): the signature is over `protected = CBOR({header, payload})`,
the exact byte string carried on the wire. The legacy `header_cbor || payload_cbor`
concatenation fields are retained only to exercise the low-level sign/verify
primitive.
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict

import cbor2
from ecdsa import SigningKey, SECP256k1
from ecdsa.util import sigencode_der_canonize


@dataclass
class TestKeys:
    private_key_hex: str
    public_key_hex: str

    @classmethod
    def generate(cls, seed_hex: str) -> "TestKeys":
        sk = SigningKey.from_secret_exponent(int(seed_hex.replace("0x", ""), 16), curve=SECP256k1)
        p = sk.get_verifying_key().pubkey.point
        comp = ("02" if p.y() % 2 == 0 else "03") + "%064x" % p.x()
        return cls(private_key_hex=seed_hex, public_key_hex="0x" + comp)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sign_message(privkey_hex: str, message: bytes) -> bytes:
    """SHA-256-then-ECDSA, RFC 6979 deterministic, low-s (matches libsecp256k1)."""
    sk = SigningKey.from_secret_exponent(int(privkey_hex.replace("0x", ""), 16), curve=SECP256k1)
    return sk.sign_deterministic(message, hashfunc=hashlib.sha256, sigencode=sigencode_der_canonize)


def generate_capability_token_vector():
    operator_privkey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    operator_keys = TestKeys.generate(operator_privkey)

    header = {"alg": "ES256K", "typ": "SAT-CAP", "enc": "CBOR"}
    payload = {
        "iss": "OPERATOR-TEST",
        "sub": "SATELLITE-1-12345",
        "aud": "SATELLITE-2-12346",
        "iat": 1705320000,
        "exp": 1705406400,
        "jti": "test-imaging-001",
        "cap": ["cmd:imaging:msi"],
        "cns": {"max_area_km2": 1000},
    }

    header_cbor = cbor2.dumps(header)
    payload_cbor = cbor2.dumps(payload)

    # Legacy primitive: signature over header_cbor || payload_cbor.
    signing_input = header_cbor + payload_cbor
    legacy_sig = sign_message(operator_privkey, signing_input)

    # Normative token scheme: signature over protected = CBOR({header, payload}).
    protected = cbor2.dumps({"header": header, "payload": payload})
    protected_sig = sign_message(operator_privkey, protected)

    return {
        "description": "Simple imaging task capability token",
        "keys": {"operator": asdict(operator_keys)},
        "input": {"header": header, "payload": payload},
        "computed": {
            "header_cbor_hex": header_cbor.hex(),
            "payload_cbor_hex": payload_cbor.hex(),
            "signing_input_hash_hex": sha256(signing_input).hex(),
            "signature_der_hex": legacy_sig.hex(),
            # Normative protected-content scheme (carried verbatim, signed as bytes):
            "protected_hex": protected.hex(),
            "protected_hash_hex": sha256(protected).hex(),
            "protected_signature_der_hex": protected_sig.hex(),
            "token_complete": {
                "header_cbor": header_cbor.hex(),
                "payload_cbor": payload_cbor.hex(),
                "signature": legacy_sig.hex(),
            },
        },
    }


def generate_execution_proof_vector():
    executor_privkey = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    executor_keys = TestKeys.generate(executor_privkey)

    task_jti = "test-imaging-001"
    payment_hash = bytes.fromhex("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
    output_hash = bytes.fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    execution_timestamp = 1705321000

    proof_preimage = (
        task_jti.encode("utf-8") + payment_hash + output_hash + execution_timestamp.to_bytes(8, "big")
    )
    signature = sign_message(executor_privkey, proof_preimage)

    return {
        "description": "Valid execution proof for imaging task",
        "keys": {"executor": asdict(executor_keys)},
        "input": {
            "task_jti": task_jti,
            "payment_hash_hex": "0x" + payment_hash.hex(),
            "output_hash_hex": "0x" + output_hash.hex(),
            "execution_timestamp": execution_timestamp,
        },
        "computed": {
            "proof_preimage_hex": proof_preimage.hex(),
            "proof_hash_hex": sha256(proof_preimage).hex(),
            "signature_der_hex": signature.hex(),
        },
    }


def generate_binding_vector():
    requester_privkey = "2222222222222222222222222222222222222222222222222222222222222222"
    requester_keys = TestKeys.generate(requester_privkey)

    task_jti = "test-imaging-001"
    payment_hash = bytes.fromhex("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")

    binding_preimage = task_jti.encode("utf-8") + payment_hash
    binding_sig = sign_message(requester_privkey, binding_preimage)

    return {
        "description": "Valid payment-capability binding",
        "keys": {"requester": asdict(requester_keys)},
        "input": {
            "task_jti": task_jti,
            "payment_hash_hex": "0x" + payment_hash.hex(),
            "payment_amount_msat": 10000000,
            "htlc_timeout_blocks": 336,
        },
        "computed": {
            "binding_preimage_hex": binding_preimage.hex(),
            "binding_hash_hex": sha256(binding_preimage).hex(),
            "binding_signature_der_hex": binding_sig.hex(),
        },
    }


def generate_htlc_timeout_vectors():
    def calc(hops: int, dispute: int, contact_gap: int, margin: int):
        final_timeout = dispute + contact_gap + margin
        timeouts = [final_timeout]
        for _ in range(hops - 1):
            timeouts.insert(0, timeouts[0] + margin)
        return {
            "hops": hops,
            "input": {
                "dispute_window_blocks": dispute,
                "max_contact_gap_blocks": contact_gap,
                "margin_per_hop_blocks": margin,
            },
            "computed": {
                "timeout_chain_blocks": timeouts,
                "customer_timeout_blocks": timeouts[0],
                "customer_timeout_hours": round(timeouts[0] * 10 / 60, 1),
                "final_timeout_blocks": timeouts[-1],
            },
        }

    return [calc(1, 36, 12, 144), calc(2, 36, 12, 144), calc(3, 36, 12, 144)]


def main():
    vectors = {
        "version": "1.0.0",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": "Computed test vectors for SCAP protocol",
        "capability_token": generate_capability_token_vector(),
        "execution_proof": generate_execution_proof_vector(),
        "payment_binding": generate_binding_vector(),
        "htlc_timeouts": generate_htlc_timeout_vectors(),
    }
    print(json.dumps(vectors, indent=2))


if __name__ == "__main__":
    main()
