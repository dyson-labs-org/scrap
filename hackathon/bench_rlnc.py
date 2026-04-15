from __future__ import annotations

import numpy as np

from sparse_rlnc import RLNCEncoder, RLNCDecoder
from sisl_payload import encode_payload_symbol, decode_payload_symbol, encode_ack, decode_ack
from sisl_crypto import derive_session_keys, derive_session_prk

PAYLOAD_512 = bytes(range(256)) * 2
PAYLOAD_100 = b"Hello SISL RLNC!" * 6 + b"!!"


def _make_session_keys():
    from cryptography.hazmat.primitives.asymmetric import ec
    from sisl_crypto import CURVE, ecdh, pubkey_to_compressed
    caller_priv = ec.derive_private_key(int.from_bytes(bytes(range(32)), 'big'), CURVE)
    resp_priv = ec.derive_private_key(int.from_bytes(bytes(range(1, 33)), 'big'), CURVE)
    caller_pub = caller_priv.public_key()
    resp_pub = resp_priv.public_key()
    dh1 = ecdh(caller_priv, resp_pub)
    dh2 = ecdh(resp_priv, caller_pub)
    dh3 = dh1
    caller_eph = pubkey_to_compressed(caller_pub)
    resp_eph = pubkey_to_compressed(resp_pub)
    return derive_session_keys(dh1, dh2, dh3, caller_eph, resp_eph)


def run_bec_trial(payload: bytes, K: int, session_keys: dict, n_to_receive: int, rng: np.random.Generator) -> bool:
    prk = derive_session_prk(session_keys)
    session_id = session_keys["session_id"]
    tx_key = session_keys["p2p_tx_key"]
    enc = RLNCEncoder(payload, K, prk)
    dec = RLNCDecoder(K, prk)
    for comb_id in range(n_to_receive):
        _, encoded_bytes, _ = enc.encode_symbol(comb_id)
        frame = encode_payload_symbol(comb_id, encoded_bytes, tx_key, prk, session_id)
        got_id, plain = decode_payload_symbol(frame, tx_key, prk, session_id)
        if dec.add_symbol(got_id, plain):
            return True
    return dec.is_complete


def measure_p_decode(payload: bytes, K: int, session_keys: dict, n_received: int, n_trials: int = 500) -> float:
    rng = np.random.default_rng(42)
    successes = sum(run_bec_trial(payload, K, session_keys, n_received, rng) for _ in range(n_trials))
    return successes / n_trials


def measure_overhead(payload: bytes, K: int, session_keys: dict, n_trials: int = 200) -> tuple[float, float]:
    rng = np.random.default_rng(99)
    epsilons = []
    prk = derive_session_prk(session_keys)
    session_id = session_keys["session_id"]
    tx_key = session_keys["p2p_tx_key"]
    for _ in range(n_trials):
        enc = RLNCEncoder(payload, K, prk)
        dec = RLNCDecoder(K, prk)
        for comb_id in range(4 * K):
            _, encoded_bytes, _ = enc.encode_symbol(comb_id)
            frame = encode_payload_symbol(comb_id, encoded_bytes, tx_key, prk, session_id)
            got_id, plain = decode_payload_symbol(frame, tx_key, prk, session_id)
            if dec.add_symbol(got_id, plain):
                epsilons.append((comb_id + 1) / K - 1.0)
                break
    eps = np.array(epsilons)
    return float(np.mean(eps)), float(np.std(eps))


def sweep_p_decode(K: int, payload: bytes, session_keys: dict) -> dict:
    result = {}
    for extra in [0, 1, 2, 3, 5, 8]:
        n = K + extra
        result[n] = measure_p_decode(payload, K, session_keys, n, n_trials=500)
    return result


def bench_periodic_interference(K: int, payload: bytes, session_keys: dict, slot_period: int = 4, bad_slots: int = 1) -> dict:
    prk = derive_session_prk(session_keys)
    session_id = session_keys["session_id"]
    tx_key = session_keys["p2p_tx_key"]
    n_trials = 300
    n_symbols = K + 8

    erasure_rate = bad_slots / slot_period

    rlnc_successes = 0
    rep_successes = 0

    for trial in range(n_trials):
        enc = RLNCEncoder(payload, K, prk)
        dec = RLNCDecoder(K, prk)
        received = 0
        for comb_id in range(n_symbols):
            slot_in_period = comb_id % slot_period
            erased = slot_in_period < bad_slots
            if not erased:
                _, encoded_bytes, _ = enc.encode_symbol(comb_id)
                frame = encode_payload_symbol(comb_id, encoded_bytes, tx_key, prk, session_id)
                got_id, plain = decode_payload_symbol(frame, tx_key, prk, session_id)
                dec.add_symbol(got_id, plain)
                received += 1
        if dec.is_complete:
            rlnc_successes += 1

        needed_for_rep = int(np.ceil(K / (1.0 - erasure_rate)))
        if needed_for_rep <= n_symbols:
            rep_successes += 1
        else:
            pass

    return {
        "rlnc_p_decode": rlnc_successes / n_trials,
        "rep_stalls": (rep_successes / n_trials < 0.9),
        "erasure_rate": erasure_rate,
    }


if __name__ == "__main__":
    session_keys = _make_session_keys()

    for K, payload in [(16, PAYLOAD_512), (32, PAYLOAD_512)]:
        sweep = sweep_p_decode(K, payload, session_keys)
        eps_mean, eps_std = measure_overhead(payload, K, session_keys, n_trials=200)
        parts = [f"K={K}"]
        for n, p in sweep.items():
            label = f"n=K+{n-K}" if n > K else "n=K+0"
            parts.append(f"{label}: P={p:.3f}")
        parts.append(f"ε={eps_mean:.3f}±{eps_std:.3f}")
        print("  ".join(parts))

    res = bench_periodic_interference(16, PAYLOAD_512, session_keys, slot_period=4, bad_slots=1)
    print(f"Periodic interference (K=16, period=4, 1 bad slot per period): P={res['rlnc_p_decode']:.3f}  erasure_rate={res['erasure_rate']:.2f}")
