#!/usr/bin/env python3
"""
Verify cryptographic test vectors for SCRAP protocol.

This script validates that:
1. All signatures verify against their public keys
2. CBOR encoding/decoding roundtrips correctly
3. Hash computations match expected values

Usage:
    python verify_test_vectors.py [test_vectors.json]
"""

import hashlib
import json
import sys
from pathlib import Path

try:
    import secp256k1
    import cbor2
except ImportError:
    print("Error: Missing dependencies. Install with:")
    print("  pip install secp256k1 cbor2")
    sys.exit(1)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def verify_signature(pubkey_hex: str, message: bytes, sig_der_hex: str) -> bool:
    """Verify an ECDSA signature."""
    try:
        pubkey_bytes = bytes.fromhex(pubkey_hex.replace('0x', ''))
        sig_der = bytes.fromhex(sig_der_hex)

        pubkey = secp256k1.PublicKey(pubkey_bytes, raw=True)
        msg_hash = sha256(message)
        sig = pubkey.ecdsa_deserialize(sig_der)
        return pubkey.ecdsa_verify(msg_hash, sig, raw=True)  # raw=True: use hash directly
    except Exception as e:
        print(f"    Error during verification: {e}")
        return False


def verify_capability_token(token_data: dict) -> tuple[bool, list[str]]:
    """Verify capability token test vector."""
    results = []
    all_passed = True

    keys = token_data["keys"]["operator"]
    computed = token_data["computed"]

    header_cbor = bytes.fromhex(computed["header_cbor_hex"])
    payload_cbor = bytes.fromhex(computed["payload_cbor_hex"])
    signing_input = header_cbor + payload_cbor

    computed_hash = sha256(signing_input)
    expected_hash = bytes.fromhex(computed["signing_input_hash_hex"])
    if computed_hash == expected_hash:
        results.append("✓ Signing input hash matches")
    else:
        results.append("✗ Signing input hash mismatch")
        all_passed = False

    header_decoded = cbor2.loads(header_cbor)
    if header_decoded == token_data["input"]["header"]:
        results.append("✓ Header CBOR roundtrip OK")
    else:
        results.append("✗ Header CBOR roundtrip failed")
        all_passed = False

    payload_decoded = cbor2.loads(payload_cbor)
    if payload_decoded == token_data["input"]["payload"]:
        results.append("✓ Payload CBOR roundtrip OK")
    else:
        results.append("✗ Payload CBOR roundtrip failed")
        all_passed = False

    if verify_signature(keys["public_key_hex"], signing_input, computed["signature_der_hex"]):
        results.append("✓ Signature verifies")
    else:
        results.append("✗ Signature verification FAILED")
        all_passed = False

    return all_passed, results


def verify_execution_proof(proof_data: dict) -> tuple[bool, list[str]]:
    """Verify execution proof test vector."""
    results = []
    all_passed = True

    keys = proof_data["keys"]["executor"]
    input_data = proof_data["input"]
    computed = proof_data["computed"]

    task_jti = input_data["task_jti"]
    payment_hash = bytes.fromhex(input_data["payment_hash_hex"].replace('0x', ''))
    output_hash = bytes.fromhex(input_data["output_hash_hex"].replace('0x', ''))
    timestamp = input_data["execution_timestamp"]

    proof_preimage = (
        task_jti.encode('utf-8') +
        payment_hash +
        output_hash +
        timestamp.to_bytes(8, 'big')
    )

    expected_preimage = bytes.fromhex(computed["proof_preimage_hex"])
    if proof_preimage == expected_preimage:
        results.append("✓ Proof preimage construction OK")
    else:
        results.append("✗ Proof preimage mismatch")
        all_passed = False

    computed_hash = sha256(proof_preimage)
    expected_hash = bytes.fromhex(computed["proof_hash_hex"])
    if computed_hash == expected_hash:
        results.append("✓ Proof hash matches")
    else:
        results.append("✗ Proof hash mismatch")
        all_passed = False

    if verify_signature(keys["public_key_hex"], proof_preimage, computed["signature_der_hex"]):
        results.append("✓ Signature verifies")
    else:
        results.append("✗ Signature verification FAILED")
        all_passed = False

    return all_passed, results


def verify_payment_binding(binding_data: dict) -> tuple[bool, list[str]]:
    """Verify payment binding test vector."""
    results = []
    all_passed = True

    keys = binding_data["keys"]["requester"]
    input_data = binding_data["input"]
    computed = binding_data["computed"]

    task_jti = input_data["task_jti"]
    payment_hash = bytes.fromhex(input_data["payment_hash_hex"].replace('0x', ''))

    binding_preimage = task_jti.encode('utf-8') + payment_hash

    expected_preimage = bytes.fromhex(computed["binding_preimage_hex"])
    if binding_preimage == expected_preimage:
        results.append("✓ Binding preimage construction OK")
    else:
        results.append("✗ Binding preimage mismatch")
        all_passed = False

    computed_hash = sha256(binding_preimage)
    expected_hash = bytes.fromhex(computed["binding_hash_hex"])
    if computed_hash == expected_hash:
        results.append("✓ Binding hash matches")
    else:
        results.append("✗ Binding hash mismatch")
        all_passed = False

    if verify_signature(keys["public_key_hex"], binding_preimage, computed["binding_signature_der_hex"]):
        results.append("✓ Signature verifies")
    else:
        results.append("✗ Signature verification FAILED")
        all_passed = False

    return all_passed, results


def verify_htlc_timeouts(timeout_data: list) -> tuple[bool, list[str]]:
    """Verify HTLC timeout calculations."""
    results = []
    all_passed = True

    for case in timeout_data:
        hops = case["hops"]
        input_params = case["input"]
        computed = case["computed"]

        dispute = input_params["dispute_window_blocks"]
        contact_gap = input_params["max_contact_gap_blocks"]
        margin = input_params["margin_per_hop_blocks"]

        final_timeout = dispute + contact_gap + margin
        timeouts = [final_timeout]
        for _ in range(hops - 1):
            timeouts.insert(0, timeouts[0] + margin)

        if timeouts == computed["timeout_chain_blocks"]:
            results.append(f"✓ {hops}-hop timeout chain OK: {timeouts}")
        else:
            results.append(f"✗ {hops}-hop timeout chain mismatch: got {timeouts}, expected {computed['timeout_chain_blocks']}")
            all_passed = False

        expected_hours = round(timeouts[0] * 10 / 60, 1)
        if expected_hours == computed["customer_timeout_hours"]:
            results.append(f"  ✓ Customer timeout hours OK: {expected_hours}h")
        else:
            results.append(f"  ✗ Customer timeout hours mismatch")
            all_passed = False

    return all_passed, results


def main():
    if len(sys.argv) > 1:
        vectors_path = Path(sys.argv[1])
    else:
        vectors_path = Path(__file__).parent / "test_vectors_computed.json"

    if not vectors_path.exists():
        print(f"Error: Test vectors not found at {vectors_path}")
        print("Run generate_test_vectors.py first")
        sys.exit(1)

    with open(vectors_path) as f:
        vectors = json.load(f)

    print(f"SCRAP Test Vector Verification")
    print(f"=" * 50)
    print(f"Version: {vectors.get('version', 'unknown')}")
    print(f"Generated: {vectors.get('generated', 'unknown')}")
    print()

    all_passed = True

    print("1. Capability Token")
    print("-" * 30)
    passed, results = verify_capability_token(vectors["capability_token"])
    for r in results:
        print(f"   {r}")
    all_passed &= passed
    print()

    print("2. Execution Proof")
    print("-" * 30)
    passed, results = verify_execution_proof(vectors["execution_proof"])
    for r in results:
        print(f"   {r}")
    all_passed &= passed
    print()

    print("3. Payment Binding")
    print("-" * 30)
    passed, results = verify_payment_binding(vectors["payment_binding"])
    for r in results:
        print(f"   {r}")
    all_passed &= passed
    print()

    print("4. HTLC Timeouts")
    print("-" * 30)
    passed, results = verify_htlc_timeouts(vectors["htlc_timeouts"])
    for r in results:
        print(f"   {r}")
    all_passed &= passed
    print()

    print("=" * 50)
    if all_passed:
        print("ALL VERIFICATIONS PASSED ✓")
        sys.exit(0)
    else:
        print("SOME VERIFICATIONS FAILED ✗")
        sys.exit(1)


if __name__ == "__main__":
    main()
