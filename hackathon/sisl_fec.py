"""SISL FEC — pure-numpy rate-1/2 K=9 soft Viterbi convolutional code.

Standalone FEC primitive for the SISL hackathon pipeline. No dependency
on sisl_framer, sisl_crypto, sisl_dsss_demo, or GNU Radio. Pure numpy.

The code is the NASA/Voyager standard rate-1/2 constraint-length-9
convolutional code:

    G1 = 0o753 = 0b111101011  (D^8 + D^7 + D^6 + D^5 + D^3 + D^1 + D^0)
    G2 = 0o561 = 0b101110001  (D^8 + D^6 + D^5 + D^4 + D^0)

Each input bit produces two output bits. The encoder is a shift register
of depth K = 9; at each time step an input bit is shifted in, the two
output bits are computed as the parity of (shift register AND G_k), and
the oldest bit is dropped.

**Zero-tail termination.** After the n_payload payload bits the encoder
is flushed with TAIL_BITS = 8 = K − 1 zero bits. This drives the
encoder state back to the all-zero state, so a Viterbi decoder can
perform optimal traceback from the known terminal state rather than
from the maximum-metric state (which would be suboptimal).

The tail bits ARE encoded through the rate-1/2 structure, so they
produce 2·TAIL_BITS = 16 coded output bits. The total coded length is

    coded_length(n_payload) = 2 * (n_payload + TAIL_BITS)
                            = 2*n_payload + 16

**LLR sign convention** (critical — must match
the coherent decode pipeline's c_soft return):

    Positive LLR ⇒ bit = 0 (BPSK +1 symbol favored)
    Negative LLR ⇒ bit = 1 (BPSK −1 symbol favored)

The Viterbi branch metric for a transition emitting coded bit c is
(1 − 2·c) · LLR, so a positive LLR gives a positive metric contribution
when c=0 (preferred) and negative when c=1 (penalized). The decoder
MAXIMIZES the total path metric.

**Public API**

    CODE_RATE_NUMERATOR         = 1
    CODE_RATE_DENOMINATOR       = 2
    CONSTRAINT_LENGTH           = 9
    TAIL_BITS                   = 8
    CODED_BITS_PER_PAYLOAD_BIT  = 2

    encode(bits)               -> ndarray[uint8]
    decode(llrs, n_payload)    -> ndarray[uint8]
    coded_length(n_payload)    -> int

**Performance target.** decode() is vectorized over the 256 trellis
states with numpy; only the outer time-step loop is Python. A
10000-payload-bit decode runs in under 500 ms on a standard CPU.

**References**

  Viterbi, "Error bounds for convolutional codes and an asymptotically
    optimum decoding algorithm", IEEE Trans. IT, 1967.
  Odenwalder, "Optimum decoding of convolutional codes", 1970 (source
    of the Voyager K=9 polynomial pair).
  Clark and Cain, "Error-Correction Coding for Digital Communications",
    Plenum, 1981, §6.
"""

from __future__ import annotations

import numpy as np


# ── Public constants ────────────────────────────────────────────────────────

CODE_RATE_NUMERATOR = 1
CODE_RATE_DENOMINATOR = 2
CONSTRAINT_LENGTH = 9
TAIL_BITS = 8
CODED_BITS_PER_PAYLOAD_BIT = 2

# NASA/Voyager K=9 rate-1/2 generator polynomials
_G1 = 0o753    # 0b111101011
_G2 = 0o561    # 0b101110001

# 2^(K-1) states; each state is the last K-1 = 8 input bits
_NUM_STATES = 1 << (CONSTRAINT_LENGTH - 1)     # 256


# ── Module-load precomputation of the trellis tables ────────────────────────

def _popcount_bit(x: int, mask: int) -> int:
    """Parity of (x & mask). Returns 0 or 1."""
    return bin(x & mask).count("1") & 1


def _build_trellis_tables():
    """Precompute per-new-state transition info for the Viterbi decoder.

    Given a new state nS, there are exactly two predecessors at the
    previous time step, both using the SAME input bit b = nS & 1:

        - s_a (with bit 8 of the 9-bit register = 0): s_a = nS >> 1
        - s_b (with bit 8 of the 9-bit register = 1): s_b = (nS >> 1) | 0x80

    The two transitions differ in the register's MSB, which (because
    both G1 and G2 have bit 8 set) flips both output bits. So for each
    new state we can look up a branch-metric index in {0,1,2,3} for
    each predecessor:

        idx = (output_bit_1 << 1) | output_bit_2

    where the LLR branch-metric table at each time step is:

        [+L1+L2, +L1-L2, -L1+L2, -L1-L2]     (indexed by idx)

    Returns:
        pred_a   : (256,) int32 — predecessor state with register bit 8 = 0
        pred_b   : (256,) int32 — predecessor state with register bit 8 = 1
        idx_a    : (256,) int32 — branch-metric index for the (pred_a, b)
                                  transition to new state nS
        idx_b    : (256,) int32 — same for (pred_b, b)
    """
    pred_a = np.arange(_NUM_STATES, dtype=np.int32) >> 1
    pred_b = pred_a | 0x80

    idx_a = np.empty(_NUM_STATES, dtype=np.int32)
    idx_b = np.empty(_NUM_STATES, dtype=np.int32)
    for ns in range(_NUM_STATES):
        # Predecessor a: register_a = nS  (9-bit, bit 8 = 0)
        reg_a = ns
        # Predecessor b: register_b = nS | 0x100 (bit 8 = 1)
        reg_b = ns | 0x100
        c1_a = _popcount_bit(reg_a, _G1)
        c2_a = _popcount_bit(reg_a, _G2)
        c1_b = _popcount_bit(reg_b, _G1)
        c2_b = _popcount_bit(reg_b, _G2)
        idx_a[ns] = (c1_a << 1) | c2_a
        idx_b[ns] = (c1_b << 1) | c2_b
    return pred_a, pred_b, idx_a, idx_b


_PRED_A, _PRED_B, _IDX_A, _IDX_B = _build_trellis_tables()


# ── Length helper ───────────────────────────────────────────────────────────

def coded_length(n_payload_bits: int) -> int:
    """Number of coded output bits for an `n_payload_bits`-bit payload.

    Includes the rate-1/2 encoding of the TAIL_BITS = 8 zero flush bits
    at the end, so:

        coded_length(n) = CODED_BITS_PER_PAYLOAD_BIT * (n + TAIL_BITS)
                        = 2 * (n + 8)
                        = 2*n + 16
    """
    if n_payload_bits < 0:
        raise ValueError(f"n_payload_bits must be ≥ 0, got {n_payload_bits}")
    return CODED_BITS_PER_PAYLOAD_BIT * (n_payload_bits + TAIL_BITS)


# ── Encoder ─────────────────────────────────────────────────────────────────

def encode(bits: np.ndarray) -> np.ndarray:
    """Rate-1/2 K=9 convolutional encode with zero-tail termination.

    Parameters
    ----------
    bits : ndarray of 0/1, any integer dtype
        Payload bits.

    Returns
    -------
    coded : ndarray[uint8]
        Coded output, length coded_length(len(bits)). Interleaved as
        [c1_0, c2_0, c1_1, c2_1, ...] where c1/c2 are the G1/G2 outputs.

    The encoder simulation uses an explicit per-step loop over input
    bits. Encoding is not on the hot path (Viterbi decode dominates),
    so we prefer clarity over the vectorization we apply on the
    decode side.
    """
    bits = np.asarray(bits).astype(np.uint8).ravel()
    if not np.all((bits == 0) | (bits == 1)):
        raise ValueError("encode: bits must be 0 or 1")

    # Append tail
    tail = np.zeros(TAIL_BITS, dtype=np.uint8)
    all_bits = np.concatenate([bits, tail])
    n_total = len(all_bits)
    out = np.empty(n_total * CODED_BITS_PER_PAYLOAD_BIT, dtype=np.uint8)

    state = 0         # 8-bit memory, LSB is most recently shifted-in
    for t in range(n_total):
        b = int(all_bits[t])
        # 9-bit register = (state << 1) | b, with bit 0 = b and
        # bit k = past input b_{t-k} (k=1..8).
        register = ((state << 1) | b) & 0x1FF
        out[2 * t] = _popcount_bit(register, _G1)
        out[2 * t + 1] = _popcount_bit(register, _G2)
        # New state drops the oldest bit (bit 8 of register).
        state = register & 0xFF

    return out


# ── Soft Viterbi decoder ────────────────────────────────────────────────────

_NEG_INF_INIT = -1.0e18    # large negative to mark impossible states at t=0


def decode(llrs: np.ndarray, n_payload_bits: int) -> np.ndarray:
    """Soft-decision Viterbi decode.

    Parameters
    ----------
    llrs : ndarray[float]
        Interleaved per-coded-bit LLRs, length
        `coded_length(n_payload_bits)`. LLR convention: positive means
        the coded bit is more likely 0 (BPSK +1 symbol), negative means
        more likely 1 (BPSK −1 symbol).

    n_payload_bits : int
        Number of payload bits to recover. The decoder assumes the
        trellis was zero-terminated, so it tracesback from state 0
        after n_payload_bits + TAIL_BITS time steps.

    Returns
    -------
    bits : ndarray[uint8]
        Exactly n_payload_bits recovered bits. The TAIL_BITS flush
        bits are used for termination and then dropped.

    Implementation notes
    --------------------
    The forward recursion is vectorized: at each time step, all 256
    state-metric updates are done with numpy array operations; there
    is no Python-level loop over states. The per-step branch-metric
    computation looks up 256 values from a 4-element table via
    fancy-indexing (`_IDX_A`, `_IDX_B` were precomputed at module load).

    The traceback is O(n_total) but trivial: at each stored survivor
    bit we either keep the MSB of the previous state or set it to 1,
    depending on which predecessor (a or b) won the add-compare-select
    at that step.
    """
    n_total = n_payload_bits + TAIL_BITS
    expected_len = CODED_BITS_PER_PAYLOAD_BIT * n_total
    llrs = np.asarray(llrs, dtype=np.float32)
    if llrs.ndim != 1:
        raise ValueError(f"decode: expected 1-D llrs, got shape {llrs.shape}")
    if len(llrs) != expected_len:
        raise ValueError(
            f"decode: expected {expected_len} LLRs for "
            f"n_payload_bits={n_payload_bits}, got {len(llrs)}"
        )
    if n_payload_bits == 0:
        return np.zeros(0, dtype=np.uint8)

    # Precompute per-step branch metric vectors: for each time step t,
    # branch_table[t, idx] gives the metric contribution of emitting
    # coded pair (c1, c2) with idx = (c1 << 1) | c2 and the LLR pair
    # (L1, L2) = (llrs[2t], llrs[2t+1]):
    #     idx 0: (0,0) → +L1 + L2
    #     idx 1: (0,1) → +L1 − L2
    #     idx 2: (1,0) → −L1 + L2
    #     idx 3: (1,1) → −L1 − L2
    L1 = llrs[0::2]
    L2 = llrs[1::2]
    branch_table = np.empty((n_total, 4), dtype=np.float32)
    branch_table[:, 0] = L1 + L2
    branch_table[:, 1] = L1 - L2
    branch_table[:, 2] = -L1 + L2
    branch_table[:, 3] = -L1 - L2

    # ── Forward recursion ───────────────────────────────────────────────
    # Initial metrics: only state 0 is valid (encoder starts at all-zero
    # memory). All other states have −∞ metric.
    M_curr = np.full(_NUM_STATES, _NEG_INF_INIT, dtype=np.float32)
    M_curr[0] = 0.0

    # survivors[t, s] == 1 if the b-predecessor won at time t for state s;
    # 0 if the a-predecessor won. (a = register bit 8 = 0, b = bit 8 = 1.)
    survivors = np.empty((n_total, _NUM_STATES), dtype=np.uint8)

    # Preallocate buffers to minimize per-step allocations.
    m_a = np.empty(_NUM_STATES, dtype=np.float32)
    m_b = np.empty(_NUM_STATES, dtype=np.float32)

    # Cache the permutation vectors locally so the hot loop doesn't
    # re-resolve module-level lookups.
    pred_a = _PRED_A
    pred_b = _PRED_B
    idx_a = _IDX_A
    idx_b = _IDX_B

    for t in range(n_total):
        bv = branch_table[t]                 # (4,)
        # m_a = M_curr[pred_a] + bv[idx_a]   — vectorized over all 256 states
        np.take(M_curr, pred_a, out=m_a)
        m_a += bv[idx_a]
        np.take(M_curr, pred_b, out=m_b)
        m_b += bv[idx_b]

        # Add-compare-select: keep the max per new state.
        # M_curr ← max(m_a, m_b); survivors[t] ← (m_b > m_a).
        np.maximum(m_a, m_b, out=M_curr)
        np.greater(m_b, m_a, out=survivors[t])

    # ── Traceback ───────────────────────────────────────────────────────
    # The final state is guaranteed to be 0 (zero-tail termination).
    # At each step we recover the input bit (which was the LSB of the
    # new_state at that step) and walk backward through the survivor
    # table.
    bits = np.empty(n_total, dtype=np.uint8)
    state = 0
    for t in range(n_total - 1, -1, -1):
        bits[t] = state & 1            # input bit that produced this state
        if survivors[t, state]:
            # b-predecessor won: previous state had bit 8 = 1
            state = (state >> 1) | 0x80
        else:
            state = state >> 1

    # Drop the TAIL_BITS flush bits at the end and return the payload.
    return bits[:n_payload_bits].copy()
