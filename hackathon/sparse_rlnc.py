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
    stream = derive_coef_stream(session_prk, comb_id, 2 + 4 * K)

    cdf = robust_soliton_cdf(K, c, delta)
    u = int.from_bytes(stream[0:2], 'big') / 65536.0
    d = sample_degree(cdf, u)

    indices: list[int] = []
    pos = 2
    attempts = 0
    max_attempts = 4 * K
    while len(indices) < d and attempts < max_attempts:
        idx = stream[pos % len(stream)] % K
        pos += 1
        attempts += 1
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


class RLNCDecoder:
    def __init__(self, K: int, session_prk: bytes):
        self._K = K
        self._prk = session_prk
        self._symbols: list[tuple[list[int], bytearray]] = []
        self._recovered: dict[int, bytes] = {}

    def _peel(self) -> None:
        changed = True
        while changed and len(self._recovered) < self._K:
            changed = False
            for active_set, enc_bytes in self._symbols:
                to_remove = [i for i in list(active_set) if i in self._recovered]
                for i in to_remove:
                    frag = self._recovered[i]
                    for j in range(len(enc_bytes)):
                        enc_bytes[j] ^= frag[j]
                    active_set.remove(i)
                if len(active_set) == 1:
                    frag_idx = active_set[0]
                    if frag_idx not in self._recovered:
                        self._recovered[frag_idx] = bytes(enc_bytes)
                        active_set.clear()
                        changed = True

    def add_symbol(self, comb_id: int, encoded_bytes: bytes) -> bool:
        indices = sample_coefficients(comb_id, self._K, self._prk)
        self._symbols.append((indices, bytearray(encoded_bytes)))
        self._peel()
        return self.is_complete

    def decode(self) -> bytes | None:
        self._peel()
        if len(self._recovered) < self._K:
            return None
        parts = [self._recovered[i] for i in range(self._K)]
        return b''.join(parts)

    @property
    def is_complete(self) -> bool:
        return len(self._recovered) == self._K
