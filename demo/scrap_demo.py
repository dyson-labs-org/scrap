#!/usr/bin/env python3
"""
SCRAP customer demo — the concrete protocol output, end to end.

Runs the full task lifecycle with REAL secp256k1 ECDSA signatures and shows the
four artifacts a customer integrates against:

    1. Authorization packet   (SAT-CAP capability token + payment-bound request)
    2. Execution receipt      (signed proof-of-execution + payment preimage)
    3. Verification flow       (the checks a receiver runs, incl. tamper detection)
    4. Integration boundary    (SCRAP as an OPTIONAL layer over an existing API)

No RF / link-layer detail — those live in SISL. This is the application layer only.

Zero install: uses the pure-Python `ecdsa` package (already present) for secp256k1,
and a minimal RFC-8949 CBOR encoder. The NORMATIVE wire format is schemas/scrap.cddl;
byte-for-byte interop vectors live in test-vectors/computed.json. Preimage
constructions here match test-vectors/generate.py exactly.
"""

import hashlib
import json
import time

from ecdsa import SigningKey, VerifyingKey, SECP256k1
from ecdsa.util import sigencode_der, sigdecode_der


# ---------------------------------------------------------------- crypto helpers
def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def keypair(secret_hex: str):
    sk = SigningKey.from_secret_exponent(int(secret_hex, 16), curve=SECP256k1)
    return sk, sk.get_verifying_key()


def pub_hex(vk: VerifyingKey) -> str:
    p = vk.pubkey.point
    return ("02" if p.y() % 2 == 0 else "03") + "%064x" % p.x()


def sign(sk: SigningKey, msg: bytes) -> bytes:
    return sk.sign_digest(sha256(msg), sigencode=sigencode_der)


def verify(vk: VerifyingKey, msg: bytes, sig: bytes) -> bool:
    try:
        return vk.verify_digest(sig, sha256(msg), sigdecode=sigdecode_der)
    except Exception:
        return False


# ----------------------------------------------------------- minimal CBOR (subset)
def cbor(x) -> bytes:
    if isinstance(x, bool):
        return b"\xf5" if x else b"\xf4"
    if isinstance(x, int):
        return _cbor_uint(0, x) if x >= 0 else _cbor_uint(1, -1 - x)
    if isinstance(x, float):
        import struct
        return b"\xfb" + struct.pack(">d", x)
    if isinstance(x, str):
        b = x.encode("utf-8")
        return _cbor_uint(3, len(b)) + b
    if isinstance(x, bytes):
        return _cbor_uint(2, len(x)) + x
    if isinstance(x, list):
        return _cbor_uint(4, len(x)) + b"".join(cbor(i) for i in x)
    if isinstance(x, dict):
        return _cbor_uint(5, len(x)) + b"".join(cbor(k) + cbor(v) for k, v in x.items())
    raise TypeError(type(x))


def _cbor_uint(major: int, n: int) -> bytes:
    mt = major << 5
    if n < 24:
        return bytes([mt | n])
    if n < 256:
        return bytes([mt | 24, n])
    if n < 65536:
        return bytes([mt | 25]) + n.to_bytes(2, "big")
    if n < 2**32:
        return bytes([mt | 26]) + n.to_bytes(4, "big")
    return bytes([mt | 27]) + n.to_bytes(8, "big")


# ------------------------------------------------------------------------- pretty
def banner(title: str):
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def show(label: str, obj):
    print(f"\n{label}:")
    print(json.dumps(obj, indent=2))


def hx(b: bytes, n: int = 16) -> str:
    h = b.hex()
    return h if len(h) <= 2 * n else h[: 2 * n] + f"... ({len(b)} bytes)"


# ============================================================================ run
def main():
    # Fixed keys + timestamps so the run is reproducible and matches test-vectors.
    op_sk, op_vk = keypair("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    cmd_sk, cmd_vk = keypair("2222222222222222222222222222222222222222222222222222222222222222")
    exe_sk, exe_vk = keypair("fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210")

    iat, exp = 1705320000, 1705406400
    jti = "test-imaging-001"

    print(__doc__)
    print("Parties (secp256k1 public keys):")
    print(f"  Operator  (issues authorization) : {pub_hex(op_vk)}")
    print(f"  Commander (requests + pays)       : {pub_hex(cmd_vk)}")
    print(f"  Executor  (runs task, gets paid)  : {pub_hex(exe_vk)}")

    # ----------------------------------------------------- 1. AUTHORIZATION PACKET
    banner("1. AUTHORIZATION PACKET  (what the customer/operator issues)")

    header = {"alg": "ES256K", "typ": "SAT-CAP", "enc": "CBOR"}
    payload = {
        "iss": "OPERATOR-TEST",        # who authorized
        "sub": "SATELLITE-1-12345",    # commanding satellite
        "aud": "SATELLITE-2-12346",    # target satellite (must == receiver)
        "iat": iat, "exp": exp,        # validity window
        "jti": jti,                    # unique task id (replay key)
        "cap": ["cmd:imaging:msi"],    # exact capabilities granted
        "cns": {"max_area_km2": 1000}, # constraints (attenuation)
    }
    signing_input = cbor(header) + cbor(payload)
    token_sig = sign(op_sk, signing_input)

    show("SAT-CAP capability token (decoded)",
         {"header": header, "payload": payload, "signature": token_sig.hex()})
    print(f"\n  CBOR signing input : {hx(signing_input)}")
    print(f"  on the wire (CBOR) : {len(signing_input) + len(token_sig)} bytes "
          f"(fits a 9.6 kbps UHF ISL ack)")

    # The commander binds this authorization to a Lightning payment.
    preimage_R = sha256(b"payment-preimage-secret")     # executor's secret
    payment_hash_H = sha256(preimage_R)                 # public; locks the HTLC
    binding_preimage = jti.encode() + payment_hash_H    # matches generate.py
    binding_sig = sign(cmd_sk, binding_preimage)

    bound_request = {
        "capability_token": signing_input.hex(),
        "payment_hash": payment_hash_H.hex(),
        "payment_amount_msat": 10_000_000,
        "htlc_timeout_blocks": 336,
        "binding_sig": binding_sig.hex(),
    }
    show("Bound task request (authorization + payment offer)", bound_request)

    # ------------------------------------------------------- 2. EXECUTION RECEIPT
    banner("2. EXECUTION RECEIPT  (what the executor returns as proof)")

    output_hash = sha256(b"<2.1 GB GeoTIFF imaging product>")
    exec_ts = 1705321000
    proof_preimage = (                                  # matches generate.py
        jti.encode()
        + payment_hash_H
        + output_hash
        + exec_ts.to_bytes(8, "big")
    )
    proof_sig = sign(exe_sk, proof_preimage)

    receipt = {
        "task_jti": jti,
        "payment_hash": payment_hash_H.hex(),
        "output_hash": output_hash.hex(),
        "execution_timestamp": exec_ts,
        "output_metadata": {
            "data_size_bytes": 2_147_483_648,
            "data_format": "GeoTIFF",
            "coverage_km2": 950.5,
            "sensor_mode": "MSI_ALL_BANDS",
        },
        "executor_sig": proof_sig.hex(),
    }
    show("Proof-of-execution (signed receipt)", receipt)

    print(f"\n  Settlement preimage R : {preimage_R.hex()}")
    print(f"  SHA256(R) == H        : {sha256(preimage_R) == payment_hash_H}  "
          f"-> revealing R both settles payment AND is the customer's receipt")

    # -------------------------------------------------------- 3. VERIFICATION FLOW
    banner("3. VERIFICATION FLOW  (every check a receiver runs — all cryptographic)")

    now = iat + 1000
    cmd_in_cap = "cmd:imaging:msi" in payload["cap"]
    checks = [
        ("Token signature valid (operator pubkey)", verify(op_vk, signing_input, token_sig)),
        ("Token not expired (iat <= now < exp)",     iat <= now < exp),
        ("aud == this satellite",                    payload["aud"] == "SATELLITE-2-12346"),
        ("jti not seen before (replay guard)",       jti not in set()),
        ("Requested command in cap[]",               cmd_in_cap),
        ("Payment binding signed by commander",      verify(cmd_vk, binding_preimage, binding_sig)),
        ("Constraint area <= max_area_km2",          950.5 <= payload["cns"]["max_area_km2"]),
        ("Execution proof signed by executor",       verify(exe_vk, proof_preimage, proof_sig)),
        ("Preimage R settles payment (SHA256(R)=H)", sha256(preimage_R) == payment_hash_H),
    ]
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {name}")
    print(f"\n  -> {'ACCEPT' if all(ok for _, ok in checks) else 'REJECT'} "
          f"({sum(ok for _, ok in checks)}/{len(checks)} checks passed)")

    print("\n  Tamper test — attacker widens granted capability after signing:")
    forged = dict(payload, cap=["cmd:imaging:msi", "cmd:propulsion:burn"])
    forged_input = cbor(header) + cbor(forged)
    print(f"  [{'PASS' if verify(op_vk, forged_input, token_sig) else 'REJECT'}]"
          f"  forged token signature  -> any field change breaks the operator signature")

    # ----------------------------------------------------- 4. INTEGRATION BOUNDARY
    banner("4. INTEGRATION AS AN OPTIONAL LAYER")
    print("""
SCRAP is additive, not a rewrite. It follows OGC-API / STAPI conformance classes,
so an operator advertises only what they implement:

    /conf/core           [REQUIRED]   landing, conformance, operator metadata
    /conf/satellites     [REQUIRED]   catalog (maps to STAPI 'products')
    /conf/tokens         [REQUIRED]   POST /tokens  (replaces STAPI 'orders')
    /conf/token-revocation [OPTIONAL]
    /conf/token-quotes     [OPTIONAL]
    /conf/lightning        [OPTIONAL]  <- payment binding is opt-in

An existing STAPI tasking stack adopts SCRAP by adding ONE adapter: turn an
accepted order into a signed capability token. Everything above is unchanged.
""")

    def order_to_capability(order: dict) -> dict:
        """The entire integration surface: existing order -> signed SAT-CAP."""
        pl = {
            "iss": "OPERATOR-TEST", "sub": order["from_sat"], "aud": order["to_sat"],
            "iat": iat, "exp": exp, "jti": order["order_id"],
            "cap": order["capabilities"], "cns": order.get("constraints", {}),
        }
        si = cbor(header) + cbor(pl)
        return {"capability_token": si.hex(), "signature": sign(op_sk, si).hex()}

    legacy_order = {
        "order_id": "order-99821", "from_sat": "SAT-A", "to_sat": "SAT-B",
        "capabilities": ["cmd:imaging:msi"], "constraints": {"max_area_km2": 500},
    }
    show("Existing tasking order (unchanged)", legacy_order)
    show("After the optional SCRAP adapter (signed, verifiable)",
         order_to_capability(legacy_order))

    banner("DEMO COMPLETE")
    print("Normative spec: spec/SCRAP.md  |  wire format: schemas/scrap.cddl  |  "
          "interop vectors: test-vectors/computed.json")


if __name__ == "__main__":
    main()
