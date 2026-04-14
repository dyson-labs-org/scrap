from __future__ import annotations

import math
import bisect

from sisl_crypto import derive_coef_stream


def robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.5) -> list[float]:
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    R = c * math.log(K / delta) * math.sqrt(K)
    threshold = int(K / R)

    tau = [0.0] * (K + 1)
    for d in range(1, K + 1):
        if d < threshold:
            tau[d] = R / (K * d)
        elif d == threshold:
            tau[d] = R * math.log(R / delta) / K
        else:
            tau[d] = 0.0

    mu = [rho[d] + tau[d] for d in range(K + 1)]
    total = sum(mu[1:])
    normalized = [mu[d] / total for d in range(K + 1)]

    cdf = []
    cumsum = 0.0
    for d in range(1, K + 1):
        cumsum += normalized[d]
        cdf.append(cumsum)
    return cdf


def sample_degree(cdf: list[float], uniform_val: float) -> int:
    idx = bisect.bisect_left(cdf, uniform_val)
    idx = min(idx, len(cdf) - 1)
    return idx + 1


def sample_coefficients(
    comb_id: int,
    K: int,
    session_prk: bytes,
    c: float = 0.1,
    delta: float = 0.5,
) -> list[int]:
    length = 4 + 4 * K
    stream = derive_coef_stream(session_prk, comb_id, length)

    cdf = robust_soliton_cdf(K, c, delta)
    u = int.from_bytes(stream[0:2], 'big') / 65536.0
    d = sample_degree(cdf, u)

    indices = []
    pos = 2
    while len(indices) < d:
        if pos >= len(stream):
            stream = derive_coef_stream(session_prk, comb_id, pos + 4 * K)
        byte_val = stream[pos]
        pos += 1
        idx = byte_val % K
        if idx not in indices:
            indices.append(idx)

    return sorted(indices)


def fragment_payload(payload: bytes, K: int) -> list[bytes]:
    frag_size = math.ceil(len(payload) / K)
    frag_size = math.ceil(frag_size / 16) * 16
    if frag_size == 0:
        frag_size = 16
    padded = payload + b'\x00' * (frag_size * K - len(payload))
    return [padded[i * frag_size:(i + 1) * frag_size] for i in range(K)]


class RLNCEncoder:
    def __init__(self, payload: bytes, K: int, session_prk: bytes):
        self._fragments = fragment_payload(payload, K)
        self._K = K
        self._prk = session_prk

    def encode_symbol(self, comb_id: int) -> tuple[int, bytes, list[int]]:
        indices = sample_coefficients(comb_id, self._K, self._prk)
        frags = [self._fragments[i] for i in indices]
        result = bytearray(frags[0])
        for f in frags[1:]:
            for j in range(len(result)):
                result[j] ^= f[j]
        return (comb_id, bytes(result), indices)
