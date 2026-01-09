#!/usr/bin/env python3
"""
Generate CBOR examples for CDDL schema validation.

Usage:
    python validate_examples.py                    # Generate all examples
    python validate_examples.py --validate         # Generate and validate against schema

Requires:
    pip install cbor2

For validation, install cddl tool:
    cargo install cddl
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import cbor2
except ImportError:
    print("Error: cbor2 not installed. Run: pip install cbor2")
    sys.exit(1)


EXAMPLES_DIR = Path(__file__).parent / "examples"


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def write_cbor(filename: str, data: dict) -> Path:
    ensure_dir(EXAMPLES_DIR)
    path = EXAMPLES_DIR / filename
    with open(path, "wb") as f:
        cbor2.dump(data, f)
    print(f"  Generated: {path}")
    return path


def write_json(filename: str, data: dict) -> Path:
    ensure_dir(EXAMPLES_DIR)
    path = EXAMPLES_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=lambda x: x.hex() if isinstance(x, bytes) else str(x))
    return path


def generate_capability_token():
    """Generate a valid capability token example."""
    header = {
        "alg": "ES256K",
        "typ": "SAT-CAP",
        "enc": "CBOR"
    }

    payload = {
        "iss": "OPERATOR-TEST",
        "sub": "SATELLITE-1-12345",
        "aud": "SATELLITE-2-12346",
        "iat": 1705320000,
        "exp": 1705406400,
        "jti": "test-imaging-001",
        "cap": ["cmd:imaging:msi", "cmd:downlink:starlink"],
        "cns": {
            "max_area_km2": 1000,
            "geographic_bounds": {
                "lat_min": -60.0,
                "lat_max": 60.0
            }
        }
    }

    # Placeholder signature (72 bytes DER)
    signature = bytes(72)

    token = {
        "header": header,
        "payload": payload,
        "signature": signature
    }

    write_cbor("capability_token.cbor", token)
    write_json("capability_token.json", token)
    return token


def generate_delegation_token():
    """Generate a delegated capability token."""
    header = {
        "alg": "ES256K",
        "typ": "SAT-CAP-DEL",
        "chn": 1
    }

    payload = {
        "iss": "SATELLITE-1-12345",
        "sub": "CUSTOMER-WALLET",
        "aud": "SATELLITE-2-12346",
        "iat": 1705320100,
        "exp": 1705406400,
        "jti": "test-imaging-001-del-1",
        "prf": "test-imaging-001",  # Parent token
        "cap": ["cmd:imaging:msi"],  # Subset of parent caps
        "cns": {
            "max_area_km2": 500  # More restrictive than parent
        }
    }

    signature = bytes(72)

    token = {
        "header": header,
        "payload": payload,
        "signature": signature
    }

    write_cbor("delegation_token.cbor", token)
    write_json("delegation_token.json", token)
    return token


def generate_bound_task_request():
    """Generate a bound task request with payment."""
    # Use actual test vector values
    capability_token_cbor = bytes.fromhex(
        "a8636973736d4f50455241544f522d544553546373756271534154454c4c4954452d312d"
        "31323334356361756471534154454c4c4954452d322d3132333436636961741a65a51e40"
        "636578701a65a66fc0636a746970746573742d696d6167696e672d30303163636170816f"
        "636d643a696d6167696e673a6d736963636e73a16c6d61785f617265615f6b6d321903e8"
    )

    payment_hash = bytes.fromhex(
        "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )

    request = {
        "capability_token": capability_token_cbor,
        "payment_hash": payment_hash,
        "payment_amount_msat": 10000000,
        "htlc_timeout_blocks": 336,
        "binding_sig": bytes(72)
    }

    write_cbor("bound_task_request.cbor", request)
    write_json("bound_task_request.json", request)
    return request


def generate_execution_proof():
    """Generate an execution proof."""
    proof = {
        "task_jti": "test-imaging-001",
        "payment_hash": bytes.fromhex(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        ),
        "output_hash": bytes.fromhex(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ),
        "execution_timestamp": 1705321000,
        "output_metadata": {
            "data_size_bytes": 2147483648,  # 2 GB
            "data_format": "GeoTIFF",
            "coverage_km2": 950.5,
            "sensor_mode": "MSI_ALL_BANDS"
        },
        "executor_sig": bytes(72)
    }

    write_cbor("execution_proof.cbor", proof)
    write_json("execution_proof.json", proof)
    return proof


def generate_dispute_message():
    """Generate a dispute message."""
    dispute = {
        "task_jti": "test-imaging-001",
        "payment_hash": bytes.fromhex(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        ),
        "dispute_type": "hash_mismatch",
        "evidence": {
            "proof_received": bytes(100),  # Placeholder
            "expected_output_hash": bytes.fromhex(
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "actual_output_hash": bytes.fromhex(
                "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
            )
        },
        "timestamp": 1705325000,
        "customer_sig": bytes(72)
    }

    write_cbor("dispute_message.cbor", dispute)
    write_json("dispute_message.json", dispute)
    return dispute


def generate_task_responses():
    """Generate various task response messages."""

    accepted = {
        "type": "ACCEPTED",
        "task_jti": "test-imaging-001",
        "accepted_at": 1705320200,
        "estimated_completion": 1705321800,
        "executor_sig": bytes(72)
    }
    write_cbor("task_accepted.cbor", accepted)

    rejected = {
        "type": "REJECTED",
        "task_jti": "test-imaging-002",
        "rejected_at": 1705320200,
        "reason": "CAPABILITY_DENIED",
        "detail": "Requested cmd:propulsion:thrust not in token capabilities",
        "executor_sig": bytes(72)
    }
    write_cbor("task_rejected.cbor", rejected)

    completed = {
        "type": "COMPLETED",
        "task_jti": "test-imaging-001",
        "proof": generate_execution_proof(),
        "data_location": {
            "method": "data_relay",
            "relay_satellite": "EDRS-C",
            "estimated_delivery": 1705322000
        }
    }
    write_cbor("task_completed.cbor", completed)

    failed = {
        "type": "FAILED",
        "task_jti": "test-imaging-003",
        "failed_at": 1705321500,
        "reason": "INSTRUMENT_FAULT",
        "detail": "MSI detector A temperature exceeded limit",
        "executor_sig": bytes(72)
    }
    write_cbor("task_failed.cbor", failed)


def generate_isl_message():
    """Generate an ISL-encapsulated SCRAP message."""
    msg = {
        "version": 1,
        "msg_type": "TASK_REQUEST",
        "sender": "SATELLITE-1-12345",
        "recipient": "SATELLITE-2-12346",
        "sequence": 42,
        "timestamp": 1705320100,
        "payload": generate_bound_task_request(),
        "hmac": bytes(32)
    }

    write_cbor("isl_scap_message.cbor", msg)
    write_json("isl_scap_message.json", msg)
    return msg


def generate_lightning_wrapper():
    """Generate a Lightning message wrapper."""
    # Example: update_add_htlc (type 128)
    wrapper = {
        "bolt_msg_type": 128,
        "bolt_payload": bytes(100),  # Placeholder HTLC message
        "channel_id": bytes(32)
    }

    write_cbor("lightning_wrapper.cbor", wrapper)
    return wrapper


def generate_heartbeat():
    """Generate a heartbeat message."""
    heartbeat = {
        "sender": "SATELLITE-1-12345",
        "timestamp": 1705320500,
        "channel_states": [
            {
                "channel_id": bytes(32),
                "local_balance_msat": 50000000,
                "remote_balance_msat": 50000000,
                "pending_htlcs": 1,
                "state": "ACTIVE"
            }
        ],
        "pending_htlcs": 1,
        "queue_depth": 3
    }

    write_cbor("heartbeat.cbor", heartbeat)
    write_json("heartbeat.json", heartbeat)
    return heartbeat


def validate_against_schema(cddl_path: Path, cbor_files: list[Path]) -> bool:
    """Validate CBOR files against CDDL schema using cddl tool."""
    all_valid = True

    for cbor_file in cbor_files:
        result = subprocess.run(
            ["cddl", str(cddl_path), "validate", str(cbor_file)],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print(f"  ✓ {cbor_file.name}: valid")
        else:
            print(f"  ✗ {cbor_file.name}: invalid")
            print(f"    {result.stderr.strip()}")
            all_valid = False

    return all_valid


def main():
    parser = argparse.ArgumentParser(description="Generate CDDL validation examples")
    parser.add_argument("--validate", action="store_true", help="Validate against schema")
    args = parser.parse_args()

    print("Generating CBOR examples...")

    generate_capability_token()
    generate_delegation_token()
    generate_bound_task_request()
    generate_execution_proof()
    generate_dispute_message()
    generate_task_responses()
    generate_isl_message()
    generate_lightning_wrapper()
    generate_heartbeat()

    print(f"\nGenerated examples in: {EXAMPLES_DIR}")

    if args.validate:
        print("\nValidating against schema...")
        cddl_path = Path(__file__).parent / "scap.cddl"

        if not cddl_path.exists():
            print(f"Error: Schema not found at {cddl_path}")
            sys.exit(1)

        # Check if cddl tool is available
        result = subprocess.run(["which", "cddl"], capture_output=True)
        if result.returncode != 0:
            print("Warning: cddl tool not found. Install with: cargo install cddl")
            print("Skipping validation.")
            return

        cbor_files = list(EXAMPLES_DIR.glob("*.cbor"))
        if validate_against_schema(cddl_path, cbor_files):
            print("\nAll examples valid!")
        else:
            print("\nSome examples failed validation.")
            sys.exit(1)


if __name__ == "__main__":
    main()
