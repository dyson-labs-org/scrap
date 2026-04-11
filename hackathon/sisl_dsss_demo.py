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
                     hackrf_device: str = "hackrf=0"):
            gr.top_block.__init__(self, "SISL DSSS Hidden Signal Demo")

            self.mode = mode
            self.tx_vga_db = tx_vga_db
            self.tx_amp_on = tx_amp_on
            self.center_hz = center_hz

            if mode == "tx":
                # Always TX a fresh SISL v3 hail targeting demo-responder.
                # The frame contains a random per-call body_nonce and a
                # fresh caller ephemeral, so the RX sees cryptographically
                # distinct hails even though the target key is constant.
                frame = build_demo_hail()
                self.hail_frame = frame
                chips = build_tx_chips(frame)
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
# Bit-unpacked ASM for sliding-bit-offset search. MSB-first to match
# bytes_to_bits / rx_chips_to_bytes conventions.
_ASM_BITS = np.unpackbits(
    np.frombuffer(_ASM_BYTES, dtype=np.uint8)
).astype(np.uint8)


def find_sisl_frame_bitwise(
    decoded_bytes: bytes,
    frame_len: int = sc.HAIL_FRAME_LEN,
) -> Optional[tuple[int, bytes]]:
    """Search the decoded bit stream for a SISL ASM at any bit offset.

    The live decoder reconstructs bits in TX order but has no way of
    knowing where the TX's byte boundaries fall — it picks up mid-frame
    from wherever the matched filter first locks. So the decoded bytes
    may be shifted by 1-7 bits relative to the TX frame structure, and
    a byte-level ASM search will miss the frame entirely.

    This function unpacks the decoded bytes into a bit array and slides
    the 32-bit ASM pattern one bit at a time until it finds a match.
    When found, it re-packs `frame_len` consecutive bytes starting from
    that exact bit offset, yielding the correctly-aligned frame bytes.

    Returns (bit_offset, frame_bytes) or None if not found. bit_offset
    is the position within the input bit stream where the ASM starts.

    False positive rate: ~2^-32 per bit offset × (N - 32) offsets.
    For N = 2k bits, that's ~5e-7 — negligible.
    """
    n_frame_bits = frame_len * 8
    if len(decoded_bytes) * 8 < n_frame_bits + 32:
        return None

    bits = np.unpackbits(np.frombuffer(decoded_bytes, dtype=np.uint8))
    max_bit_offset = len(bits) - n_frame_bits
    if max_bit_offset <= 0:
        return None

    asm_len = len(_ASM_BITS)
    # Vectorized sliding comparison: convolve bits with a one-hot pattern
    for bit_start in range(max_bit_offset + 1):
        if np.array_equal(bits[bit_start:bit_start + asm_len], _ASM_BITS):
            frame_bits = bits[bit_start:bit_start + n_frame_bits]
            frame_bytes = np.packbits(frame_bits).tobytes()
            return bit_start, frame_bytes
    return None

# ── Live RX: stream samples and decode hails in real time ─────────────────

# Detection threshold for "is there a signal here at all?" — matched-filter
# peak magnitude must exceed SIGNAL_FLOOR_RATIO × median. For a clean,
# coherent signal the ratio can be 50–200; for a weak but legitimate
# bench capture it's typically 10–30. Pure Gaussian noise gives peak
# /median ≈ 7–8 at block lengths of millions of samples.
#
# Default is 10: permissive enough to process borderline bench
# captures, strict enough to avoid wasting decode attempts on pure
# noise. Override with the --signal-threshold CLI flag.
_SIGNAL_FLOOR_RATIO = 10.0


def _decode_one_hail_in_block(
    samples: np.ndarray,
    responder_static: ec.EllipticCurvePrivateKey,
    samps_per_chip: int = SAMPS_PER_CHIP,
    samp_hz: float = SAMP_RATE_HZ,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
) -> dict:
    """Process one block of baseband samples, try to decode one SISL hail.

    Pipeline:
      1. Estimate carrier frequency offset via R[1] autocorrelation.
      2. Apply frequency correction.
      3. Run a COMPLEX sample-rate matched filter on the corrected signal.
      4. Check peak/median ratio — this is the actual signal-presence test.
         Without frequency correction the matched filter does not peak
         sharply at symbol boundaries when TX and RX clocks differ by
         more than a few hundred Hz, which is always the case between
         independent SDRs. Only after correction does peak/median become
         a reliable detection statistic.
      5. If detected, run per-symbol tracking decode (reusing the
         precomputed freq offset so we don't re-estimate).
      6. Try both bit polarities (BPSK 180° ambiguity) when looking
         for the SISL ASM.

    Statuses:
      short_block   — fewer than one code-period of samples
      no_signal     — CORRECTED peak/median below threshold
      track_lost    — tracker lost lock partway through the frame
      no_hail       — decoded bytes contain no SISL ASM in either polarity
      decrypt_fail  — hail frame found but Poly1305 tag mismatch
      decrypt_ok    — hail decoded and decrypted under responder_static
    """
    if len(samples) < sf.CHIPS_PER_SYMBOL * samps_per_chip * 200:
        return {"status": "short_block"}

    # ── 0. Remove DC offset ───────────────────────────────────────────
    # RTL-SDR (and any direct-conversion receiver) has significant LO
    # feedthrough — a large spike at the tuned frequency that sits right
    # on top of our signal. Subtract the block mean before doing any
    # DSP; our signal is mean-zero BPSK so this preserves the signal.
    samples = (samples - samples.mean()).astype(np.complex64)

    # ── 1. Carrier offset estimation ──────────────────────────────────
    rad_per_sample = sf.estimate_freq_offset_rad_per_sample(samples)
    freq_hz = rad_per_sample * samp_hz / (2 * np.pi)

    # ── 2. Apply correction ─────────────────────────────────────────────
    samples_corr = sf.apply_freq_correction(samples, rad_per_sample)

    # ── 3. Complex matched filter ──────────────────────────────────────
    corr_c = sf.matched_filter_complex_sample_rate(samples_corr, samps_per_chip)
    if len(corr_c) == 0:
        return {"status": "short_block"}
    mag = np.abs(corr_c).astype(np.float32)
    peak_mag = float(mag.max())
    median_mag = float(np.median(mag))

    # ── 4. Signal presence test (post-correction) ─────────────────────
    if median_mag == 0.0 or peak_mag < signal_threshold * median_mag:
        return {
            "status": "no_signal",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
        }

    # ── 4b. Periodic structure test ────────────────────────────────────
    # A single strong noise spike can exceed the peak/median ratio
    # threshold. Verify the matched filter has PERIODIC peaks at the
    # expected symbol-spacing interval: a real DSSS signal produces
    # ~1000 peaks per frame all of similar magnitude, while noise
    # produces only 1-2 outlier peaks and noise floor elsewhere.
    #
    # Starting at the global max position, sample the matched filter
    # magnitude at 16 symbol-spaced positions. The MEDIAN of those
    # samples should be at least 30% of the global max for a real
    # periodic signal. Pure noise with a spurious spike will have a
    # tiny median (the rest are noise-floor values).
    first_peak_pos = int(np.argmax(mag))
    samples_per_symbol = sf.CHIPS_PER_SYMBOL * samps_per_chip
    n_test_symbols = 16
    search_half = samples_per_symbol // 4
    test_peaks: list[float] = []
    for k in range(n_test_symbols):
        pos_k = first_peak_pos + k * samples_per_symbol
        if pos_k + search_half >= len(mag):
            break
        lo = max(0, pos_k - search_half)
        hi = min(len(mag), pos_k + search_half + 1)
        test_peaks.append(float(mag[lo:hi].max()))

    if len(test_peaks) < 4:
        return {
            "status": "short_block",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
        }

    median_test_peak = float(np.median(test_peaks))
    periodic_ratio = median_test_peak / peak_mag if peak_mag > 0 else 0.0
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

    # ── 5. Tracking decode (reuses precomputed freq offset) ───────────
    target_bytes = 2 * sc.HAIL_FRAME_LEN
    track_result = sf.decode_with_freq_tracking(
        samples,
        samps_per_chip=samps_per_chip,
        n_bytes=target_bytes,
        freq_offset_rad_per_sample=rad_per_sample,
    )
    if track_result is None:
        track_result = sf.decode_with_freq_tracking(
            samples,
            samps_per_chip=samps_per_chip,
            n_bytes=sc.HAIL_FRAME_LEN,
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
    decoded = track_result["bytes"]
    positions = track_result["positions"]

    # ── 3. Try both bit polarities (BPSK phase ambiguity) ────────────────
    decoded_inv = bytes(b ^ 0xFF for b in decoded)
    for variant_label, variant in (("normal", decoded), ("inverted", decoded_inv)):
        # ── First: byte-aligned ASM search (fast, common case) ─────
        info = identify_sisl_frame(variant)
        frame_bytes = None
        asm_location = None
        if info is not None and info["frame_type"] == "hail" and info["frame_bytes"] is not None:
            frame_bytes = info["frame_bytes"]
            asm_location = f"byte{info['asm_offset']}"

        # ── Fallback: bit-level sliding ASM search ─────────────────
        # The live decoder reconstructs bits in TX order but has no
        # idea where the TX's byte boundaries are — the first decoded
        # bit could be at any of 8 possible sub-byte positions within
        # a TX byte. Bit-level search catches this.
        if frame_bytes is None:
            bitwise = find_sisl_frame_bitwise(variant, sc.HAIL_FRAME_LEN)
            if bitwise is not None:
                bit_offset, frame_bytes = bitwise
                asm_location = f"bit{bit_offset}"

        if frame_bytes is None:
            continue

        decoded_hail = sc.decode_hail(frame_bytes, responder_static)
        if decoded_hail is None:
            return {
                "status": "decrypt_fail",
                "start_sample": positions[0] if positions else 0,
                "asm_at_byte": asm_location,
                "peak_mag": peak_mag,
                "median_mag": median_mag,
                "polarity": variant_label,
                "rad_per_sample": rad_per_sample,
                "freq_offset_hz": freq_hz,
            }
        return {
            "status": "decrypt_ok",
            "start_sample": positions[0] if positions else 0,
            "asm_at_byte": asm_location,
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "polarity": variant_label,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "body": decoded_hail.body,
            "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
        }

    # Neither polarity contains a SISL ASM — either interference or
    # drift/noise corrupted the bits beyond recognition.
    return {
        "status": "no_hail",
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "start_sample": positions[0] if positions else 0,
        "rad_per_sample": rad_per_sample,
        "freq_offset_hz": freq_hz,
        "first_16_bytes_hex": decoded[:16].hex(),
        "first_16_inv_hex": decoded_inv[:16].hex(),
        "drift_per_symbol_rad": track_result.get("drift_per_symbol_rad", 0.0),
        "first_peak_magnitudes": track_result.get("first_peak_magnitudes", []),
        "first_peak_angles_rad": track_result.get("first_peak_angles_rad", []),
    }


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
    elif s == "track_lost":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        print(f"[{block_num:4d}] TRACK LOST: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"Δf={foff:+.0f}Hz")
    elif quiet:
        return
    elif s == "no_hail":
        p = result.get("peak_mag", 0)
        m = result.get("median_mag", 0)
        r = p / m if m > 0 else float("inf")
        drift = result.get("drift_per_symbol_rad", 0.0)
        drift_deg = drift * 180.0 / 3.14159265
        print(f"[{block_num:4d}] interference: "
              f"peak={p:.3g}, median={m:.3g}, ratio={r:.1f}, "
              f"Δf={foff:+.0f}Hz, drift={drift_deg:+.1f}°/sym")
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
        "interference": 0,       # signal crossed threshold but no SISL ASM
        "overflows": 0,
    }
    t_start = time.time()

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
            )
            _print_live_event(stats["blocks_processed"], result)

            s = result["status"]
            if s == "decrypt_ok":
                stats["hails_detected"] += 1
                stats["hails_decrypted"] += 1
            elif s == "decrypt_fail":
                stats["hails_detected"] += 1
            elif s == "no_hail":
                stats["interference"] += 1
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
    max_search_chips: Optional[int] = None,
) -> dict:
    """Full pipeline: capture → despread → detect hail → trial decrypt.

    Returns a dict with:
        offset            — acquisition chip offset (None if no lock)
        decoded_bytes     — raw despread bytes
        frame             — identify_sisl_frame() result or None
        decoded_hail      — sisl_crypto.DecodedHail or None
        decrypted         — True iff the hail was for `responder_static`
        responder_label   — diagnostic string ("demo-responder", etc.)
    """
    if responder_static is None:
        responder_static = demo_responder_key()

    data, offset = offline_despread(
        cfile_path, max_search_chips=max_search_chips
    )

    result: dict = {
        "offset": offset,
        "decoded_bytes": data,
        "frame": None,
        "decoded_hail": None,
        "decrypted": False,
    }

    info = identify_sisl_frame(data)
    result["frame"] = info
    if info is None or info["frame_type"] != "hail" or info["frame_bytes"] is None:
        return result

    decoded = sc.decode_hail(info["frame_bytes"], responder_static)
    if decoded is not None:
        result["decoded_hail"] = decoded
        result["decrypted"] = True
    return result


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
    parser.add_argument("--max-search-chips", type=int, default=None,
                        help="offline: bound the acquisition search window")
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
                             "to avoid saturating the ADC)")
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

        result = offline_decode_hail(
            args.capture,
            responder_static=responder,
            max_search_chips=args.max_search_chips,
        )

        offset = result["offset"]
        data = result["decoded_bytes"]
        frame = result["frame"]
        decoded_hail = result["decoded_hail"]

        lock_state = "locked" if offset is not None else "NO LOCK — fallback to chip 0"
        print(f"acquisition:   {lock_state}")
        if offset is not None:
            print(f"  offset:      {offset} chips "
                  f"({offset / CHIP_RATE_HZ * 1000:.1f} ms into capture)")
        print(f"decoded:       {len(data)} bytes of despread data")
        print(f"attempting as: {label}")
        print()

        if frame is None:
            print("SISL frame:    NO ASM FOUND in despread bytes")
            print(f"  first 64:    {data[:64]!r}")
            return 2
        print("SISL frame:    detected")
        print(f"  asm offset:  byte {frame['asm_offset']}")
        print(f"  version:     0x{frame['version']:02x}")
        print(f"  msg type:    0x{frame['msg_type']:02x} ({frame['frame_type']})")
        if frame["frame_type"] != "hail":
            print("  (not a hail — stopping)")
            return 3
        print(f"  frame hex:   {frame['frame_bytes'].hex()}")
        print()

        if decoded_hail is None:
            print("TRIAL DECRYPT: FAILED")
            print("  Poly1305 tag mismatch — this hail was not addressed to the")
            print(f"  key we tried ({label}).")
            print("  This is the v3 identity oracle: wrong key ⇒ silent drop.")
            return 1

        body = decoded_hail.body
        print("TRIAL DECRYPT: OK (this hail was for us)")
        print(f"  center_freq_offset: +{body.center_freq_offset} MHz")
        print(f"  bandwidth_code:     0x{body.bandwidth_code:02x}")
        print(f"  mode:               0x{body.mode:02x}")
        print(f"  chip_rate_code:     0x{body.chip_rate_code:02x}")
        print(f"  body_nonce:         {body.body_nonce.hex()}")
        print(f"  flags:              0x{body.flags:02x}")
        print(f"  caller eph (canon): "
              f"{decoded_hail.caller_eph_pub_canonical.hex()}")
        return 0

    if args.mode == "rx":
        # Live RX: stream from HackRF, decode hails in real time.
        # Uses SoapySDR directly (not GR) so the processing thread can do
        # numpy DSP synchronously without a GR flowgraph wrapper.
        responder = (demo_responder_key() if args.as_key == "responder"
                     else demo_other_key())
        label = ("demo-responder (correct target)"
                 if args.as_key == "responder"
                 else "demo-other (WRONG key — should fail)")
        print(f"rx: live decode for {args.duration:.1f} s as {label}")
        save = args.capture if args.save else None
        if save is not None:
            print(f"  also saving raw samples → {save}")
        stats = live_rx_decode(
            duration_s=args.duration,
            block_seconds=args.block_seconds,
            responder_static=responder,
            save_path=save,
            lna_db=args.rx_lna,
            vga_db=args.rx_vga,
            amp_on=args.rx_amp,
            center_hz=args.freq * 1e6,
            device_name=args.device,
            signal_threshold=args.signal_threshold,
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
        print(f"  interference:    {stats.get('interference', 0)} "
              "(strong signal, non-SISL)")
        print(f"  hails detected:  {stats['hails_detected']} "
              "(SISL frame parsed)")
        print(f"  hails decrypted: {stats['hails_decrypted']} "
              "(Poly1305 verified)")
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
    )
    frame = tb.hail_frame
    print(f"tx: transmitting demo hail ({len(frame)} bytes) "
          f"to {args.freq:.1f} MHz for {args.duration:.1f} s")
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
