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


# 256×256 multiply table — built via log/antilog outer product (vectorized).
_GF256_EXP_NP = np.array(_GF256_EXP, dtype=np.uint16)
_GF256_LOG_NP = np.array(_GF256_LOG, dtype=np.uint16)

_a_idx = np.arange(256, dtype=np.uint16)[:, None]
_b_idx = np.arange(256, dtype=np.uint16)[None, :]
_log_sum = (_GF256_LOG_NP[_a_idx] + _GF256_LOG_NP[_b_idx]) % 255
_MUL_TABLE = _GF256_EXP_NP[_log_sum].astype(np.uint8)
_MUL_TABLE[0, :] = 0
_MUL_TABLE[:, 0] = 0
del _a_idx, _b_idx, _log_sum

# Inverse table (element 0 is undefined; map 0 → 0 as sentinel).
_INV_TABLE = np.zeros(256, dtype=np.uint8)
_nz = np.arange(1, 256, dtype=np.uint16)
_INV_TABLE[1:] = _GF256_EXP_NP[(255 - _GF256_LOG_NP[_nz]) % 255]
del _nz


def _gf_mul_vec(scalar: int, vec: np.ndarray) -> np.ndarray:
    """Multiply each byte in vec by scalar ∈ GF(2^8)."""
    return _MUL_TABLE[scalar][vec]


@functools.lru_cache(maxsize=32)
def robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.1) -> tuple[float, ...]:
    if K <= 0:
        raise ValueError(f"K must be > 0, got {K}")
    if c <= 0.0:
        raise ValueError(f"c must be > 0, got {c}")
    if not (0.0 < delta < 1.0):
        raise ValueError(f"delta must be in (0, 1), got {delta}")

    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))

    R = c * math.log(K / delta) * math.sqrt(K)
    threshold = int(K / R)
    threshold = max(1, min(K, threshold))

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
    seen_indices: set[int] = set()
    pos = 2
    attempts = 0
    while len(indices) < d and attempts < max_attempts:
        raw = int.from_bytes(stream[pos:pos + 4], 'big')
        idx = raw % K
        coeff_raw = stream[pos + 4]
        coeff = (coeff_raw % 255) + 1  # map 0..254 → 1..255 (always nonzero)
        pos += 5
        attempts += 1
        if idx not in seen_indices:
            seen_indices.add(idx)
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
    _DEFAULT_MAX_SYMBOL_FACTOR = 4

    def __init__(
        self,
        K: int,
        session_prk: bytes,
        *,
        max_symbols: int | None = None,
    ):
        self._K = K
        self._prk = session_prk
        self._max_symbols = (
            self._DEFAULT_MAX_SYMBOL_FACTOR * K
            if max_symbols is None
            else int(max_symbols)
        )
        if self._max_symbols <= 0:
            raise ValueError(f"max_symbols must be > 0, got {self._max_symbols}")
        self._seen_ids: set[int] = set()
        self._received_symbols = 0
        self._status = "in_progress"
        self._failure_reason: str | None = None
        # Incremental RREF state — allocated lazily on first symbol.
        self._frag_size: int = 0
        # pivot_coeff[i]: K-wide coefficient row for pivot i (normalized: leading entry = 1)
        self._pivot_coeff: np.ndarray | None = None   # shape (K, K)
        # pivot_data[i]: frag_size-wide data row for pivot i
        self._pivot_data: np.ndarray | None = None    # shape (K, frag_size)
        self._pivot_cols: list[int] = []              # column index each pivot row reduced on
        self._n_pivots: int = 0

    def _init_arrays(self, frag_size: int) -> None:
        self._frag_size = frag_size
        self._pivot_coeff = np.zeros((self._K, self._K), dtype=np.uint8)
        self._pivot_data = np.zeros((self._K, frag_size), dtype=np.uint8)
        self._pivot_cols = [0] * self._K

    def _mark_budget_exhausted(self) -> None:
        if self.is_complete:
            return
        self._status = "budget_exhausted"
        self._failure_reason = (
            f"decoder symbol budget exhausted: received={self._received_symbols}, "
            f"max={self._max_symbols}, rank={self._n_pivots}/{self._K}"
        )

    def _add_to_rref(self, coeff_vec: np.ndarray, data: np.ndarray) -> bool:
        """Add one symbol to the running RREF. Returns True if rank increases."""
        n = self._n_pivots
        row_c = coeff_vec.astype(np.uint16)
        row_d = data.copy()

        if n > 0:
            pc = self._pivot_cols[:n]                        # (n,) column indices
            pm_c = self._pivot_coeff[:n]                     # (n, K)
            pm_d = self._pivot_data[:n]                      # (n, frag_size)
            # Coefficient of our row at each pivot column.
            leading = row_c[pc].astype(np.uint8)             # (n,)
            nz = np.flatnonzero(leading)
            if len(nz):
                coeffs = leading[nz]                         # (len(nz),)
                # XOR scaled pivot coeff rows into row_c
                # _MUL_TABLE[coeffs[j], pm_c[nz[j], :]] for each j
                scaled_c = _MUL_TABLE[coeffs[:, None], pm_c[nz]]  # (len(nz), K)
                row_c ^= np.bitwise_xor.reduce(scaled_c.astype(np.uint16), axis=0)
                # XOR scaled pivot data rows into row_d
                scaled_d = _MUL_TABLE[coeffs[:, None], pm_d[nz]]  # (len(nz), frag_size)
                row_d ^= np.bitwise_xor.reduce(scaled_d, axis=0)

        # Find leftmost nonzero in coeff part after elimination.
        nz_cols = np.flatnonzero(row_c.astype(np.uint8))
        if len(nz_cols) == 0:
            return False   # linearly dependent

        pivot_col = int(nz_cols[0])
        inv_lead = int(_INV_TABLE[int(row_c[pivot_col])])

        # Normalize: multiply row by inverse of leading coefficient.
        row_c_u8 = _MUL_TABLE[inv_lead, row_c.astype(np.uint8)]   # (K,)
        row_d = _MUL_TABLE[inv_lead, row_d]                        # (frag_size,)

        # Back-substitute: eliminate pivot_col from all existing pivot rows.
        if n > 0:
            existing = self._pivot_coeff[:n, pivot_col]            # (n,)
            nz = np.flatnonzero(existing)
            if len(nz):
                coeffs = existing[nz]                              # (len(nz),)
                self._pivot_coeff[nz] ^= _MUL_TABLE[coeffs[:, None], row_c_u8[None, :]]
                self._pivot_data[nz] ^= _MUL_TABLE[coeffs[:, None], row_d[None, :]]

        self._pivot_coeff[n] = row_c_u8
        self._pivot_data[n] = row_d
        self._pivot_cols[n] = pivot_col
        self._n_pivots += 1
        return True

    def add_symbol(self, comb_id: int, encoded_bytes: bytes) -> bool:
        if self.is_complete:
            self._status = "complete"
            return True
        if self._status == "budget_exhausted":
            return False

        self._received_symbols += 1
        if comb_id in self._seen_ids:
            if self._received_symbols >= self._max_symbols:
                self._mark_budget_exhausted()
            return self.is_complete
        self._seen_ids.add(comb_id)

        indices, coeffs = sample_coefficients(comb_id, self._K, self._prk)
        coeff_vec = np.zeros(self._K, dtype=np.uint8)
        for idx, c in zip(indices, coeffs):
            coeff_vec[idx] = c
        data = np.frombuffer(encoded_bytes, dtype=np.uint8).copy()

        if self._pivot_coeff is None:
            self._init_arrays(len(data))

        self._add_to_rref(coeff_vec, data)
        if self.is_complete:
            self._status = "complete"
            self._failure_reason = None
        elif self._received_symbols >= self._max_symbols:
            self._mark_budget_exhausted()
        return self.is_complete

    def decode(self) -> bytes | None:
        if not self.is_complete:
            return None
        # pivot_data rows are already in RREF; pivot_cols[i] is the fragment index
        # for pivot row i.  Assemble in fragment order.
        fragments: list[bytes | None] = [None] * self._K
        for i in range(self._n_pivots):
            fragments[self._pivot_cols[i]] = self._pivot_data[i].tobytes()
        if any(f is None for f in fragments):
            return None
        return b''.join(fragments)  # type: ignore[arg-type]

    @property
    def is_complete(self) -> bool:
        return self._n_pivots == self._K

    @property
    def is_budget_exhausted(self) -> bool:
        return self._status == "budget_exhausted"

    @property
    def status(self) -> str:
        return self._status

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    @property
    def max_symbols(self) -> int:
        return self._max_symbols

    @property
    def received_symbols(self) -> int:
        return self._received_symbols

    @property
    def unique_symbol_ids(self) -> int:
        return len(self._seen_ids)
