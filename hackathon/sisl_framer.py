"""SISL framer / deframer — pure-numpy DSP for the hackathon demo.

Implements the TX and RX chip-rate DSP for the SISL DSSS hailing channel,
independent of GNU Radio. The same functions are reused by the Phase 1
hidden-signal demo (`sisl_dsss_demo.py`) and the Phase 2 handshake flowgraph
(`sisl_hail_flow.py`) via thin GR wrappers.

Signal chain:

    TX: bytes → MSB-first bit unpack → BPSK symbols (±1)
              → repeat each symbol 1023 times → multiply by spreading code
              → int8 chip stream

    RX: chip stream → reshape into (n_symbols, 1023) → row-dot with local
        code → sign decision → MSB-first bit pack → bytes

Acquisition (sliding correlator, matched-filter frame detection) is NOT
implemented here. Per Hackathon.md §1.3 and §Risks, the Phase 1 demo
assumes chip-aligned start on both ends. For production or a real receiver,
add a sliding correlator on top of this module.

The spreading code is the public hailing code from SISL v3 §4.6.1, generated
by `sisl_dsss.hail_code_seed()` + `sisl_dsss.generate_dsss_code()`. Callers
may supply a session-derived code for the Phase 3 P2P channel.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# scipy is a HARD requirement — the matched-filter correlator must be
# FFT-based for real-time DSP. A numpy np.convolve fallback on multi-
# million-sample streams takes seconds per block and silently causes
# HackRF overflow in the live-RX path. Fail loudly at import.
try:
    from scipy.signal import fftconvolve as _fftconvolve
except ImportError as e:
    raise ImportError(
        "sisl_framer requires scipy for FFT-based DSP. "
        "Install with: pip install scipy  "
        "(or on Arch: sudo pacman -S python-scipy)"
    ) from e

import sisl_dsss as sd

CHIPS_PER_SYMBOL = 1023


# ── Spreading code helpers ──────────────────────────────────────────────────

_public_code_cache: Optional[np.ndarray] = None


def public_hail_code() -> np.ndarray:
    """Return the public SISL hailing spreading code as int8 ±1 array."""
    global _public_code_cache
    if _public_code_cache is None:
        seed = sd.hail_code_seed()
        code_list = sd.generate_dsss_code(seed, length=CHIPS_PER_SYMBOL)
        _public_code_cache = np.array(code_list, dtype=np.int8)
    return _public_code_cache


def code_from_seed(seed: bytes, length: int = CHIPS_PER_SYMBOL) -> np.ndarray:
    return np.array(sd.generate_dsss_code(seed, length=length), dtype=np.int8)


# ── Byte/bit packing ────────────────────────────────────────────────────────

def bytes_to_bits(data: bytes) -> np.ndarray:
    """MSB-first unpack. Returns uint8 array of 0/1."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def bits_to_bytes(bits: np.ndarray) -> bytes:
    """MSB-first pack. Bits must be a multiple of 8 in length."""
    if len(bits) % 8 != 0:
        raise ValueError(f"bit count {len(bits)} not a multiple of 8")
    return np.packbits(bits.astype(np.uint8)).tobytes()


# ── TX: bytes → chip stream ─────────────────────────────────────────────────

def tx_bytes_to_chips(data: bytes,
                      code: Optional[np.ndarray] = None) -> np.ndarray:
    """Spread `data` into an int8 bipolar chip stream.

    BPSK mapping: bit 0 → +1, bit 1 → -1. Each symbol is multiplied by the
    full spreading code, so one byte produces 8 * CHIPS_PER_SYMBOL chips.
    """
    if code is None:
        code = public_hail_code()
    if len(code) != CHIPS_PER_SYMBOL:
        raise ValueError(f"code length {len(code)} != {CHIPS_PER_SYMBOL}")

    bits = bytes_to_bits(data)
    symbols = (1 - 2 * bits.astype(np.int8))          # 0→+1, 1→-1
    # Broadcast multiply: (n_symbols, 1) * (1, chips) → (n_symbols, chips)
    chips = (symbols[:, None] * code[None, :]).reshape(-1)
    return chips.astype(np.int8)


# ── RX: chip stream → bytes ─────────────────────────────────────────────────

def rx_chips_to_bytes(chips: np.ndarray, n_bytes: int,
                      code: Optional[np.ndarray] = None) -> bytes:
    """Despread a chip-aligned stream into bytes.

    `chips` must contain at least `n_bytes * 8 * CHIPS_PER_SYMBOL` samples
    starting at chip 0 of the first symbol. Accepts float or int input.
    """
    if code is None:
        code = public_hail_code()

    n_bits = n_bytes * 8
    needed = n_bits * CHIPS_PER_SYMBOL
    if len(chips) < needed:
        raise ValueError(f"need {needed} chips, got {len(chips)}")

    # Reshape, correlate each row against the local code
    mat = np.asarray(chips[:needed], dtype=np.float32).reshape(
        n_bits, CHIPS_PER_SYMBOL
    )
    corr = mat @ code.astype(np.float32)

    # BPSK decision: correlation > 0 → bit 0, < 0 → bit 1
    bits = (corr < 0).astype(np.uint8)
    return bits_to_bytes(bits)


def rx_chip_snr_db(chips: np.ndarray, n_bytes: int,
                   code: Optional[np.ndarray] = None) -> float:
    """Estimate post-despread SNR in dB from correlator output magnitude.

    Useful for sanity-checking the loopback with and without noise.
    """
    if code is None:
        code = public_hail_code()
    n_bits = n_bytes * 8
    needed = n_bits * CHIPS_PER_SYMBOL
    mat = np.asarray(chips[:needed], dtype=np.float32).reshape(
        n_bits, CHIPS_PER_SYMBOL
    )
    corr = mat @ code.astype(np.float32)
    # signal = magnitude of correlator output (assuming BPSK ±)
    # noise  = deviation from ±CHIPS_PER_SYMBOL
    signal = np.mean(np.abs(corr))
    noise = np.std(np.abs(corr) - signal) + 1e-12
    return float(20 * np.log10(signal / noise))


# ── Sliding-correlator acquisition (Phase 2/3, optional) ────────────────────

def matched_filter_magnitude(chips: np.ndarray,
                              code: Optional[np.ndarray] = None) -> np.ndarray:
    """Return |correlation| of `chips` against one period of the spreading code.

    Chip-rate matched filter. `chips` is expected to already be decimated
    to one sample per chip, chip-aligned at the start. For sample-rate
    input (unknown sub-chip phase), use `matched_filter_magnitude_sample_rate`
    instead — it is phase-agnostic and runs in a single pass.

    Output length = len(chips) - len(code) + 1.
    """
    if code is None:
        code = public_hail_code()
    chips_f = np.asarray(chips, dtype=np.float32)
    code_f = code.astype(np.float32)
    if len(chips_f) < len(code_f):
        return np.zeros(0, dtype=np.float32)
    kernel = code_f[::-1]
    corr = _fftconvolve(chips_f, kernel, mode="valid")
    return np.abs(corr.astype(np.float32))


def matched_filter_magnitude_sample_rate(
    samples: np.ndarray,
    samps_per_chip: int,
    code: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Sample-rate matched filter. Phase-agnostic acquisition in one pass.

    Correlates `samples` (complex64 baseband) against the spreading code
    upsampled by `samps_per_chip` via zero-order hold. A peak at output
    index k means the first chip of a symbol starts at sample k. No
    sub-chip phase search is required — the kernel's ZOH upsampling
    absorbs any integer-sample phase offset of the TX chip grid relative
    to the RX sample grid.

    Only the real (I) component of `samples` is used — the demo TX is
    BPSK with zero Q. A full-complex version is a trivial extension.

    Output length = len(samples) - len(code)*samps_per_chip + 1.
    """
    if code is None:
        code = public_hail_code()
    if samps_per_chip < 1:
        raise ValueError("samps_per_chip must be >= 1")
    code_upsampled = np.repeat(
        code.astype(np.float32), samps_per_chip
    ).astype(np.float32)
    i = np.asarray(samples, dtype=np.complex64).real.astype(np.float32)
    if len(i) < len(code_upsampled):
        return np.zeros(0, dtype=np.float32)
    kernel = code_upsampled[::-1]
    corr = _fftconvolve(i, kernel, mode="valid")
    return np.abs(corr.astype(np.float32))


def find_frame_start(chips: np.ndarray, code: Optional[np.ndarray] = None,
                     max_search: Optional[int] = None,
                     peak_threshold: float = 4.0) -> Optional[int]:
    """Locate the chip offset of the first symbol via matched-filter peak.

    Returns the offset into `chips` at which the first symbol begins, or
    None if no peak is confidently above noise within `max_search` chips.

    `max_search=None` searches the entire input. `peak_threshold` is the
    ratio of peak magnitude to median magnitude required to declare a lock;
    4.0 is conservative and works well under AWGN with processing gain.

    Note: the matched filter also peaks at every symbol boundary (every
    1023 chips) because the code period matches the symbol period. We return
    the FIRST above-threshold peak, which corresponds to the first symbol
    edge in the stream.
    """
    if code is None:
        code = public_hail_code()
    mag = matched_filter_magnitude(chips, code)
    if len(mag) == 0:
        return None
    if max_search is not None:
        mag = mag[:max_search]
        if len(mag) == 0:
            return None

    peak_val = float(mag.max())
    median = float(np.median(mag))
    if median == 0.0 or peak_val < peak_threshold * median:
        return None

    # Note: the matched filter peaks at every symbol boundary (every 1023
    # chips) with magnitude ≈ CHIPS_PER_SYMBOL; FFT-based convolution
    # introduces ULP-level rounding across these near-identical peaks, so
    # a strict np.argmax may return a LATER peak than the first. Return
    # the first index that is within 10% of the global maximum — robust
    # to float32 rounding while still unambiguously above noise.
    near_peak = mag >= 0.9 * peak_val
    return int(np.argmax(near_peak))


# ── GNU Radio wrappers (optional; only if gnuradio is importable) ───────────

try:
    from gnuradio import gr
    _HAVE_GR = True
except ImportError:
    gr = None                                          # type: ignore
    _HAVE_GR = False


if _HAVE_GR:
    class SISLFramerBlock(gr.basic_block):                                # type: ignore[misc]
        """GR basic_block wrapping `tx_bytes_to_chips`.

        Input: byte stream (uint8, one byte per item).
        Output: chip stream (int8, ±1, CHIPS_PER_SYMBOL * 8 chips per byte).
        """

        def __init__(self, code: Optional[np.ndarray] = None):
            gr.basic_block.__init__(
                self,
                name="sisl_framer",
                in_sig=[np.uint8],
                out_sig=[np.int8],
            )
            self._code = code if code is not None else public_hail_code()

        def general_work(self, input_items, output_items):
            in0 = input_items[0]
            out0 = output_items[0]
            chips_per_byte = 8 * CHIPS_PER_SYMBOL
            n_bytes_in = len(in0)
            n_bytes_out = len(out0) // chips_per_byte
            n = min(n_bytes_in, n_bytes_out)
            if n == 0:
                return 0
            chips = tx_bytes_to_chips(bytes(in0[:n].tolist()), self._code)
            out0[:n * chips_per_byte] = chips
            self.consume(0, n)
            return n * chips_per_byte

    class SISLDeframerBlock(gr.basic_block):                              # type: ignore[misc]
        """GR basic_block wrapping `rx_chips_to_bytes` (chip-aligned).

        Input: float32 chip stream (correlator input).
        Output: byte stream (uint8).

        Assumes chip-0 alignment at startup. A real receiver must prepend a
        sliding-correlator acquisition stage (see `find_frame_start`).
        """

        def __init__(self, code: Optional[np.ndarray] = None):
            gr.basic_block.__init__(
                self,
                name="sisl_deframer",
                in_sig=[np.float32],
                out_sig=[np.uint8],
            )
            self._code = code if code is not None else public_hail_code()

        def general_work(self, input_items, output_items):
            in0 = input_items[0]
            out0 = output_items[0]
            chips_per_byte = 8 * CHIPS_PER_SYMBOL
            n_bytes_possible = min(len(in0) // chips_per_byte, len(out0))
            if n_bytes_possible == 0:
                return 0
            chips = in0[:n_bytes_possible * chips_per_byte]
            data = rx_chips_to_bytes(chips, n_bytes_possible, self._code)
            out0[:n_bytes_possible] = np.frombuffer(data, dtype=np.uint8)
            self.consume(0, n_bytes_possible * chips_per_byte)
            return n_bytes_possible
