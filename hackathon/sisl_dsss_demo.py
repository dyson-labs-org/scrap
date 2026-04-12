"""Phase 1: SISL DSSS hidden-signal demo.

GNU Radio top-block that drives two HackRF units through the SISL public
hailing code and shows that the signal is below the noise floor to a naive
observer but recovers cleanly to a receiver with the correct spreading code.

Per Hackathon.md §1 and §Signal Parameters:

    Center frequency: 2437 MHz  (WiFi channel 6 — "hide in WiFi noise")
    Chip rate:        1 Mcps
    Sample rate:      8 Msps   (HackRF minimum 1 Msps, rates are integer)
    Samples/chip:     8        → clean zero-order-hold upsample
    TX power:         minimum HackRF setting
    Spreading code:   SISL public hail code (sisl_dsss.hail_code_seed())

CRITICAL per Hackathon.md §Link Budget: a single 30 dB attenuator is not
sufficient to put the signal below the HackRF noise floor. Use 60 dB+
total attenuation (two 30 dB in series) between TX and RX, and set HackRF
TX gain to minimum. Verify with a CW tone first that the attenuation chain
actually buries the signal in the waterfall before adding the DSSS layer.

Status: **UNTESTED** — written without hardware in the loop. Validate
flowgraph structure at the bench before running live. The pure-numpy DSP
layer in sisl_framer.py is fully tested (see test_sisl_framer.py) and is
the ground truth for spread/despread semantics. This file is the GR glue.

Both tx and rx emit/capture a SISL v3 hail frame built by build_demo_hail
(using the deterministic demo_responder_key target). The offline mode
decodes the captured file via sisl_crypto.decode_hail.

Usage:
    python hackathon/sisl_dsss_demo.py --mode tx       # tx a demo hail forever
    python hackathon/sisl_dsss_demo.py --mode rx       # capture samples to /tmp/sisl_rx.cfile
    python hackathon/sisl_dsss_demo.py --mode offline  # decode and decrypt a capture

Requires:
    gnuradio (tested on 3.10+)
    gr-soapy or gr-osmosdr for HackRF access
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

from cryptography.hazmat.primitives.asymmetric import ec

import sisl_crypto as sc
import sisl_fec

try:
    from gnuradio import analog, blocks, gr
    try:
        from gnuradio import soapy
        _HAVE_SOAPY = True
    except ImportError:
        _HAVE_SOAPY = False
    _HAVE_GR = True
except ImportError:
    _HAVE_GR = False
    _HAVE_SOAPY = False

import sisl_framer as sf


# ── Demo parameters ─────────────────────────────────────────────────────────

CENTER_FREQ_HZ = 2_437_000_000          # default: WiFi ch 6 (may be noisy!)
CHIP_RATE_HZ = 1_000_000                # 1 Mcps — fixed across devices
SAMP_RATE_HZ = 8_000_000                # 8 Msps (HackRF default)
SAMPS_PER_CHIP = SAMP_RATE_HZ // CHIP_RATE_HZ    # 8 — integer
HACKRF_TX_VGA_DB = 0                    # TX IF gain, 0..47 dB. Default = min.
HACKRF_TX_AMP_ON = False                # TX RF PA (14 dB). Off by default.
HACKRF_RX_VGA_DB = 20                   # conservative
HACKRF_RX_LNA_DB = 16                   # conservative


# ── Per-device RX configuration ────────────────────────────────────────────
#
# The HackRF and RTL-SDR families have very different sample rate grids
# and frequency ranges. The TX path is HackRF-only (RTL-SDR is RX-only
# hardware); the RX path can use either.

class DeviceInfo:
    def __init__(self, name, driver, samp_hz, samps_per_chip, freq_min_hz,
                 freq_max_hz, notes):
        self.name = name
        self.driver = driver
        self.samp_hz = samp_hz
        self.samps_per_chip = samps_per_chip
        self.freq_min_hz = freq_min_hz
        self.freq_max_hz = freq_max_hz
        self.notes = notes


DEVICES = {
    "hackrf": DeviceInfo(
        name="HackRF One",
        driver="driver=hackrf",
        samp_hz=8_000_000,
        samps_per_chip=8,
        freq_min_hz=1_000_000,           # 1 MHz
        freq_max_hz=6_000_000_000,       # 6 GHz
        notes="TX + RX, 1 MHz – 6 GHz, 8-bit ADC, 3 gain stages",
    ),
    "rtlsdr": DeviceInfo(
        name="NESDR / RTL-SDR",
        driver="driver=rtlsdr",
        samp_hz=2_000_000,               # 2 Msps → 2 samps/chip (Nyquist)
        samps_per_chip=2,
        freq_min_hz=24_000_000,          # 24 MHz (R820T2)
        freq_max_hz=1_766_000_000,       # ~1766 MHz (R820T2 ceiling)
        notes="RX only, 24–1766 MHz, 8-bit ADC, single tuner gain",
    ),
}


# Suggest plugin install commands when a SoapySDR driver is missing
_PLUGIN_INSTALL_HINTS = {
    "hackrf": (
        "  Arch:   sudo pacman -S soapyhackrf\n"
        "  Debian: sudo apt install soapysdr-module-hackrf\n"
        "  From source: https://github.com/pothosware/SoapyHackRF"
    ),
    "rtlsdr": (
        "  Arch:   sudo pacman -S soapyrtlsdr\n"
        "  Debian: sudo apt install soapysdr-module-rtlsdr\n"
        "  From source: https://github.com/pothosware/SoapyRTLSDR"
    ),
}


def _format_device_open_error(soapy_module, info: "DeviceInfo",
                               err: Exception) -> str:
    """Produce a human-readable explanation for SoapySDR device-open
    failures that tells the user exactly which plugin is missing.
    """
    try:
        enumerated = soapy_module.Device.enumerate()
    except Exception:
        enumerated = []

    # SoapySDR.Device.enumerate() returns a list of dicts (or Kwargs objects
    # that behave dict-like). Extract the driver field for human display.
    found_drivers = []
    for d in enumerated:
        try:
            drv = d.get("driver", "?") if hasattr(d, "get") else "?"
        except Exception:
            drv = "?"
        found_drivers.append(str(drv))

    lines = [
        f"failed to open {info.name} with '{info.driver}': {err}",
        "",
        "SoapySDR enumerated the following devices:",
    ]
    if enumerated:
        for i, d in enumerate(enumerated):
            try:
                lines.append(f"  [{i}] {dict(d)}")
            except Exception:
                lines.append(f"  [{i}] {d}")
    else:
        lines.append("  (none — no SoapySDR plugins found matching any device)")

    driver_key = info.driver.replace("driver=", "")
    if driver_key not in found_drivers:
        lines.append("")
        lines.append(
            f"The '{driver_key}' driver is NOT among SoapySDR's loaded plugins."
        )
        lines.append(
            f"Install the Soapy{driver_key.upper()} plugin and retry:"
        )
        hint = _PLUGIN_INSTALL_HINTS.get(driver_key,
                                         f"  (no install hint for {driver_key})")
        lines.append(hint)
        lines.append("")
        lines.append(
            "After installing, verify with:  SoapySDRUtil --find"
        )

    return "\n".join(lines)


# ── Suggested quieter frequencies ──────────────────────────────────────────
#
# 2.4 GHz ISM is saturated at hackathons and any venue with WiFi/BT. These
# are alternatives the HackRF can reach (1 MHz – 6 GHz tuning range). All
# values are in MHz. Regulatory note: ISM bands are generally permitted
# for low-power research; licensed bands (amateur, commercial) are not.
# Check your local regulator.
SUGGESTED_FREQS_MHZ = [
    # (MHz,  band,            notes)
    (2484,   "2.4 GHz ISM",   "Japan WiFi ch 14 — empty in US/EU"),
    (2422,   "2.4 GHz ISM",   "between WiFi ch 2/3, narrow quiet slot"),
    (2467,   "2.4 GHz ISM",   "between WiFi ch 11/13"),
    (5760,   "5.8 GHz ISM",   "below WiFi 802.11a ch 153 — usually clean"),
    (5820,   "5.8 GHz ISM",   "between WiFi ch 161/165"),
    (5875,   "5.8 GHz ISM",   "top of 5 GHz ISM, usually empty"),
    (915,    "US 915 ISM",    "LoRa/Z-Wave band (US only)"),
    (868,    "EU 868 ISM",    "LoRa/Sigfox (EU only)"),
    (433,    "433 ISM",       "garage-remote band (worldwide)"),
]


def _format_freq_suggestions() -> str:
    lines = [
        "",
        "Suggested quieter frequencies (--freq in MHz):",
        "",
        "  MHz    band           notes",
        "  -----  -------------  ----------------------------------------",
    ]
    for mhz, band, note in SUGGESTED_FREQS_MHZ:
        lines.append(f"  {mhz:<5}  {band:<13}  {note}")
    lines.append("")
    lines.append("  Default is 2437 MHz (WiFi ch 6 — often noisy at hackathons).")
    lines.append("  Higher frequencies (5.8 GHz) have ~8 dB more path loss than")
    lines.append("  2.4 GHz; lower frequencies (< 1 GHz) need larger antennas.")
    lines.append("  All listed values are legal ISM bands for low-power research")
    lines.append("  in the regions noted. Check your local regulator.")
    return "\n".join(lines)


# ── Demo keys (reproducible, NOT SECRET) ────────────────────────────────────
#
# The Phase 1/2 demo uses deterministic secp256k1 keys derived from fixed
# labels so TX and RX sides share identity without a ground-station uplink.
# DO NOT use these for anything other than the hackathon demo: the seeds
# are literally this source file.

_DEMO_SEED_PREFIX = b"SISL-PHASE1-DEMO-KEY-v1:"

# secp256k1 group order — SEC 2 / BIP-340. Scalars for a valid private key
# must lie in [1, n-1].
_SECP256K1_N = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFE_BAAEDCE6_AF48A03B_BFD25E8C_D0364141
)


def _demo_key_from_label(label: str) -> ec.EllipticCurvePrivateKey:
    seed = hashlib.sha256(_DEMO_SEED_PREFIX + label.encode()).digest()
    # Reduce into [1, n-1]. The bias from modular reduction on a uniformly
    # random 256-bit integer is ~2^-128 and cryptographically negligible;
    # we add 1 to exclude the zero scalar.
    scalar = (int.from_bytes(seed, "big") % (_SECP256K1_N - 1)) + 1
    return ec.derive_private_key(scalar, ec.SECP256K1())


def demo_caller_key() -> ec.EllipticCurvePrivateKey:
    """Reproducible 'satellite A' static key."""
    return _demo_key_from_label("caller")


def demo_responder_key() -> ec.EllipticCurvePrivateKey:
    """Reproducible 'satellite B' static key — the hail target."""
    return _demo_key_from_label("responder")


def demo_other_key() -> ec.EllipticCurvePrivateKey:
    """Reproducible 'satellite X' static key — NOT the hail target.

    Used to demonstrate the trial-decryption identity oracle: decoding
    a demo hail under this key MUST fail (Poly1305 tag mismatch).
    """
    return _demo_key_from_label("other")


# ── Demo hail frame builder ─────────────────────────────────────────────────

def build_demo_hail() -> bytes:
    """Produce a real SISL v3 hail frame targeting the demo responder.

    Returns the 133-byte on-wire frame. The encrypted body carries
    caller_static_pub (the demo caller's compressed pubkey) so the
    responder can compute DH2 for full X3DH at ACK time. body_nonce is
    fresh per call (replay protection); caller ephemeral is fresh per
    call and consumed by encode_hail.
    """
    caller_static = demo_caller_key()
    responder_static = demo_responder_key()
    caller_eph = sc.Ephemeral()
    body = sc.HailBody(
        caller_static_pub=sc.pubkey_to_compressed(caller_static.public_key()),
        center_freq_offset=100,   # +100 MHz reference offset
        bandwidth_code=0x03,      # 5 MHz
        mode=0x01,                # DSSS
        chip_rate_code=0x32,      # 5 Mcps
        body_nonce=os.urandom(8),
        flags=0x03,               # DSSS + FHSS capable
    )
    return sc.encode_hail(caller_eph, responder_static.public_key(), body)


# ── Pure-numpy helpers (no GR) ──────────────────────────────────────────────

def build_tx_chips(message: bytes) -> np.ndarray:
    """Produce an int8 ±1 chip stream for `message` using the public code."""
    return sf.tx_bytes_to_chips(message)


def build_demo_hail_fec_chips() -> tuple[np.ndarray, bytes]:
    """Produce a FEC-encoded chip stream for one fresh demo hail.

    Returns (chips, frame_bytes_for_diagnostics) where chips is the
    int8 ±1 stream from tx_bits_to_chips applied to the 2096-bit FEC
    channel array, and frame_bytes is the canonical 133-byte uncoded
    hail (for printing/debugging — NOT what's on the wire).

    This is the FEC TX path: encode_hail_fec produces 48 uncoded
    header bits + 2048 FEC body bits (total 2096), each becoming
    CHIPS_PER_SYMBOL=1023 chips on the air.
    """
    caller_static = demo_caller_key()
    responder_static = demo_responder_key()
    caller_eph = sc.Ephemeral()
    body = sc.HailBody(
        caller_static_pub=sc.pubkey_to_compressed(caller_static.public_key()),
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=os.urandom(8),
        flags=0x03,
    )
    # Capture the canonical frame for printing/debugging by re-encoding
    # under a separate ephemeral. The on-wire bits use the consumed eph.
    diag_eph = sc.Ephemeral()
    diag_frame = sc.encode_hail(diag_eph, responder_static.public_key(), body)
    bits = sc.encode_hail_fec(caller_eph, responder_static.public_key(), body)
    chips = sf.tx_bits_to_chips(bits)
    return chips, diag_frame


def upsample_chips_to_samples(chips: np.ndarray,
                              samps_per_chip: float = SAMPS_PER_CHIP
                              ) -> np.ndarray:
    """Zero-order-hold upsample chips to complex baseband samples.

    Simple demo path: each chip becomes `round(samps_per_chip)` samples of
    the same ±1 value, emitted as complex64 with zero imaginary part. This
    is coarse; a production TX would pulse-shape (e.g., root-raised-cosine).
    """
    n = int(round(samps_per_chip))
    rep = np.repeat(chips.astype(np.float32), n)
    return rep.astype(np.complex64)


# ── GR top-block ────────────────────────────────────────────────────────────

if _HAVE_GR:
    class DSSSHiddenSignalTop(gr.top_block):                              # type: ignore[misc]
        """Phase 1 top-block.

        TX mode: vector source of pre-spread samples → HackRF sink.
        RX mode: HackRF source → raw file sink (post-processed offline).

        Live despread in GR would use SISLDeframerBlock from sisl_framer,
        but chip-rate alignment to a 2.4 Msps stream requires interpolation
        handling that's brittle without a bench — keep the RX path simple
        and do the demodulation offline.
        """

        def __init__(self, mode: str,
                     tx_vga_db: int = HACKRF_TX_VGA_DB,
                     tx_amp_on: bool = HACKRF_TX_AMP_ON,
                     center_hz: float = CENTER_FREQ_HZ,
                     hackrf_device: str = "hackrf=0",
                     preamble_only: bool = False):
            gr.top_block.__init__(self, "SISL DSSS Hidden Signal Demo")

            self.mode = mode
            self.tx_vga_db = tx_vga_db
            self.tx_amp_on = tx_amp_on
            self.center_hz = center_hz
            self.preamble_only = preamble_only

            if mode == "tx":
                if preamble_only:
                    # Diagnostic mode: transmit only the 4-byte ASM on
                    # repeat. No body, no crypto, no per-call variation.
                    frame = _ASM_BYTES
                    self.hail_frame = frame
                    chips = build_tx_chips(frame)
                else:
                    # FEC TX path: encode_hail_fec produces a 2096-bit
                    # channel array (48 uncoded header + 2048 FEC body).
                    chips, frame = build_demo_hail_fec_chips()
                    self.hail_frame = frame
                # Repeat the hail indefinitely so the RX can lock at any time
                samples = upsample_chips_to_samples(chips)
                self._src = blocks.vector_source_c(
                    samples.tolist(), repeat=True, vlen=1
                )
                if _HAVE_SOAPY:
                    self._sink = soapy.sink(
                        "driver=hackrf", "fc32", 1, "", "", [""], [""]
                    )
                    self._sink.set_sample_rate(0, SAMP_RATE_HZ)
                    self._sink.set_frequency(0, center_hz)
                    # Explicit float dB for AMP — matches RX AMP handling.
                    # HackRF TX AMP is two-state: 0.0 dB (off) or 14.0 dB (on).
                    self._sink.set_gain(0, "AMP", 14.0 if tx_amp_on else 0.0)
                    self._sink.set_gain(0, "VGA", float(tx_vga_db))
                else:
                    # Fallback: file sink so something exists without SoapySDR
                    self._sink = blocks.file_sink(
                        gr.sizeof_gr_complex, "/tmp/sisl_tx.cfile"
                    )
                self.connect(self._src, self._sink)

            elif mode == "rx":
                if _HAVE_SOAPY:
                    self._src = soapy.source(
                        "driver=hackrf", "fc32", 1, "", "", [""], [""]
                    )
                    self._src.set_sample_rate(0, SAMP_RATE_HZ)
                    self._src.set_frequency(0, center_hz)
                    self._src.set_gain(0, "AMP", False)
                    self._src.set_gain(0, "LNA", HACKRF_RX_LNA_DB)
                    self._src.set_gain(0, "VGA", HACKRF_RX_VGA_DB)
                else:
                    self._src = blocks.null_source(gr.sizeof_gr_complex)
                self._sink = blocks.file_sink(
                    gr.sizeof_gr_complex, "/tmp/sisl_rx.cfile"
                )
                self.connect(self._src, self._sink)

            else:
                raise ValueError(f"mode must be 'tx' or 'rx', got {mode!r}")


# ── TX to file (pure numpy, no radio) ──────────────────────────────────────

def tx_to_file(message: bytes, path: str,
               prefix_ms: float = 0.0,
               repeats: int = 1) -> int:
    """Synthesize a TX capture from `message` and write it as complex64.

    Bypasses GNU Radio and HackRF entirely. Useful for smoke-testing the
    TX upsampling path and the offline despread chain without a bench
    setup.

    `prefix_ms`: silence prefix before the signal (exercises
    find_frame_start acquisition). Rounded to a whole-chip boundary so
    integer decimation at RX stays aligned.
    `repeats`: how many copies of the message to concatenate.
    """
    chips = build_tx_chips(message)
    samples = upsample_chips_to_samples(chips)
    if repeats > 1:
        samples = np.tile(samples, repeats)

    prefix = np.zeros(0, dtype=np.complex64)
    if prefix_ms > 0:
        n_prefix = int(prefix_ms * SAMP_RATE_HZ / 1000)
        # Snap to whole-chip boundary so decimation stays chip-phase-aligned
        n_prefix = (n_prefix // SAMPS_PER_CHIP) * SAMPS_PER_CHIP
        prefix = np.zeros(n_prefix, dtype=np.complex64)

    out = np.concatenate([prefix, samples]).astype(np.complex64)
    out.tofile(path)
    return out.size


# ── Offline despread utility ────────────────────────────────────────────────

def _decimate_to_chips(samples: np.ndarray,
                       samps_per_chip: int = SAMPS_PER_CHIP) -> np.ndarray:
    """Mean-of-window decimation: samples → chip-rate float32.

    Averages each contiguous block of `samps_per_chip` samples. Preserves
    amplitude information needed by matched-filter acquisition — unlike
    the previous `np.sign` approach which discarded magnitude entirely.

    Only the real (I) component is used; the demo TX is BPSK with zero Q.
    """
    i = np.asarray(samples, dtype=np.complex64).real.astype(np.float32)
    n_full = (len(i) // samps_per_chip) * samps_per_chip
    if n_full == 0:
        return np.zeros(0, dtype=np.float32)
    return i[:n_full].reshape(-1, samps_per_chip).mean(axis=1)


def offline_despread(cfile_path: str,
                     samps_per_chip: int = SAMPS_PER_CHIP,
                     max_search_chips: Optional[int] = None,
                     max_bytes: Optional[int] = None
                     ) -> tuple[bytes, Optional[int]]:
    """Read a complex64 capture, find frame start, despread all bytes.

    Returns `(recovered_bytes, frame_offset_chips)`:
        recovered_bytes   — every byte the despreader could recover from
                            the located acquisition point to end of stream
                            (or `max_bytes` if specified)
        frame_offset_chips — chip offset where the matched filter locked,
                            or None if no peak was above threshold (in
                            which case decoding falls back to chip 0 and
                            will likely return noise)

    The length is determined by the capture, not by any expected message.
    Callers inspect the returned bytes to find their payload: Phase 1 raw
    text can be located via substring search, Phase 2 SISL frames via ASM
    (0x1ACFFC1D) + version + msg_type parsing.

    `max_search_chips`: bound the acquisition search window. None scans
    the full capture.
    `max_bytes`: optional upper bound on how many bytes to decode (useful
    for very large captures where you only care about the first frame).
    """
    raw = np.fromfile(cfile_path, dtype=np.complex64)
    chip_stream = _decimate_to_chips(raw, samps_per_chip=samps_per_chip)

    if len(chip_stream) < sf.CHIPS_PER_SYMBOL:
        have_samples = len(raw)
        have_ms = have_samples / SAMP_RATE_HZ * 1000
        raise ValueError(
            f"capture has no decodable content:\n"
            f"  file:     {cfile_path}\n"
            f"  have:     {have_samples} samples "
            f"({len(chip_stream)} chips, {have_ms:.1f} ms)\n"
            f"  minimum:  {sf.CHIPS_PER_SYMBOL} chips (one bit)\n"
            f"Re-capture with a longer --duration or verify RX was "
            f"actually receiving signal."
        )

    offset = sf.find_frame_start(chip_stream, max_search=max_search_chips)
    start = offset if offset is not None else 0
    avail_chips = len(chip_stream) - start
    n_bytes = avail_chips // (8 * sf.CHIPS_PER_SYMBOL)
    if max_bytes is not None:
        n_bytes = min(n_bytes, max_bytes)
    if n_bytes == 0:
        return b"", offset

    needed = n_bytes * 8 * sf.CHIPS_PER_SYMBOL
    recovered = sf.rx_chips_to_bytes(chip_stream[start:start + needed], n_bytes)
    return recovered, offset


# ── SISL frame auto-detection ──────────────────────────────────────────────

_ASM_BYTES = b"\x1A\xCF\xFC\x1D"


# ── Polarity mask constants ───────────────────────────────────────────────
#
# The BPSK demodulator has a 180° phase ambiguity: the decoded frame may
# be the true bits or any of several XOR transformations thereof. These
# six masks cover the possible polarities the receiver can land on. Each
# entry is (label_suffix, even_byte_mask, odd_byte_mask).

_POLARITY_MASKS = [
    ("",      0x00, 0x00),       # identity
    ("-inv",  0xFF, 0xFF),       # full inversion
    ("-alt",  0xAA, 0xAA),       # alternating bits
    ("-alt2", 0x55, 0x55),       # alternating bits, opposite phase
    ("-alt-inv",  0x55, 0xAA),   # alternating bytes
    ("-alt2-inv", 0xAA, 0x55),   # alternating bytes, opposite phase
]


def _apply_polarity(frame_bytes: bytes, even_mask: int, odd_mask: int) -> bytes:
    """XOR each byte of `frame_bytes` with a per-parity mask."""
    out = bytearray(len(frame_bytes))
    for i, x in enumerate(frame_bytes):
        out[i] = x ^ (even_mask if i % 2 == 0 else odd_mask)
    return bytes(out)
# Bit-unpacked ASM for sliding-bit-offset search. MSB-first to match
# bytes_to_bits / rx_chips_to_bytes conventions.
_ASM_BITS = np.unpackbits(
    np.frombuffer(_ASM_BYTES, dtype=np.uint8)
).astype(np.uint8)

# Extended pilot: ASM + deterministic version (0x03) and msg_type (0x01)
# bytes. Every valid SISL hail frame begins with ASM || 0x03 || 0x01,
# so these 48 bits are a free extended training sequence for phase and
# frequency estimation. Longer pilot = tighter slope variance = better
# coherent decode at marginal SNR.
_PILOT_BYTES = _ASM_BYTES + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
_PILOT_BITS = np.unpackbits(
    np.frombuffer(_PILOT_BYTES, dtype=np.uint8)
).astype(np.uint8)


class LlrAccumulator:
    """Multi-copy FEC LLR accumulator for SISL hails.

    The TX loops the same FEC-encoded hail frame repeatedly. Each clean
    per-block detection yields a per-bit soft-value vector. Adding these
    vectors element-wise across copies gives +3 dB effective SNR per
    doubling (coherent addition of independent AWGN observations).

    The accumulator stores only the FEC body LLRs (2048 coded bits);
    the 48-bit uncoded header is used for polarity vote and ASM
    cheap-reject but is not summed. try_decrypt runs sisl_fec.decode
    (soft Viterbi) on the accumulated body LLRs.

    `max_copies` is the cap before exponential forgetting (halving).
    """

    def __init__(self, n_bits: int, pass_rms: float = 0.6,
                 max_copies: int = 64, max_asm_errs: int = 2):
        assert n_bits == sc.HAIL_FEC_TOTAL_BITS, (
            f"n_bits must be HAIL_FEC_TOTAL_BITS "
            f"({sc.HAIL_FEC_TOTAL_BITS}); got {n_bits}"
        )
        self.n_bits = n_bits
        self.pass_rms = pass_rms
        self.max_copies = max_copies
        self.max_asm_errs = max_asm_errs
        self._header_bits = sc.HAIL_FEC_HEADER_BITS
        self._accum_size = sc.HAIL_FEC_BODY_CODED_BITS
        self.accumulated = np.zeros(self._accum_size, dtype=np.float64)
        self.n_copies = 0
        self._asm_signs = np.where(_ASM_BITS == 0, 1.0, -1.0).astype(np.float64)

    def reset(self) -> None:
        self.accumulated.fill(0.0)
        self.n_copies = 0

    def try_add(self, result: dict) -> bool:
        """Try to add a block-decode result to the accumulator.

        Returns True if the result was accepted and added, False otherwise.
        """
        llrs = result.get("fec_llrs")
        if llrs is None:
            return False
        if len(llrs) < self.n_bits:
            return False
        # The soft-Viterbi + Poly1305 gate at try_decrypt is the real
        # quality oracle. Skip phase_rms and asm_errs gates — the FEC +
        # crypto layer rejects bad copies after combining.
        llrs_f64 = llrs[:self.n_bits].astype(np.float64)
        polarity_vote = float(np.dot(llrs_f64[:32], self._asm_signs))
        sign = 1.0 if polarity_vote >= 0 else -1.0
        body_llrs = llrs_f64[self._header_bits:]
        self.accumulated += sign * body_llrs
        self.n_copies += 1
        if self.n_copies >= self.max_copies:
            self.accumulated *= 0.5
            self.n_copies //= 2
        return True

    def try_decrypt(
        self,
        responder_static,
    ) -> Optional[tuple[object, str, int]]:
        """Soft-Viterbi-decode accumulated body LLRs and trial-decrypt.

        Returns (decoded_hail, polarity_label, chase_flips) or None.
        """
        if self.n_copies == 0:
            return None
        body_llrs_f32 = self.accumulated.astype(np.float32)
        body_bits = sisl_fec.decode(
            body_llrs_f32, sc.HAIL_FEC_BODY_PAYLOAD_BITS,
        )
        body_bytes = np.packbits(body_bits).tobytes()
        assert len(body_bytes) == sc.HAIL_BODY_PAYLOAD_LEN
        header = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
        frame = header + body_bytes
        decoded = sc.decode_hail(frame, responder_static)
        if decoded is not None:
            return decoded, "fec-acc", 0
        return None


# Pre-computed differential polarity template for the 32-bit ASM.
# For each of 31 consecutive bit pairs in the ASM, the "expected" differential
# dot-product sign is +1 if the two bits are equal (same bit), -1 if they differ.
# Soft-decision ASM search correlates this template against the actual
# differential dot-product stream.
_ASM_DIFF_POLARITY = np.where(
    _ASM_BITS[1:] == _ASM_BITS[:-1],
    +1.0, -1.0,
).astype(np.float64)


def _extract_soft_frame_bits(
    soft: np.ndarray,
    n_soft: int,
    best_offset: int,
    best_score: float,
    n_bits: int,
    n_peaks: int,
) -> bytes:
    """Hard-decision bit extraction given a soft correlator match position.

    Used by find_sisl_frame_soft_topk to produce a bit-level frame from
    each candidate ASM position. If the match is near the end of
    peak_values and not enough peaks remain, zero-pad the tail.
    """
    best_sign = +1 if best_score >= 0 else -1
    bits = np.empty(n_bits, dtype=np.uint8)
    bits[0] = 0
    bits_available = min(n_bits, n_peaks - best_offset)
    for k in range(1, bits_available):
        src = best_offset + k - 1
        if src >= n_soft:
            break
        bits[k] = bits[k - 1] if soft[src] >= 0 else (1 - bits[k - 1])
    if bits_available < n_bits:
        bits[bits_available:] = 0
    if best_sign < 0:
        bits = 1 - bits
    return np.packbits(bits).tobytes()


def find_sisl_frame_soft_topk(
    peak_values: list,
    frame_len: int = sc.HAIL_FRAME_LEN,
    k: int = 5,
    min_separation: int = 4,
) -> list:
    """Return the top-K ASM candidate positions by |soft_score|.

    At marginal SNR, the argmax soft score may be a noise-driven winner
    while the true ASM sits at a lower-but-plausible position. Searching
    the top K candidates lets the downstream coherent+chase decode try
    each alternative before giving up.

    `min_separation` enforces that returned candidates are at least N
    bit positions apart, so adjacent samples in the same peak neighborhood
    don't all crowd the top-K list.

    Returns a list of (bit_offset, soft_score, frame_bytes, pts_ratio)
    tuples, sorted by |soft_score| descending, at most K entries long.
    `pts_ratio` is the candidate's |score| divided by the median |score|
    across all positions — a CFAR-style peak-to-sidelobe ratio usable
    as an additional cheap gate before feeding candidates to the
    expensive coherent decode + Chase pipeline. Clean signal has
    pts_ratio > 5; pure noise has pts_ratio ≈ 2–3.
    Empty list if the buffer is too short.
    """
    n_bits = frame_len * 8
    n_peaks = len(peak_values)
    if n_peaks < 33:
        return []

    peaks = np.array(peak_values, dtype=np.complex128)
    diffs = (peaks[1:] * np.conj(peaks[:-1])).real
    mags = np.abs(peaks[1:]) * np.abs(peaks[:-1])
    soft = np.where(mags > 1e-12, diffs / mags, 0.0).astype(np.float64)

    template = _ASM_DIFF_POLARITY
    n_soft = len(soft)
    if n_soft < 31:
        return []

    # Compute all positions' soft scores in one vectorized pass.
    n_positions = n_soft - 30
    windowed = np.lib.stride_tricks.sliding_window_view(
        soft, window_shape=31
    )[:n_positions]
    scores = windowed @ template     # shape (n_positions,)
    abs_scores = np.abs(scores)

    # CFAR sidelobe estimate: median of all |scores|. Robust to outliers
    # (the real ASM peak itself) since median ignores them.
    sidelobe = float(np.median(abs_scores)) + 1e-9

    # Greedy top-K with minimum-separation constraint. We pick the highest
    # |score|, mask out a ±min_separation neighborhood, repeat until we
    # have K or run out of candidates.
    taken = np.zeros(n_positions, dtype=bool)
    results = []
    for _ in range(k):
        candidate_mask = ~taken
        if not candidate_mask.any():
            break
        # Restrict argmax to untaken positions
        masked = np.where(candidate_mask, abs_scores, -1.0)
        idx = int(np.argmax(masked))
        if masked[idx] <= 0:
            break
        score = float(scores[idx])
        pts_ratio = float(abs_scores[idx]) / sidelobe
        frame_bytes = _extract_soft_frame_bits(
            soft, n_soft, idx, score, n_bits, n_peaks,
        )
        results.append((idx, score, frame_bytes, pts_ratio))
        lo = max(0, idx - min_separation)
        hi = min(n_positions, idx + min_separation + 1)
        taken[lo:hi] = True
    return results


# ── Live RX: stream samples and decode hails in real time ─────────────────

# Initial signal-presence prefilter — a cheap peak/median ratio test
# that rejects the noisiest blocks before running the more expensive
# periodicity check. The periodicity check (16 symbol-spaced peaks
# median ≥ 30% of global max) is the authoritative test; this ratio
# is just a cheap first-pass filter.
#
# Pure Gaussian noise gives peak/median ≈ 5–8 for block lengths of
# millions of samples. Weak-but-real bench signals can sit at ratio
# 4–10 when antennas are misaligned or path loss is large. Default
# of 4 admits most real signals and lets the periodicity check do
# the real rejection. Override with --signal-threshold.
_SIGNAL_FLOOR_RATIO = 4.0


def _extract_llrs_at_position(
    peak_values: list,
    peak_offset: int,
) -> dict:
    """Run the coherent decode at one ASM offset and return LLR diagnostics.

    Used to populate llrs / c_frame / phase_rms_residual_rad / asm_errs_in_coherent
    on every status branch where peak_values are available, so the LLR
    accumulator can chase-combine across blocks regardless of whether
    the current block decrypted on its own. No decryption attempted here.

    Returns a dict with keys (llrs, c_frame, phase_rms_residual_rad,
    asm_errs_in_coherent), all None if the offset is out of range or the
    coherent decode fails.
    """
    out: dict = {
        "llrs": None,
        "fec_llrs": None,
        "c_frame": None,
        "phase_rms_residual_rad": None,
        "asm_errs_in_coherent": None,
    }
    aligned_peaks = peak_values[peak_offset:]
    n_frame_bits = sc.HAIL_FRAME_LEN * 8           # 1064
    n_fec_bits = sc.HAIL_FEC_TOTAL_BITS             # 2096
    if len(aligned_peaks) < n_frame_bits:
        return out

    # Always run the legacy coherent decoder for the 1064-bit `llrs`
    # (the non-FEC accumulator and the soft-correlator path consume
    # this). It uses the existing pilot-only (θ₀, Δθ) fit which is
    # accurate enough over a 1064-symbol codeword.
    coherent = sf.coherent_decode_from_pilot(
        aligned_peaks, 0, _PILOT_BITS, n_frame_bits,
    )
    if coherent is None:
        return out
    c_frame, c_soft, _c_theta0, _c_delta, c_rms = coherent
    out["c_frame"] = c_frame
    out["llrs"] = c_soft
    out["phase_rms_residual_rad"] = c_rms
    c_bits_first32 = np.unpackbits(
        np.frombuffer(c_frame[:4], dtype=np.uint8))
    out["asm_errs_in_coherent"] = int(np.sum(c_bits_first32 != _ASM_BITS))

    # If we have enough peaks for the FEC channel layout, run the
    # DBPSK fast-path decoder over the longer span. This produces the
    # 2096-bit `fec_llrs` vector that the FEC accumulator + soft Viterbi
    # consume. The DBPSK decoder uses pilot-aided drift estimation
    # (estimate_drift_per_symbol with pilot_bits) and differential
    # demodulation across the body — the two-step fix mandated by the
    # second reviewer's S4 critique to handle the back-half phase wrap
    # that the legacy coherent decoder cannot recover from on a
    # 2096-symbol codeword. See sisl_framer.dbpsk_decode_from_pilot.
    if len(aligned_peaks) >= n_fec_bits:
        dbpsk = sf.dbpsk_decode_from_pilot(
            aligned_peaks, _PILOT_BITS, n_fec_bits,
        )
        if dbpsk is not None:
            _fec_frame, fec_soft, _, _, _ = dbpsk
            out["fec_llrs"] = fec_soft
    return out


def _acquire_and_track(
    samples: np.ndarray,
    samps_per_chip: int,
    samp_hz: float,
    signal_threshold: float,
) -> dict:
    """Frequency estimation, correction, matched filter, periodicity test,
    and per-symbol tracking decode.

    Returns a dict with peak_values, positions, freq_hz, peak_mag,
    median_mag, rad_per_sample on success, or a status dict on failure.
    """
    if len(samples) < sf.CHIPS_PER_SYMBOL * samps_per_chip * 200:
        return {"status": "short_block"}

    samples = (samples - samples.mean()).astype(np.complex64)
    rad_per_sample = sf.estimate_freq_offset_rad_per_sample(
        samples, iterations=3)
    freq_hz = rad_per_sample * samp_hz / (2 * np.pi)
    samples_corr = sf.apply_freq_correction(samples, rad_per_sample)

    corr_c = sf.matched_filter_complex_sample_rate(samples_corr, samps_per_chip)
    if len(corr_c) == 0:
        return {"status": "short_block"}
    mag = np.abs(corr_c).astype(np.float32)
    peak_mag = float(mag.max())
    median_mag = float(np.median(mag))

    prefilter_threshold = min(signal_threshold, 2.5)
    if median_mag == 0.0 or peak_mag < prefilter_threshold * median_mag:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    # Periodic structure test
    first_peak_pos = int(np.argmax(mag))
    samples_per_symbol = sf.CHIPS_PER_SYMBOL * samps_per_chip
    search_half = samples_per_symbol // 4
    test_peaks: list[float] = []
    for k in range(16):
        pos_k = first_peak_pos + k * samples_per_symbol
        if pos_k + search_half >= len(mag):
            break
        lo = max(0, pos_k - search_half)
        hi = min(len(mag), pos_k + search_half + 1)
        test_peaks.append(float(mag[lo:hi].max()))

    if len(test_peaks) < 4:
        return {"status": "short_block", "peak_mag": peak_mag, "median_mag": median_mag}

    periodic_ratio = float(np.median(test_peaks)) / peak_mag if peak_mag > 0 else 0.0
    if periodic_ratio < 0.3:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "periodic_ratio": periodic_ratio,
            "note": "spurious spike, no periodic structure",
        }

    # Tracking decode — need 2× FEC frame for search margin
    target_bytes = (2 * sc.HAIL_FEC_TOTAL_BITS + 7) // 8
    track_result = sf.decode_with_freq_tracking(
        samples,
        samps_per_chip=samps_per_chip,
        n_bytes=target_bytes,
        freq_offset_rad_per_sample=rad_per_sample,
    )
    if track_result is None:
        fallback_bytes = (sc.HAIL_FEC_TOTAL_BITS + 7) // 8
        track_result = sf.decode_with_freq_tracking(
            samples,
            samps_per_chip=samps_per_chip,
            n_bytes=fallback_bytes,
            freq_offset_rad_per_sample=rad_per_sample,
        )
        if track_result is None:
            return {
                "status": "track_lost",
                "peak_mag": peak_mag,
                "median_mag": median_mag,
                "rad_per_sample": rad_per_sample,
                "freq_offset_hz": freq_hz,
            }

    return {
        "status": "acquired",
        "peak_values": track_result.get("peak_values", []),
        "positions": track_result["positions"],
        "freq_hz": freq_hz,
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
    }


def _try_fec_decrypt(
    peak_values: list,
    positions: list,
    responder_static: ec.EllipticCurvePrivateKey,
    top_k_soft: int,
    freq_hz: float,
    peak_mag: float,
    median_mag: float,
    rad_per_sample: float,
) -> dict:
    """FEC fast path: soft correlator search, DBPSK decode, Viterbi, decrypt.

    Returns a result dict with status decrypt_ok, decrypt_fail, or track_lost.
    """
    if not peak_values or len(peak_values) < sc.HAIL_FEC_TOTAL_BITS:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "note": "peak_values too short for HAIL_FEC_TOTAL_BITS",
        }

    topk = find_sisl_frame_soft_topk(
        peak_values, sc.HAIL_FRAME_LEN, k=top_k_soft,
    )

    best_attempt: Optional[dict] = None
    best_offset = -1
    best_score = 0.0
    best_pts_ratio = 0.0
    decoded_hail: Optional[sc.DecodedHail] = None
    polarity_label = "fec"

    for cand_offset, cand_score, _cand_frame, cand_pts in topk:
        if cand_offset + sc.HAIL_FEC_TOTAL_BITS > len(peak_values):
            continue
        if abs(cand_score) <= 10.0 or cand_pts < 3.0:
            continue

        llr_diag = _extract_llrs_at_position(peak_values, int(cand_offset))
        fec_llrs_arr = llr_diag.get("fec_llrs")
        if fec_llrs_arr is None:
            continue

        attempt = sc.decode_hail_fec_from_llrs(fec_llrs_arr, responder_static)
        if attempt is None:
            attempt = sc.decode_hail_fec_from_llrs(
                -fec_llrs_arr, responder_static,
            )
            if attempt is not None:
                polarity_label = "fec-inv"
        else:
            polarity_label = "fec"

        if attempt is not None:
            decoded_hail = attempt
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)
            best_attempt = {"llr_diag": llr_diag, "fec_llrs": fec_llrs_arr}
            break

        if best_attempt is None or abs(cand_score) > abs(best_score):
            best_attempt = {"llr_diag": llr_diag, "fec_llrs": fec_llrs_arr}
            best_offset = int(cand_offset)
            best_score = float(cand_score)
            best_pts_ratio = float(cand_pts)

    if best_attempt is None:
        return {
            "status": "track_lost",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "note": "no soft-correlator candidate cleared the gate",
        }

    llr_diag = best_attempt["llr_diag"]
    fec_llrs_arr = best_attempt["fec_llrs"]
    base = {
        "start_sample": positions[0] if positions else 0,
        "asm_at_byte": f"soft-bit{best_offset}",
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "rad_per_sample": rad_per_sample,
        "freq_offset_hz": freq_hz,
        "soft_score": best_score,
        "pts_ratio": best_pts_ratio,
        "llrs": llr_diag["llrs"],
        "fec_llrs": fec_llrs_arr,
        "c_frame": llr_diag["c_frame"],
        "phase_rms_residual_rad": llr_diag["phase_rms_residual_rad"],
        "asm_errs_in_coherent": llr_diag["asm_errs_in_coherent"],
    }
    if decoded_hail is None:
        return {"status": "decrypt_fail", "polarity": "fec", **base}
    return {
        "status": "decrypt_ok",
        "polarity": polarity_label,
        "body": decoded_hail.body,
        "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
        **base,
    }


def _decode_one_hail_in_block(
    samples: np.ndarray,
    responder_static: ec.EllipticCurvePrivateKey,
    samps_per_chip: int = SAMPS_PER_CHIP,
    samp_hz: float = SAMP_RATE_HZ,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
) -> dict:
    """Process one block of baseband samples, try to decode one FEC hail.

    Thin dispatcher: calls _acquire_and_track, then _try_fec_decrypt.

    Statuses:
      short_block   — fewer than one code-period of samples
      no_signal     — CORRECTED peak/median below threshold
      track_lost    — tracker lost lock partway through the frame
      decrypt_fail  — hail frame found but Poly1305 tag mismatch
      decrypt_ok    — hail decoded and decrypted under responder_static
    """
    acq = _acquire_and_track(samples, samps_per_chip, samp_hz, signal_threshold)
    if acq["status"] != "acquired":
        return acq

    return _try_fec_decrypt(
        peak_values=acq["peak_values"],
        positions=acq["positions"],
        responder_static=responder_static,
        top_k_soft=top_k_soft,
        freq_hz=acq["freq_hz"],
        peak_mag=acq["peak_mag"],
        median_mag=acq["median_mag"],
        rad_per_sample=acq["rad_per_sample"],
    )


# ── Live event formatting (presentation, not decode logic) ────────────────

def _print_live_event(block_num: int, result: dict, quiet: bool = False) -> None:
    """Print one line describing a block's processing result.

    `quiet=True` suppresses the "no signal" and "interference" output so
    the operator only sees genuine SISL events (decrypt ok / fail).
    """
    s = result["status"]
    foff = result.get("freq_offset_hz", 0.0)
    if s == "decrypt_ok":
        b = result["body"]
        print(f"[{block_num:4d}] DECRYPTED  "
              f"sample={result['start_sample']}  "
              f"asm@{result['asm_at_byte']}  "
              f"peak={result['peak_mag']:.3g}  "
              f"Δf={foff:+.0f}Hz  "
              f"pol={result.get('polarity', '?')}  "
              f"nonce={b.body_nonce.hex()}  "
              f"freq=+{b.center_freq_offset}MHz  mode=0x{b.mode:02x}")
    elif s == "decrypt_fail":
        print(f"[{block_num:4d}] FRAME FOUND  "
              f"sample={result.get('start_sample', 0)}  "
              f"asm@{result['asm_at_byte']}  "
              f"Δf={foff:+.0f}Hz  "
              f"pol={result.get('polarity', '?')}  "
              f"— DECRYPT FAILED (not addressed to this key)")
    elif s == "frame_fuzzy":
        d = result.get("asm_distance", -1)
        print(f"[{block_num:4d}] FRAME FUZZY  "
              f"asm@{result['asm_at_byte']}  "
              f"ASM hamming={d}/32  "
              f"peak={result['peak_mag']:.3g}  "
              f"Δf={foff:+.0f}Hz  pol={result.get('polarity', '?')}  "
              f"— frame detected with {d} bit errors, "
              f"too noisy to decrypt")
        print(f"       first 16 bytes: {result.get('first_16_bytes_hex','')}")
    elif s == "frame_soft":
        ss = result.get("soft_score", 0.0)
        drift = result.get("drift_per_symbol_rad", 0.0)
        drift_deg = drift * 180.0 / 3.14159265
        rms = result.get("phase_rms_residual_rad")
        rms_str = f"{rms:.2f}" if rms is not None else "n/a"
        # Quality hint: <0.3 → clean lock, 0.3-0.9 → marginal, >0.9 → noise
        if rms is None:
            qual = ""
        elif rms < 0.3:
            qual = " CLEAN"
        elif rms < 0.9:
            qual = " MARGINAL"
        else:
            qual = " NOISE"
        print(f"[{block_num:4d}] FRAME SOFT-DETECTED  "
              f"asm@bit{result['asm_at_bit']}  "
              f"soft={ss:+.1f}/31  "
              f"peak={result['peak_mag']:.3g}  "
              f"Δf={foff:+.0f}Hz  "
              f"drift={drift_deg:+.1f}°/sym  "
              f"pol={result.get('polarity', '?')}  "
              f"phase_rms={rms_str} rad{qual}  "
              f"— SISL frame detected via soft correlator, body bit "
              f"errors prevent Poly1305 verification")
        print(f"       diff 16 bytes: {result.get('first_16_bytes_hex', '')}")
        coh = result.get("coherent_16_bytes_hex")
        asm_errs = result.get("asm_errs_in_coherent")
        if coh is not None:
            err_str = (f"(ASM errs in coherent first 32 bits: {asm_errs}/32)"
                       if asm_errs is not None else "")
            print(f"       coh  16 bytes: {coh}  {err_str}")
    elif s == "track_lost":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        print(f"[{block_num:4d}] TRACK LOST: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"Δf={foff:+.0f}Hz")
    elif s == "noise_lock" and not quiet:
        # Suppress in quiet mode: these are spurious soft-correlator
        # triggers on interference (phase_rms > 0.9 AND asm_errs > 4).
        # In verbose mode, show a short one-liner so operators can see
        # the rejection activity but not confuse it with frame events.
        ss = result.get("soft_score", 0.0)
        rms = result.get("phase_rms_residual_rad")
        rms_str = f"{rms:.2f}" if rms is not None else "n/a"
        asm_errs = result.get("asm_errs_in_coherent")
        errs_str = f"{asm_errs}/32" if asm_errs is not None else "n/a"
        print(f"[{block_num:4d}] noise-lock  "
              f"soft={ss:+.1f}/31  "
              f"phase_rms={rms_str}  asm_errs={errs_str}  "
              f"Δf={foff:+.0f}Hz  (rejected)")
    elif quiet:
        return
    elif s == "no_hail":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        drift = result.get("drift_per_symbol_rad", 0.0)
        drift_deg = drift * 180.0 / 3.14159265
        hn = result.get("min_asm_hamming_normal")
        hi = result.get("min_asm_hamming_inverted")
        best_h = None
        if hn is not None and hi is not None:
            best_h = min(hn, hi)
        elif hn is not None:
            best_h = hn
        elif hi is not None:
            best_h = hi
        best_str = f", best ASM hamming={best_h}/32" if best_h is not None else ""
        ss = result.get("soft_score")
        soft_str = f", soft={ss:+.1f}/31" if ss is not None else ""
        print(f"[{block_num:4d}] interference: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"Δf={foff:+.0f}Hz, drift={drift_deg:+.1f}°/sym{best_str}{soft_str}")
        print(f"       first 16 bytes (normal):   "
              f"{result.get('first_16_bytes_hex', '')}")
        print(f"       first 16 bytes (inverted): "
              f"{result.get('first_16_inv_hex', '')}")
        mags = result.get('first_peak_magnitudes', [])
        angs = result.get('first_peak_angles_rad', [])
        if mags and angs:
            mag_str = " ".join(f"{m_i:.0f}" for m_i in mags[:8])
            ang_str = " ".join(f"{a_i*180/3.14159:+4.0f}" for a_i in angs[:8])
            print(f"       first 8 peak |c|:   {mag_str}")
            print(f"       first 8 peak ∠c:    {ang_str} (degrees)")
    elif s == "no_signal":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        periodic = result.get("periodic_ratio", None)
        note = result.get("note", "")
        extra = ""
        if periodic is not None:
            extra = f", periodic={periodic:.2f}"
            if note:
                extra += f" ({note})"
        print(f"[{block_num:4d}] no signal: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"Δf={foff:+.0f}Hz{extra}")
    elif s == "short_block":
        print(f"[{block_num:4d}] short block (processing gap)")


def live_rx_decode(
    duration_s: float = 10.0,
    block_seconds: float = 1.5,
    responder_static: Optional[ec.EllipticCurvePrivateKey] = None,
    save_path: Optional[str] = None,
    lna_db: int = HACKRF_RX_LNA_DB,
    vga_db: int = HACKRF_RX_VGA_DB,
    amp_on: bool = False,
    center_hz: float = CENTER_FREQ_HZ,
    device_name: str = "hackrf",
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
    combine_copies: int = 0,
) -> dict:
    """Stream samples from the selected device, decode SISL hails live.

    `device_name` ∈ DEVICES.keys(). HackRF uses three gain stages
    (AMP/LNA/VGA); RTL-SDR has a single tuner gain, so when device_name
    is "rtlsdr" we clamp (lna_db + vga_db) into [0, 49] and apply it as
    the single gain (amp_on is ignored — RTL-SDR has no pre-tuner AMP).

    Frequency and sample-rate capabilities vary per device; we validate
    `center_hz` against the selected device's range before opening it.

    Returns a stats dict: blocks_processed, hails_detected, hails_decrypted,
    interference, overflows, elapsed_s, ok, error.
    """
    try:
        import SoapySDR
        from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    except ImportError as e:
        return {
            "ok": False,
            "error": f"SoapySDR Python bindings not available: {e}. "
                     f"Install with 'sudo pacman -S python-soapysdr' (Arch).",
        }

    if device_name not in DEVICES:
        return {
            "ok": False,
            "error": f"unknown device {device_name!r}; "
                     f"choices: {list(DEVICES.keys())}",
        }
    info = DEVICES[device_name]

    if center_hz < info.freq_min_hz or center_hz > info.freq_max_hz:
        return {
            "ok": False,
            "error": (
                f"{info.name} cannot tune to {center_hz/1e6:.1f} MHz; "
                f"range is {info.freq_min_hz/1e6:.0f}..{info.freq_max_hz/1e6:.0f} "
                f"MHz. ({info.notes})"
            ),
        }

    if responder_static is None:
        responder_static = demo_responder_key()

    samp_hz = info.samp_hz
    samps_per_chip = info.samps_per_chip

    print(f"opening {info.name} at {center_hz/1e6:.1f} MHz, "
          f"{samp_hz/1e6:.3f} Msps, block={block_seconds}s "
          f"(processing ~{int(block_seconds*samp_hz*8/1e6)} MB/block, "
          f"{samps_per_chip} samples/chip)")

    try:
        device = SoapySDR.Device(info.driver)
    except RuntimeError as e:
        return {
            "ok": False,
            "error": _format_device_open_error(SoapySDR, info, e),
        }
    device.setSampleRate(SOAPY_SDR_RX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_RX, 0, center_hz)

    if device_name == "hackrf":
        # Three independent gain stages. AMP is a two-state float (0 or 14).
        device.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if amp_on else 0.0)
        device.setGain(SOAPY_SDR_RX, 0, "LNA", float(lna_db))
        device.setGain(SOAPY_SDR_RX, 0, "VGA", float(vga_db))
        print(f"  RX gain: AMP={'on' if amp_on else 'off'} "
              f"LNA={lna_db} dB VGA={vga_db} dB")
    elif device_name == "rtlsdr":
        # Single tuner gain. Combine LNA+VGA so the operator has one
        # knob that behaves intuitively: "bigger number = more gain".
        combined_db = max(0.0, min(49.0, float(lna_db + vga_db)))
        device.setGain(SOAPY_SDR_RX, 0, combined_db)
        print(f"  RX gain: TUNER={combined_db:.1f} dB "
              f"(from --rx-lna {lna_db} + --rx-vga {vga_db}; "
              f"clamped to [0, 49])")
        if amp_on:
            print("  NOTE: --rx-amp ignored — RTL-SDR has no AMP stage")
    else:
        raise ValueError(f"unhandled device {device_name}")

    stream = device.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
    device.activateStream(stream)

    save_file = open(save_path, "wb") if save_path else None
    block_samples = int(block_seconds * samp_hz)
    buf = np.empty(block_samples, dtype=np.complex64)

    stats = {
        "ok": True,
        "blocks_processed": 0,
        "hails_detected": 0,     # frame header parsed (decrypt ok OR fail)
        "hails_decrypted": 0,    # decrypt_ok only
        "frames_soft": 0,        # soft correlator detected frame (|score|>10)
        "frames_fuzzy": 0,       # ASM found with 1-3 bit errors
        "interference": 0,       # signal crossed threshold but no SISL ASM
        "overflows": 0,
        "combined_copies": 0,    # copies fed into LLR accumulator
        "combined_decrypts": 0,  # decrypts from the accumulator
    }
    t_start = time.time()

    # D4: LLR accumulator for multi-copy chase combining. Only active
    # when combine_copies > 0; otherwise does nothing.
    accumulator = None
    if combine_copies > 0:
        accumulator = LlrAccumulator(
            n_bits=sc.HAIL_FEC_TOTAL_BITS,
            max_copies=combine_copies,
        )

    # ── Auto-PPM calibration state ──
    RECAL_INTERVAL = 30.0
    SETTLED_THRESHOLD_HZ = 1000.0
    current_center_hz = float(center_hz)
    total_correction_hz = 0.0
    settled = False
    last_recal_t = t_start
    offset_history: list[float] = []

    # ── Auto-gain (AGC) state ──
    # Target: peak matched-filter magnitude in [AGC_LOW, AGC_HIGH].
    # Below AGC_LOW the signal is too weak for FEC. Above AGC_HIGH
    # the ADC may be compressing. Adjust the variable-gain stage
    # (HackRF VGA or RTL-SDR TUNER) by AGC_STEP_DB per block.
    AGC_LOW = 80.0
    AGC_HIGH = 500.0
    AGC_STEP_DB = 2.0
    if device_name == "hackrf":
        current_vga = float(vga_db)
        vga_min, vga_max = 0.0, 62.0
    else:
        current_vga = max(0.0, min(49.0, float(lna_db + vga_db)))
        vga_min, vga_max = 0.0, 49.0

    try:
        while time.time() - t_start < duration_s:
            filled = 0
            overflow = False
            while filled < block_samples:
                sr = device.readStream(
                    stream,
                    [buf[filled:]],
                    block_samples - filled,
                    timeoutUs=1_000_000,
                )
                if sr.ret > 0:
                    filled += sr.ret
                elif sr.ret == -1:              # SOAPY_SDR_TIMEOUT
                    break
                elif sr.ret == -4:              # SOAPY_SDR_OVERFLOW
                    overflow = True
                    break
                else:
                    print(f"  readStream error {sr.ret}")
                    break

            if filled < block_samples // 2:
                if overflow:
                    stats["overflows"] += 1
                continue

            stats["blocks_processed"] += 1

            if save_file is not None:
                buf[:filled].tofile(save_file)

            result = _decode_one_hail_in_block(
                buf[:filled], responder_static,
                samps_per_chip=samps_per_chip,
                samp_hz=samp_hz,
                signal_threshold=signal_threshold,
                top_k_soft=top_k_soft,
            )
            _print_live_event(stats["blocks_processed"], result)

            s = result["status"]
            if s == "decrypt_ok":
                stats["hails_detected"] += 1
                stats["hails_decrypted"] += 1
            elif s == "decrypt_fail":
                stats["hails_detected"] += 1
            elif s == "frame_soft":
                stats["frames_soft"] = stats.get("frames_soft", 0) + 1
            elif s == "frame_fuzzy":
                stats["frames_fuzzy"] += 1
            elif s == "noise_lock":
                stats["noise_locks"] = stats.get("noise_locks", 0) + 1
            elif s == "no_hail":
                stats["interference"] += 1

            # ── Auto-PPM: retune SDR to drive residual offset → 0 ──
            foff = result.get("freq_offset_hz")
            now = time.time()
            if foff is not None and abs(foff) > 0:
                offset_history.append(foff)
                do_retune = False
                if not settled:
                    do_retune = len(offset_history) >= 2
                elif now - last_recal_t >= RECAL_INTERVAL:
                    do_retune = True
                if do_retune and offset_history:
                    correction = float(np.median(offset_history[-4:]))
                    current_center_hz += correction
                    total_correction_hz += correction
                    device.setFrequency(SOAPY_SDR_RX, 0, current_center_hz)
                    total_ppm = total_correction_hz / center_hz * 1e6
                    print(f"  AUTO-PPM: retune {correction:+.0f} Hz "
                          f"(total {total_correction_hz:+.0f} Hz / "
                          f"{total_ppm:+.1f} ppm, "
                          f"center {current_center_hz/1e6:.6f} MHz)")
                    offset_history.clear()
                    last_recal_t = now
                    if abs(correction) < SETTLED_THRESHOLD_HZ:
                        settled = True

            # ── Auto-gain (AGC): adjust RX gain to keep peak_mag in range ──
            pk = result.get("peak_mag")
            if pk is not None and pk > 0:
                if pk < AGC_LOW and current_vga < vga_max:
                    new_vga = min(vga_max, current_vga + AGC_STEP_DB)
                    current_vga = new_vga
                    if device_name == "hackrf":
                        device.setGain(SOAPY_SDR_RX, 0, "VGA", current_vga)
                    else:
                        device.setGain(SOAPY_SDR_RX, 0, current_vga)
                    print(f"  AGC: peak={pk:.0f} < {AGC_LOW:.0f}, "
                          f"gain → {current_vga:.0f} dB")
                elif pk > AGC_HIGH and current_vga > vga_min:
                    new_vga = max(vga_min, current_vga - AGC_STEP_DB)
                    current_vga = new_vga
                    if device_name == "hackrf":
                        device.setGain(SOAPY_SDR_RX, 0, "VGA", current_vga)
                    else:
                        device.setGain(SOAPY_SDR_RX, 0, current_vga)
                    print(f"  AGC: peak={pk:.0f} > {AGC_HIGH:.0f}, "
                          f"gain → {current_vga:.0f} dB")

            # D4: LLR chase-combining.
            if accumulator is not None:
                added = accumulator.try_add(result)
                if added:
                    stats["combined_copies"] += 1
                    acc_l1 = float(np.mean(np.abs(accumulator.accumulated)))
                    print(f"       +ACC n={accumulator.n_copies}  "
                          f"L1={acc_l1:.0f}")
                    combined = accumulator.try_decrypt(responder_static)
                    if combined is not None:
                        decoded_hail, label, n_flips = combined
                        stats["combined_decrypts"] += 1
                        stats["hails_decrypted"] += 1
                        print(f"       ACCUMULATOR DECRYPT  "
                              f"n_copies={accumulator.n_copies}  "
                              f"pol={label}  "
                              f"mode=0x{decoded_hail.body.mode:02x}  "
                              f"nonce={decoded_hail.body.body_nonce.hex()}")
                        accumulator.reset()
    except KeyboardInterrupt:
        print("  interrupted")
    finally:
        device.deactivateStream(stream)
        device.closeStream(stream)
        if save_file is not None:
            save_file.close()

    stats["elapsed_s"] = time.time() - t_start
    return stats


def offline_decode_hail(
    cfile_path: str,
    responder_static: Optional[ec.EllipticCurvePrivateKey] = None,
) -> dict:
    """Full pipeline: capture → FEC decode → trial decrypt.

    Returns a dict with:
        offset            — None (FEC path doesn't use chip-level offset)
        decoded_bytes     — empty (FEC path uses LLRs, not hard bytes)
        decoded_hail      — sisl_crypto.DecodedHail or None
        decrypted         — True iff the hail was for `responder_static`
        fec_status        — status from _decode_one_hail_in_block
        fec_polarity      — polarity label
    """
    if responder_static is None:
        responder_static = demo_responder_key()

    raw = np.fromfile(cfile_path, dtype=np.complex64)
    decode_result = _decode_one_hail_in_block(raw, responder_static)
    out: dict = {
        "offset": None,
        "decoded_bytes": b"",
        "frame": None,
        "decoded_hail": None,
        "decrypted": False,
        "fec_status": decode_result.get("status"),
        "fec_polarity": decode_result.get("polarity"),
    }
    if decode_result.get("status") == "decrypt_ok":
        out["decoded_hail"] = type("X", (), {
            "body": decode_result["body"],
            "caller_eph_pub_canonical":
                decode_result["caller_eph_pub_canonical"],
        })()
        out["decrypted"] = True
    return out


def identify_sisl_frame(data: bytes) -> Optional[dict]:
    """Scan `data` for a SISL v3 frame header and report what was found.

    Returns a dict describing the frame, or None if no ASM+version+type
    combination matches. Does NOT attempt decryption — that's the caller's
    job (via sisl_crypto.decode_hail / decode_ack).
    """
    idx = data.find(_ASM_BYTES)
    if idx < 0 or idx + 6 > len(data):
        return None
    version = data[idx + 4]
    msg_type = data[idx + 5]
    if version != 0x03:
        return {
            "asm_offset": idx,
            "version": version,
            "msg_type": msg_type,
            "frame_type": "unknown-version",
            "frame_bytes": None,
        }
    if msg_type == 0x01:                          # hail
        end = idx + sc.HAIL_FRAME_LEN
        return {
            "asm_offset": idx,
            "version": version,
            "msg_type": msg_type,
            "frame_type": "hail",
            "frame_bytes": data[idx:end] if end <= len(data) else None,
        }
    if msg_type == 0x02:                          # ack
        end = idx + sc.ACK_FRAME_LEN
        return {
            "asm_offset": idx,
            "version": version,
            "msg_type": msg_type,
            "frame_type": "ack",
            "frame_bytes": data[idx:end] if end <= len(data) else None,
        }
    return {
        "asm_offset": idx,
        "version": version,
        "msg_type": msg_type,
        "frame_type": f"unknown-msg-type-0x{msg_type:02x}",
        "frame_bytes": None,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SISL Phase 1 DSSS demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_format_freq_suggestions(),
    )
    parser.add_argument("--mode",
                        choices=("tx", "rx", "tx-to-file", "offline"),
                        required=True)
    parser.add_argument("--capture", default="/tmp/sisl_rx.cfile",
                        help="capture file (input for offline, output for tx-to-file)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="seconds to run tx or rx")
    parser.add_argument("--prefix-ms", type=float, default=0.0,
                        help="tx-to-file: leading silence in ms")
    parser.add_argument("--repeats", type=int, default=1,
                        help="tx-to-file: hail repetitions")
    parser.add_argument("--as", dest="as_key",
                        choices=("responder", "other"), default="responder",
                        help="offline/rx: which demo key to trial-decrypt as. "
                             "'responder' is the correct target, 'other' "
                             "should fail (demonstrates the identity oracle)")
    parser.add_argument("--save", action="store_true",
                        help="rx: also write raw samples to --capture path")
    parser.add_argument("--block-seconds", type=float, default=1.5,
                        help="rx: processing block duration (default 1.5 s)")
    parser.add_argument("--rx-lna", type=int, default=HACKRF_RX_LNA_DB,
                        help=f"rx: HackRF LNA (Low-Noise Amplifier, RF "
                             f"front-end gain, 0..40 dB in 8 dB steps) "
                             f"(default {HACKRF_RX_LNA_DB})")
    parser.add_argument("--rx-vga", type=int, default=HACKRF_RX_VGA_DB,
                        help=f"rx: HackRF VGA (Variable Gain Amplifier, "
                             f"baseband gain after mixer, 0..62 dB in 2 dB "
                             f"steps) (default {HACKRF_RX_VGA_DB})")
    parser.add_argument("--rx-amp", action="store_true",
                        help="rx: enable HackRF AMP (switchable 14 dB RF "
                             "preamplifier ahead of the LNA; off by default "
                             "to avoid saturating the ADC). **HackRF only** "
                             "— RTL-SDR/NESDR has no AMP stage and this "
                             "flag is silently ignored when --device rtlsdr.")
    parser.add_argument("--tx-vga", type=int, default=HACKRF_TX_VGA_DB,
                        help=f"tx: HackRF TX VGA (IF gain, baseband "
                             f"amplification before upconversion, 0..47 dB "
                             f"in 1 dB steps) (default {HACKRF_TX_VGA_DB})")
    parser.add_argument("--tx-amp", action="store_true",
                        help="tx: enable HackRF TX AMP (switchable 14 dB RF "
                             "power amplifier after the upconverter; off by "
                             "default — only enable if link budget demands "
                             "it and you have ≥40 dB of attenuation to the "
                             "peer RX")
    parser.add_argument("--tx-preamble", action="store_true",
                        help="tx: diagnostic mode — transmit ONLY the "
                             "4-byte ASM (1acffc1d) on repeat, no body. "
                             "The RX should see a soft correlator hit "
                             "every 32 bits (~32 ms) with full score ~31. "
                             "Use this to debug the RF path independent "
                             "of frame structure, crypto, or per-call "
                             "randomness. Wrong key doesn't apply — there "
                             "is no body to decrypt, so 'decrypt_ok' will "
                             "never fire; watch for frame_soft at high "
                             "score + low phase_rms instead.")
    parser.add_argument("--freq", type=float,
                        default=CENTER_FREQ_HZ / 1e6,
                        help=f"tx/rx center frequency in MHz "
                             f"(default {CENTER_FREQ_HZ/1e6:.0f}). "
                             f"See list at bottom of --help for quieter "
                             f"alternatives.")
    parser.add_argument("--signal-threshold", type=float,
                        default=_SIGNAL_FLOOR_RATIO,
                        help=f"rx: peak/median ratio that counts as signal "
                             f"present (default {_SIGNAL_FLOOR_RATIO}). "
                             f"Lower to ~6-8 to force decode attempts on "
                             f"weak signals; raise to ~20 to avoid wasted "
                             f"attempts on interference. Pure Gaussian "
                             f"noise sits around 7-8.")
    parser.add_argument("--top-k", type=int, default=5,
                        help="rx: number of top ASM candidate positions "
                             "to try in the soft correlator (default 5). "
                             "At marginal SNR the true ASM may not be the "
                             "argmax soft score; trying the top-K plausible "
                             "positions catches these. Cost: ~5x the "
                             "per-block decode compute. Set to 1 to match "
                             "old behavior, or 10 for very low SNR / "
                             "noisy environments.")
    parser.add_argument("--combine", type=int, default=0,
                        help="rx: multi-copy LLR chase combining. When N>0, "
                             "accumulate per-bit soft values from up to N "
                             "consecutive clean-fit blocks (phase_rms ≤ 0.3) "
                             "and re-attempt decryption on the summed LLRs. "
                             "Gives √N effective SNR gain because TX loops "
                             "the same hail frame. 0 disables (default); "
                             "typical values 4-16. Requires the TX to be "
                             "transmitting continuously in steady state.")
    parser.add_argument("--device", choices=list(DEVICES.keys()),
                        default="hackrf",
                        help="rx: which SDR to use. 'hackrf' (default) "
                             "covers 1 MHz – 6 GHz at 8 Msps with three "
                             "gain stages. 'rtlsdr' (NESDR Smart / "
                             "generic RTL-SDR) covers 24 MHz – 1766 MHz "
                             "at 2 Msps with a single tuner gain; "
                             "useful as a second observer on sub-GHz "
                             "bands. tx mode is always HackRF.")
    args = parser.parse_args()

    if args.mode == "tx-to-file":
        frame = build_demo_hail()
        n = tx_to_file(frame, args.capture,
                       prefix_ms=args.prefix_ms, repeats=args.repeats)
        print(f"wrote {n} complex64 samples ({n * 8} bytes) to {args.capture}")
        print(f"  hail frame:    {len(frame)} bytes")
        print(f"  asm:           {frame[0:4].hex()}")
        print(f"  version/type:  0x{frame[4]:02x} / 0x{frame[5]:02x}")
        print(f"  eph enc (hex): {frame[6:38].hex()}...")
        print(f"  prefix:        {args.prefix_ms} ms")
        print(f"  repeats:       {args.repeats}")
        print(f"  target key:    demo-responder (deterministic)")
        return 0

    if args.mode == "offline":
        if args.as_key == "responder":
            responder = demo_responder_key()
            label = "demo-responder (correct target)"
        else:
            responder = demo_other_key()
            label = "demo-other (WRONG key — should fail)"

        result = offline_decode_hail(args.capture, responder_static=responder)

        print(f"FEC decode:    status={result.get('fec_status')!r}, "
              f"polarity={result.get('fec_polarity')!r}")
        decoded_hail = result["decoded_hail"]
        if decoded_hail is None:
            print(f"TRIAL DECRYPT: FAILED as {label}")
            return 1
        body = decoded_hail.body
        print("TRIAL DECRYPT: OK (this hail was for us)")
        print(f"  center_freq_offset: +{body.center_freq_offset} MHz")
        print(f"  bandwidth_code:     0x{body.bandwidth_code:02x}")
        print(f"  mode:               0x{body.mode:02x}")
        print(f"  body_nonce:         {body.body_nonce.hex()}")
        return 0

    if args.mode == "rx":
        responder = (demo_responder_key() if args.as_key == "responder"
                     else demo_other_key())
        label = ("demo-responder (correct target)"
                 if args.as_key == "responder"
                 else "demo-other (WRONG key — should fail)")
        print(f"rx: live decode for {args.duration:.1f} s as {label}")
        save = args.capture if args.save else None
        if save is not None:
            print(f"  also saving raw samples → {save}")
        block_sec = args.block_seconds
        if block_sec < 5.0:
            block_sec = 6.0
        stats = live_rx_decode(
            duration_s=args.duration,
            block_seconds=block_sec,
            responder_static=responder,
            save_path=save,
            lna_db=args.rx_lna,
            vga_db=args.rx_vga,
            amp_on=args.rx_amp,
            center_hz=args.freq * 1e6,
            device_name=args.device,
            signal_threshold=args.signal_threshold,
            top_k_soft=args.top_k,
            combine_copies=args.combine,
        )
        if not stats.get("ok", False):
            print(f"rx failed: {stats.get('error', 'unknown')}",
                  file=sys.stderr)
            return 2
        print()
        print("RX summary:")
        print(f"  elapsed:         {stats['elapsed_s']:.1f} s")
        print(f"  blocks:          {stats['blocks_processed']}")
        print(f"  overflows:       {stats.get('overflows', 0)}")
        print(f"  hails detected:  {stats['hails_detected']} "
              "(SISL frame parsed)")
        print(f"  hails decrypted: {stats['hails_decrypted']} "
              "(Poly1305 verified)")
        if stats.get("combined_copies", 0) or stats.get("combined_decrypts", 0):
            print(f"  combined copies: {stats.get('combined_copies', 0)}")
            print(f"  combined decrypt:{stats.get('combined_decrypts', 0)}")
        return 0 if stats["hails_decrypted"] > 0 else 1

    # mode == "tx"
    if not _HAVE_GR:
        print("gnuradio not installed — run after:")
        print("  sudo pacman -S gnuradio gnuradio-companion "
              "soapysdr soapysdr-hackrf")
        return 2

    tb = DSSSHiddenSignalTop(
        args.mode,
        tx_vga_db=args.tx_vga,
        tx_amp_on=args.tx_amp,
        center_hz=args.freq * 1e6,
        preamble_only=args.tx_preamble,
    )
    frame = tb.hail_frame
    if args.tx_preamble:
        print(f"tx: transmitting PREAMBLE-ONLY (4-byte ASM) "
              f"to {args.freq:.1f} MHz for {args.duration:.1f} s")
        print(f"  asm:           {frame.hex()} (repeating forever)")
        print(f"  symbols:       32 per cycle (~32 ms period)")
        print(f"  note:          no body, no crypto — expect frame_soft "
              f"with score ~31 at the RX, not decrypt_ok")
    else:
        print(f"tx: transmitting FEC demo hail to {args.freq:.1f} MHz "
              f"for {args.duration:.1f} s")
        print(f"  on-air:        {sc.HAIL_FEC_TOTAL_BITS} channel bits "
              f"(48 uncoded header + 2048 FEC body)")
        print(f"  underlying:    {len(frame)}-byte hail frame, FEC-encoded")
        print(f"  asm:           {frame[0:4].hex()}")
        print(f"  version/type:  0x{frame[4]:02x} / 0x{frame[5]:02x}")
        print(f"  target key:    demo-responder (deterministic)")
    print(f"  TX gain:       VGA={args.tx_vga} dB "
          f"AMP={'on (+14 dB)' if args.tx_amp else 'off'}")

    tb.start()
    time.sleep(args.duration)
    tb.stop()
    tb.wait()
    print(f"done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
