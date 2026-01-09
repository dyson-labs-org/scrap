#!/usr/bin/env python3
"""
Generate cryptographic test vectors for SCRAP protocol.

Requires:
    pip install secp256k1 cbor2

Usage:
    python generate_test_vectors.py > test_vectors_computed.json
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Optional

try:
    import secp256k1
    import cbor2
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    print("Warning: secp256k1 and/or cbor2 not installed. Install with:")
    print("  pip install secp256k1 cbor2")


@dataclass
class TestKeys:
    private_key_hex: str
    public_key_hex: str

    @classmethod
    def generate(cls, seed_hex: str) -> 'TestKeys':
        privkey_bytes = bytes.fromhex(seed_hex.replace('0x', ''))
        privkey = secp256k1.PrivateKey(privkey_bytes)
        pubkey = privkey.pubkey.serialize().hex()
        return cls(
            private_key_hex=seed_hex,
            public_key_hex='0x' + pubkey
        )


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sign_message(privkey_hex: str, message: bytes) -> bytes:
    privkey_bytes = bytes.fromhex(privkey_hex.replace('0x', ''))
    privkey = secp256k1.PrivateKey(privkey_bytes)
    msg_hash = sha256(message)
    sig = privkey.ecdsa_sign(msg_hash, raw=True)  # raw=True: use hash directly, don't double-hash
    return privkey.ecdsa_serialize(sig)


def verify_signature(pubkey_hex: str, message: bytes, sig_der: bytes) -> bool:
    pubkey_bytes = bytes.fromhex(pubkey_hex.replace('0x', ''))
    pubkey = secp256k1.PublicKey(pubkey_bytes, raw=True)
    msg_hash = sha256(message)
    sig = pubkey.ecdsa_deserialize(sig_der)
    return pubkey.ecdsa_verify(message, sig, raw=True)


def generate_capability_token_vector():
    operator_privkey = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    operator_keys = TestKeys.generate(operator_privkey)

    payload = {
        "iss": "OPERATOR-TEST",
        "sub": "SATELLITE-1-12345",
        "aud": "SATELLITE-2-12346",
        "iat": 1705320000,
        "exp": 1705406400,
        "jti": "test-imaging-001",
        "cap": ["cmd:imaging:msi"],
        "cns": {
            "max_area_km2": 1000
        }
    }

    header = {
        "alg": "ES256K",
        "typ": "SAT-CAP",
        "enc": "CBOR"
    }

    payload_cbor = cbor2.dumps(payload)
    header_cbor = cbor2.dumps(header)

    signing_input = header_cbor + payload_cbor
    signing_input_hash = sha256(signing_input)

    signature = sign_message(operator_privkey, signing_input)

    return {
        "description": "Simple imaging task capability token",
        "keys": {
            "operator": asdict(operator_keys)
        },
        "input": {
            "header": header,
            "payload": payload
        },
        "computed": {
            "header_cbor_hex": header_cbor.hex(),
            "payload_cbor_hex": payload_cbor.hex(),
            "signing_input_hash_hex": signing_input_hash.hex(),
            "signature_der_hex": signature.hex(),
            "token_complete": {
                "header_cbor": header_cbor.hex(),
                "payload_cbor": payload_cbor.hex(),
                "signature": signature.hex()
            }
        }
    }


def generate_execution_proof_vector():
    executor_privkey = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    executor_keys = TestKeys.generate(executor_privkey)

    task_jti = "test-imaging-001"
    payment_hash = bytes.fromhex("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
    output_hash = bytes.fromhex("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    execution_timestamp = 1705321000

    proof_preimage = (
        task_jti.encode('utf-8') +
        payment_hash +
        output_hash +
        execution_timestamp.to_bytes(8, 'big')
    )
    proof_hash = sha256(proof_preimage)

    signature = sign_message(executor_privkey, proof_preimage)

    return {
        "description": "Valid execution proof for imaging task",
        "keys": {
            "executor": asdict(executor_keys)
        },
        "input": {
            "task_jti": task_jti,
            "payment_hash_hex": "0x" + payment_hash.hex(),
            "output_hash_hex": "0x" + output_hash.hex(),
            "execution_timestamp": execution_timestamp
        },
        "computed": {
            "proof_preimage_hex": proof_preimage.hex(),
            "proof_hash_hex": proof_hash.hex(),
            "signature_der_hex": signature.hex()
        }
    }


def generate_binding_vector():
    requester_privkey = "2222222222222222222222222222222222222222222222222222222222222222"
    requester_keys = TestKeys.generate(requester_privkey)

    task_jti = "test-imaging-001"
    payment_hash = bytes.fromhex("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")
    payment_amount_msat = 10000000
    htlc_timeout_blocks = 336

    binding_preimage = task_jti.encode('utf-8') + payment_hash
    binding_hash = sha256(binding_preimage)
    binding_sig = sign_message(requester_privkey, binding_preimage)

    return {
        "description": "Valid payment-capability binding",
        "keys": {
            "requester": asdict(requester_keys)
        },
        "input": {
            "task_jti": task_jti,
            "payment_hash_hex": "0x" + payment_hash.hex(),
            "payment_amount_msat": payment_amount_msat,
            "htlc_timeout_blocks": htlc_timeout_blocks
        },
        "computed": {
            "binding_preimage_hex": binding_preimage.hex(),
            "binding_hash_hex": binding_hash.hex(),
            "binding_signature_der_hex": binding_sig.hex()
        }
    }


def generate_htlc_timeout_vectors():
    def calculate_timeouts(hops: int, dispute_window: int, contact_gap: int, margin: int):
        final_timeout = dispute_window + contact_gap + margin
        timeouts = [final_timeout]
        for _ in range(hops - 1):
            timeouts.insert(0, timeouts[0] + margin)
        return {
            "hops": hops,
            "input": {
                "dispute_window_blocks": dispute_window,
                "max_contact_gap_blocks": contact_gap,
                "margin_per_hop_blocks": margin
            },
            "computed": {
                "timeout_chain_blocks": timeouts,
                "customer_timeout_blocks": timeouts[0],
                "customer_timeout_hours": round(timeouts[0] * 10 / 60, 1),
                "final_timeout_blocks": timeouts[-1]
            }
        }

    return [
        calculate_timeouts(1, 36, 12, 144),
        calculate_timeouts(2, 36, 12, 144),
        calculate_timeouts(3, 36, 12, 144),
    ]


def main():
    if not HAS_DEPS:
        print(json.dumps({"error": "Missing dependencies: secp256k1, cbor2"}, indent=2))
        return

    vectors = {
        "version": "1.0.0",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": "Computed test vectors for SCRAP protocol",

        "capability_token": generate_capability_token_vector(),
        "execution_proof": generate_execution_proof_vector(),
        "payment_binding": generate_binding_vector(),
        "htlc_timeouts": generate_htlc_timeout_vectors(),
    }

    print(json.dumps(vectors, indent=2))


if __name__ == "__main__":
    main()
