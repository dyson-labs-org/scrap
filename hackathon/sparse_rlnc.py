from __future__ import annotations

import functools
import math
import bisect

import numpy as np

from sisl_crypto import derive_coef_stream


# ── GF(2^8) arithmetic (AES polynomial x^8+x^4+x^3+x+1 = 0x11b) ────────────

_GF256_POLY = 0x11b


def _build_gf256_tables() -> tuple[list[int], list[int]]:
    """Build GF(2^8) log/antilog tables using generator 3 (= x+1, primitive root of AES poly)."""
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        # Multiply x by 3 = (x+1): x*x XOR x, reduced mod x^8+x^4+x^3+x+1
        x ^= (x << 1) ^ (0x1b if x & 0x80 else 0)
        x &= 0xff
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_GF256_EXP, _GF256_LOG = _build_gf256_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF256_EXP[_GF256_LOG[a] + _GF256_LOG[b]]


def _gf_inv(a: int) -> int:
    return _GF256_EXP[255 - _GF256_LOG[a]]


# 256×256 multiply table for vectorized byte-array operations.
_MUL_TABLE = np.zeros((256, 256), dtype=np.uint8)
for _a in range(256):
    for _b in range(256):
        _MUL_TABLE[_a, _b] = _gf_mul(_a, _b)

# Inverse table (element 0 is undefined; map 0 → 0 as sentinel).
_INV_TABLE = np.zeros(256, dtype=np.uint8)
for _a in range(1, 256):
    _INV_TABLE[_a] = _gf_inv(_a)


def _gf_mul_vec(scalar: int, vec: np.ndarray) -> np.ndarray:
    """Multiply each byte in vec by scalar ∈ GF(2^8)."""
    return _MUL_TABLE[scalar][vec]


@functools.lru_cache(maxsize=32)
def robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.1) -> tuple[float, ...]:
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
    return tuple(cdf)


def sample_degree(cdf: tuple[float, ...], uniform_val: float) -> int:
    idx = bisect.bisect_left(cdf, uniform_val)
    idx = min(idx, len(cdf) - 1)
    return idx + 1


def sample_coefficients(
    comb_id: int,
    K: int,
    session_prk: bytes,
    c: float = 0.1,
    delta: float = 0.1,
) -> tuple[list[int], list[int]]:
    """Sample (indices, GF(2^8) coefficients) for one coded symbol.

    Returns two parallel lists: fragment indices and their nonzero GF(2^8)
    coefficients (1..255).  The stream layout is:
        2 bytes  — uniform [0,1) for degree sampling
        5 bytes × max_attempts — 4 bytes index + 1 byte coefficient
    """
    max_attempts = 4 * K
    stream = derive_coef_stream(session_prk, comb_id, 2 + 5 * max_attempts)

    cdf = robust_soliton_cdf(K, c, delta)
    u = int.from_bytes(stream[0:2], 'big') / 65536.0
    d = sample_degree(cdf, u)

    indices: list[int] = []
    coeffs: list[int] = []
    pos = 2
    attempts = 0
    while len(indices) < d and attempts < max_attempts:
        raw = int.from_bytes(stream[pos:pos + 4], 'big')
        idx = raw % K
        coeff_raw = stream[pos + 4]
        coeff = (coeff_raw % 255) + 1  # map 0..254 → 1..255 (always nonzero)
        pos += 5
        attempts += 1
        if idx not in indices:
            indices.append(idx)
            coeffs.append(coeff)

    # Clamp to available indices: if degree > K or attempts exhausted, we may
    # have fewer than d indices.  This is expected for large degree / small K.
    # Callers must tolerate fewer-than-degree indices; assert non-empty only.
    assert len(indices) > 0 or d == 0, (
        f"coefficient under-sampling: got 0 indices for degree {d}, K={K}"
    )

    # Sort by index for deterministic ordering.
    pairs = sorted(zip(indices, coeffs))
    return ([p[0] for p in pairs], [p[1] for p in pairs])


def fragment_payload(payload: bytes, K: int) -> list[bytes]:
    frag_size = math.ceil(len(payload) / K)
    frag_size = math.ceil(frag_size / 16) * 16
    if frag_size == 0:
        frag_size = 16
    padded = payload + b'\x00' * (frag_size * K - len(payload))
    return [padded[i * frag_size:(i + 1) * frag_size] for i in range(K)]


class RLNCEncoder:
    def __init__(self, payload: bytes, K: int, session_prk: bytes):
        self._fragments = [
            np.frombuffer(f, dtype=np.uint8).copy()
            for f in fragment_payload(payload, K)
        ]
        self._K = K
        self._prk = session_prk

    def encode_symbol(self, comb_id: int) -> tuple[int, bytes, list[int]]:
        indices, coeffs = sample_coefficients(comb_id, self._K, self._prk)
        if not indices:
            frag_size = len(self._fragments[0])
            return (comb_id, bytes(frag_size), indices)
        # Stack active fragments into 2D array (degree × frag_size), scale each
        # row by its GF(2^8) coefficient via the lookup table, then XOR-reduce.
        active = np.stack([self._fragments[idx] for idx in indices])  # (d, frag_size)
        for i, c in enumerate(coeffs):
            active[i] = _MUL_TABLE[c][active[i]]
        result = np.bitwise_xor.reduce(active, axis=0)
        return (comb_id, bytes(result), indices)


class RLNCDecoder:
    def __init__(self, K: int, session_prk: bytes):
        self._K = K
        self._prk = session_prk
        # Each entry: (coeff_vec: np.ndarray[K, uint8], data: np.ndarray[frag_size, uint8])
        self._symbols: list[tuple[np.ndarray, np.ndarray]] = []
        self._recovered: dict[int, np.ndarray] = {}
        self._seen_ids: set[int] = set()

    _MAX_SEEN_IDS = 4096

    def _subtract_recovered(self, coeff_vec: np.ndarray, data: np.ndarray) -> None:
        """XOR out all already-recovered fragments from a symbol's data."""
        for i, frag in self._recovered.items():
            c = int(coeff_vec[i])
            if c != 0:
                data ^= _gf_mul_vec(c, frag)
                coeff_vec[i] = 0

    def _peel(self) -> None:
        changed = True
        while changed and len(self._recovered) < self._K:
            changed = False
            for coeff_vec, data in self._symbols:
                self._subtract_recovered(coeff_vec, data)
                nonzero = np.flatnonzero(coeff_vec)
                if len(nonzero) == 1:
                    idx = int(nonzero[0])
                    if idx not in self._recovered:
                        c = int(coeff_vec[idx])
                        frag = data.copy()
                        if c != 1:
                            frag = _gf_mul_vec(int(_INV_TABLE[c]), frag)
                        self._recovered[idx] = frag
                        coeff_vec[idx] = 0
                        changed = True

    def add_symbol(self, comb_id: int, encoded_bytes: bytes) -> bool:
        if comb_id in self._seen_ids:
            return self.is_complete
        if len(self._seen_ids) < self._MAX_SEEN_IDS:
            self._seen_ids.add(comb_id)
        indices, coeffs = sample_coefficients(comb_id, self._K, self._prk)
        coeff_vec = np.zeros(self._K, dtype=np.uint8)
        for idx, c in zip(indices, coeffs):
            coeff_vec[idx] = c
        data = np.frombuffer(encoded_bytes, dtype=np.uint8).copy()
        self._symbols.append((coeff_vec, data))
        self._peel()
        if not self.is_complete:
            self._gaussian_eliminate()
            self._peel()
        return self.is_complete

    def _gaussian_eliminate(self) -> None:
        unknown = [i for i in range(self._K) if i not in self._recovered]
        if not unknown:
            return
        idx_map = {frag: col for col, frag in enumerate(unknown)}
        n = len(unknown)

        # Build reduced coefficient matrix over unknowns only.
        rows_c: list[np.ndarray] = []
        rows_d: list[np.ndarray] = []
        for coeff_vec, data in self._symbols:
            # Apply known-fragment subtraction first.
            cv = coeff_vec.copy()
            d = data.copy()
            self._subtract_recovered(cv, d)
            cols = [idx_map[i] for i in unknown if cv[i] != 0]
            if cols:
                row = np.zeros(n, dtype=np.uint8)
                for i in unknown:
                    if cv[i] != 0:
                        row[idx_map[i]] = cv[i]
                rows_c.append(row)
                rows_d.append(d)

        if not rows_c:
            return

        frag_size = len(rows_d[0])
        pivot_row: dict[int, int] = {}
        row_idx = 0

        for col in range(n):
            # Find pivot.
            found = None
            for r in range(row_idx, len(rows_c)):
                if rows_c[r][col] != 0:
                    found = r
                    break
            if found is None:
                continue
            rows_c[row_idx], rows_c[found] = rows_c[found], rows_c[row_idx]
            rows_d[row_idx], rows_d[found] = rows_d[found], rows_d[row_idx]

            # Normalize pivot row so pivot coefficient = 1.
            piv_c = int(rows_c[row_idx][col])
            if piv_c != 1:
                inv_piv = int(_INV_TABLE[piv_c])
                rows_c[row_idx] = _MUL_TABLE[inv_piv][rows_c[row_idx]]
                rows_d[row_idx] = _gf_mul_vec(inv_piv, rows_d[row_idx])

            pivot_row[col] = row_idx

            # Eliminate this column from all other rows.
            for r in range(len(rows_c)):
                if r != row_idx and rows_c[r][col] != 0:
                    scale = int(rows_c[r][col])
                    rows_c[r] ^= _MUL_TABLE[scale][rows_c[row_idx]]
                    rows_d[r] ^= _gf_mul_vec(scale, rows_d[row_idx])

            row_idx += 1

        for col, pr in pivot_row.items():
            nonzero = np.flatnonzero(rows_c[pr])
            if len(nonzero) == 1 and nonzero[0] == col:
                self._recovered[unknown[col]] = rows_d[pr].copy()

    def decode(self) -> bytes | None:
        self._peel()
        if len(self._recovered) < self._K:
            self._gaussian_eliminate()
            self._peel()
        if len(self._recovered) < self._K:
            return None
        parts = [self._recovered[i].tobytes() for i in range(self._K)]
        return b''.join(parts)

    @property
    def is_complete(self) -> bool:
        return len(self._recovered) == self._K
