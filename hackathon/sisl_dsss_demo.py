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
                     preamble_only: bool = False,
                     fec: bool = False):
            gr.top_block.__init__(self, "SISL DSSS Hidden Signal Demo")

            self.mode = mode
            self.tx_vga_db = tx_vga_db
            self.tx_amp_on = tx_amp_on
            self.center_hz = center_hz
            self.preamble_only = preamble_only
            self.fec = fec

            if mode == "tx":
                if preamble_only:
                    # Diagnostic mode: transmit only the 4-byte ASM on
                    # repeat. No body, no crypto, no per-call variation.
                    # At RX, the soft correlator should fire EVERY 32 bits
                    # (every 32 ms at 1 ksym/s), giving a dense, highly
                    # verifiable reference signal. Used to debug the RF
                    # path independent of frame structure.
                    frame = _ASM_BYTES
                    self.hail_frame = frame
                    chips = build_tx_chips(frame)
                elif fec:
                    # FEC TX path: encode_hail_fec produces a 2096-bit
                    # channel array (48 uncoded header + 2048 FEC body).
                    # Each bit becomes CHIPS_PER_SYMBOL chips. The on-air
                    # waveform is twice as long per hail, but the FEC
                    # body lets the RX accumulator decode at ~5 dB lower
                    # chip SNR than the uncoded path.
                    chips, frame = build_demo_hail_fec_chips()
                    self.hail_frame = frame
                else:
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
               repeats: int = 1,
               fec: bool = False) -> int:
    """Synthesize a TX capture from `message` and write it as complex64.

    Bypasses GNU Radio and HackRF entirely. Useful for smoke-testing the
    TX upsampling path and the offline despread chain without a bench
    setup.

    `prefix_ms`: silence prefix before the signal (exercises
    find_frame_start acquisition). Rounded to a whole-chip boundary so
    integer decimation at RX stays aligned.
    `repeats`: how many copies of the message to concatenate.
    `fec`: when True, ignore `message` and synthesize a fresh FEC-encoded
    demo hail via build_demo_hail_fec_chips. The on-air signal is twice
    as long per hail (2096 channel symbols vs 1064).
    """
    if fec:
        chips, _diag_frame = build_demo_hail_fec_chips()
    else:
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

# Extended pilot: ASM + deterministic version (0x03) and msg_type (0x01)
# bytes. Every valid SISL hail frame begins with ASM || 0x03 || 0x01,
# so these 48 bits are a free extended training sequence for phase and
# frequency estimation. Longer pilot = tighter slope variance = better
# coherent decode at marginal SNR.
_PILOT_BYTES = _ASM_BYTES + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
_PILOT_BITS = np.unpackbits(
    np.frombuffer(_PILOT_BYTES, dtype=np.uint8)
).astype(np.uint8)


def _chase_decrypt_body(
    frame_bytes: bytes,
    soft_bits: np.ndarray,
    responder_static,
    k: int = 12,
) -> Optional[tuple[object, int]]:
    """Chase-II soft-decision decoding on the body of a coherent-decoded frame.

    After the coherent decoder produces a candidate frame + per-bit soft
    values, if Poly1305 verification fails, try flipping small subsets
    of the least-confident body bits and re-verifying.

    Rank body-bit positions (bit 32 onwards — after the ASM) by |soft|
    in ascending order, take the k weakest, enumerate all 2^k subsets,
    flip those bits in the candidate frame, and trial-decrypt each
    mutation.

    k=12 → 4096 trials, ~40 ms per call with Poly1305 at ~10 μs/verify.
    Catches up to 12 body-bit errors, though in practice only the few
    highest-likelihood combinations matter because soft ranking pushes
    true errors to the top.

    Returns (decoded_hail, flip_count) on success, None on failure.
    """
    # First: verify the original frame (mask=0 case).
    decoded = sc.decode_hail(frame_bytes, responder_static)
    if decoded is not None:
        return decoded, 0

    n_bits = len(frame_bytes) * 8
    if len(soft_bits) < n_bits:
        # Coherent decoder truncated: can't chase bits we don't have soft values for
        return None

    body_start_bit = 32    # after the 4-byte ASM
    # Rank body bits by |soft| ascending — weakest first
    body_soft = np.abs(soft_bits[body_start_bit:n_bits])
    order = np.argsort(body_soft)
    if len(order) < k:
        k = len(order)
    weakest = (order[:k] + body_start_bit).astype(np.int64)

    # Unpack frame to bit array (MSB-first to match np.packbits convention)
    frame_bits = np.unpackbits(np.frombuffer(frame_bytes, dtype=np.uint8))

    # Enumerate all 2^k non-zero flip masks
    total = 1 << k
    for mask in range(1, total):
        mutated = frame_bits.copy()
        m = mask
        j = 0
        while m:
            if m & 1:
                idx = weakest[j]
                mutated[idx] ^= 1
            m >>= 1
            j += 1
        candidate = np.packbits(mutated).tobytes()
        decoded = sc.decode_hail(candidate, responder_static)
        if decoded is not None:
            flip_count = bin(mask).count("1")
            return decoded, flip_count
    return None


class LlrAccumulator:
    """Multi-copy LLR chase-combiner for uncoded SISL hails.

    The TX loops the same hail frame repeatedly. Each clean per-block
    detection yields a per-bit soft-value vector aligned to the frame's
    32-bit ASM. If we add these vectors element-wise across copies, the
    effective SNR grows by +3 dB per doubling (coherent addition of
    independent AWGN observations of the same bit sign).

    This is a direct prototype of the KSP-WCC accumulator architecture
    using the existing uncoded pipeline — no FEC, no keystream. If the
    expected √N gain manifests on real bench data, the whole chase-
    combining approach is validated before any polar work.

    Alignment rules:
    - Only accept copies with phase_rms_residual_rad ≤ pass_rms
      (clean coherent fit).
    - Only accept copies with asm_errs_in_coherent == 0 (structural
      match to _ASM_BITS at the start of the decoded frame).
    - Same polarity (normal vs inverted): we normalize to the stored
      vector's polarity by flipping signs on mismatch.
    - Because the coherent decoder already aligns the first bit to the
      ASM boundary, bit-index 0 of the soft vector is canonical across
      all copies — no per-copy alignment math needed.

    After each addition, the accumulated LLRs are hard-decided to bytes
    and passed through the same 6-XOR + Chase-II decrypt pipeline used
    for single-copy decode.

    Admission gates (v2 — tuned against bench_llr_accumulator.py):
    - pass_rms = 0.6 (was 0.3). The single-copy "CLEAN" threshold is
      appropriate for reporting a confirmed decrypt, but too tight
      for accumulator admission. At the waterfall where combining is
      most useful, clean copies have rms ≈ 0.3–0.5; we want to admit
      them even when individually they couldn't decrypt alone.
    - asm_errs ≤ 2 (was == 0). Strictly structural: with 32 ASM bits,
      up to 2 errors still leaves an unambiguous match while letting
      marginal-SNR copies contribute their body bits.

    Polarity anchor (v2): the sign of llrs[0] is noise-fragile. We now
    use the dot product of llrs[:32] with the signed ASM pattern as a
    32-dimensional polarity vote. Positive → matches ASM normal;
    negative → inverted. At any plausible SNR this 32-bit coherent
    vote is effectively noise-free.

    `max_copies` is the cap before the oldest copies are decayed by
    halving (exponential forgetting). Set to a large number in
    simulation to get unbounded accumulation.
    """

    def __init__(self, n_bits: int, pass_rms: float = 0.6,
                 max_copies: int = 64, max_asm_errs: int = 2,
                 fec: bool = False):
        """If `fec` is True the accumulator runs in FEC mode:

        - `n_bits` is interpreted as the number of CHANNEL bits expected
          per copy (HAIL_FEC_TOTAL_BITS = 2096), not payload bits.
        - The internal accumulator vector stores only the body LLRs
          (HAIL_FEC_BODY_CODED_BITS = 2048); the 48-bit uncoded header
          at the front of each copy is used for polarity vote and ASM
          cheap-reject but is not summed into the accumulator.
        - try_decrypt runs sisl_fec.decode on the accumulated body LLRs
          and reconstructs the standard 133-byte hail frame for the
          existing decode_hail pipeline. Chase-II is bypassed in FEC
          mode — the convolutional code does the soft-decision work.

        If `fec` is False (default) the accumulator behaves exactly as
        before: stores `n_bits` payload LLRs, hard-decides into bytes
        for the 6-XOR + Chase-II decrypt pipeline.
        """
        self.n_bits = n_bits
        self.pass_rms = pass_rms
        self.max_copies = max_copies
        self.max_asm_errs = max_asm_errs
        self.fec = fec
        if fec:
            assert n_bits == sc.HAIL_FEC_TOTAL_BITS, (
                f"FEC mode requires n_bits == HAIL_FEC_TOTAL_BITS "
                f"({sc.HAIL_FEC_TOTAL_BITS}); got {n_bits}"
            )
            self._header_bits = sc.HAIL_FEC_HEADER_BITS
            self._accum_size = sc.HAIL_FEC_BODY_CODED_BITS
        else:
            self._header_bits = 0
            self._accum_size = n_bits
        self.accumulated = np.zeros(self._accum_size, dtype=np.float64)
        self.n_copies = 0
        self._asm_signs = np.where(_ASM_BITS == 0, 1.0, -1.0).astype(np.float64)

    def reset(self) -> None:
        self.accumulated.fill(0.0)
        self.n_copies = 0

    def try_add(self, result: dict) -> bool:
        """Try to add a block-decode result to the accumulator.

        Returns True if the result was accepted and added, False otherwise.
        Accept conditions:
        - result contains 'llrs' (or 'fec_llrs' in FEC mode)
        - phase_rms_residual_rad ≤ pass_rms
        - asm_errs_in_coherent ≤ max_asm_errs (≤2 by default)
        """
        # In FEC mode the producer publishes 2096 channel LLRs in 'fec_llrs';
        # in normal mode 1064 frame LLRs in 'llrs'. They are different
        # representations of the same coherent decode call.
        llrs_key = "fec_llrs" if self.fec else "llrs"
        llrs = result.get(llrs_key)
        rms = result.get("phase_rms_residual_rad")
        asm_errs = result.get("asm_errs_in_coherent")
        if llrs is None:
            return False
        if len(llrs) < self.n_bits:
            return False
        # Quality gates are different by mode:
        # - Non-FEC: hard-decision combining is fragile, so reject copies
        #   with bad pilot fit (phase_rms) or wrong ASM bits (asm_errs).
        # - FEC: the soft-Viterbi + Poly1305 gate at try_decrypt is the
        #   real quality oracle. The hard-decision asm_errs at low chip
        #   SNR can exceed max_asm_errs even when the Viterbi will
        #   correct the body, and the pilot fit's rms is also noisy at
        #   the operating point. Skip both gates in FEC mode and let
        #   the FEC + crypto layer reject bad copies after combining.
        if not self.fec:
            if rms is None or rms > self.pass_rms:
                return False
            if asm_errs is None or asm_errs > self.max_asm_errs:
                return False

        # Polarity vote: correlate this copy's first-32 LLRs against the
        # signed ASM pattern. Positive → matches normal; negative →
        # matches inverted. 32-dimensional coherent vote is effectively
        # noise-free at any SNR the decoder can reach. In FEC mode the
        # first 32 channel LLRs are still the uncoded ASM, so the same
        # polarity logic applies regardless of mode.
        llrs_f64 = llrs[:self.n_bits].astype(np.float64)
        polarity_vote = float(np.dot(llrs_f64[:32], self._asm_signs))
        sign = 1.0 if polarity_vote >= 0 else -1.0
        # In FEC mode, drop the uncoded header and accumulate only the
        # coded body LLRs. In normal mode, accumulate the entire frame.
        if self.fec:
            body_llrs = llrs_f64[self._header_bits:]
            self.accumulated += sign * body_llrs
        else:
            self.accumulated += sign * llrs_f64
        self.n_copies += 1
        if self.n_copies >= self.max_copies:
            # Exponential forgetting: halve the accumulator when full.
            # Only reachable with very long-running accumulation; in the
            # default config of 64 this is effectively never hit.
            self.accumulated *= 0.5
            self.n_copies //= 2
        return True

    def current_frame(self) -> Optional[bytes]:
        """Hard-decide the accumulated LLRs into HAIL_FRAME_LEN bytes."""
        if self.n_copies == 0:
            return None
        bits = (self.accumulated < 0).astype(np.uint8)
        return np.packbits(bits).tobytes()

    def try_decrypt(
        self,
        responder_static,
    ) -> Optional[tuple[object, str, int]]:
        """Attempt to decrypt the accumulated frame.

        In FEC mode: soft-Viterbi-decode the accumulated body LLRs into
        payload bits, reconstruct the standard 133-byte hail frame using
        the known uncoded header, and run the existing decode_hail
        pipeline. The convolutional code does the soft-decision work, so
        Chase-II is not needed.

        In normal mode: hard-decide the accumulated LLRs, then run the
        existing 6-XOR + Chase-II decrypt pipeline used for single
        copies.

        Returns (decoded_hail, polarity_label, chase_flips) or None.
        """
        if self.n_copies == 0:
            return None

        if self.fec:
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

        frame = self.current_frame()
        if frame is None:
            return None
        def _xor_alt(b: bytes, even_mask: int, odd_mask: int) -> bytes:
            o = bytearray(len(b))
            for i, x in enumerate(b):
                o[i] = x ^ (even_mask if i % 2 == 0 else odd_mask)
            return bytes(o)
        candidates = [
            ("acc", frame),
            ("acc-inv", bytes(x ^ 0xFF for x in frame)),
            ("acc-alt", bytes(x ^ 0xAA for x in frame)),
            ("acc-alt2", bytes(x ^ 0x55 for x in frame)),
            ("acc-alt-inv", _xor_alt(frame, 0x55, 0xAA)),
            ("acc-alt2-inv", _xor_alt(frame, 0xAA, 0x55)),
        ]
        for label, candidate in candidates:
            decoded = sc.decode_hail(candidate, responder_static)
            if decoded is not None:
                return decoded, label, 0
        # Chase-II on accumulated soft values
        soft_sym = self.accumulated.astype(np.float32)
        chase = _chase_decrypt_body(
            frame, soft_sym, responder_static, k=12,
        )
        if chase is not None:
            decoded, n_flips = chase
            return decoded, f"acc-chase{n_flips}", n_flips
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


def find_sisl_frame_best_match(
    decoded_bytes: bytes,
    frame_len: int = sc.HAIL_FRAME_LEN,
) -> Optional[tuple[int, bytes, int]]:
    """Find the lowest-Hamming-distance ASM match in a decoded bit stream.

    Unlike `find_sisl_frame_bitwise_fuzzy`, this always returns the BEST
    match regardless of distance threshold. The caller decides whether
    the distance is acceptable. Useful for diagnostic reporting: even
    when the ASM can't be found within decode tolerance, we want to
    know how close we are.

    Returns (bit_offset, frame_bytes, asm_distance). frame_bytes is
    frame_len bytes extracted starting at the best-match bit offset.
    """
    n_frame_bits = frame_len * 8
    if len(decoded_bytes) * 8 < n_frame_bits + 32:
        return None

    bits = np.unpackbits(np.frombuffer(decoded_bytes, dtype=np.uint8))
    max_bit_offset = len(bits) - n_frame_bits
    if max_bit_offset <= 0:
        return None

    asm_len = len(_ASM_BITS)
    best_distance = asm_len + 1
    best_offset = -1

    for bit_start in range(max_bit_offset + 1):
        window = bits[bit_start:bit_start + asm_len]
        distance = int(np.sum(window ^ _ASM_BITS))
        if distance < best_distance:
            best_distance = distance
            best_offset = bit_start
            if distance == 0:
                break

    if best_offset < 0:
        return None

    frame_bits = bits[best_offset:best_offset + n_frame_bits]
    frame_bytes = np.packbits(frame_bits).tobytes()
    return best_offset, frame_bytes, best_distance


def find_sisl_frame_bitwise_fuzzy(
    decoded_bytes: bytes,
    frame_len: int = sc.HAIL_FRAME_LEN,
    max_errors: int = 5,
) -> Optional[tuple[int, bytes, int]]:
    """Fuzzy ASM search with a max-errors threshold.

    Scans every bit offset, computes the Hamming distance to the 32-bit
    ASM, and returns the best match only if within `max_errors`.

    False positive rates (per offset, vs random 32-bit):
      ≤ 3 errors → ≈ 5489 / 2³² ≈ 1.3 × 10⁻⁶
      ≤ 4 errors → ≈ 41449 / 2³² ≈ 9.6 × 10⁻⁶
      ≤ 5 errors → ≈ 242825 / 2³² ≈ 5.7 × 10⁻⁵
    Over ~2000 bit offsets per block, tolerance 5 gives ~11 % block
    FP rate — but the periodicity pre-filter already rejects noise
    blocks, so the effective pipeline FP is <0.5 %.

    Default tolerance bumped from 3 to 5 to catch frames with higher
    bit error rates. Real frames at marginal SNR commonly sit at
    4-6 Hamming distance from the true ASM.

    Returns (bit_offset, frame_bytes, asm_distance) or None.
    """
    best = find_sisl_frame_best_match(decoded_bytes, frame_len)
    if best is None:
        return None
    bit_offset, frame_bytes, best_distance = best
    if best_distance > max_errors:
        return None
    return bit_offset, frame_bytes, best_distance


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


def _try_coherent_decrypt_at_position(
    peak_values: list,
    soft_offset: int,
    responder_static: ec.EllipticCurvePrivateKey,
) -> Optional[dict]:
    """Run the coherent decode + 6 XOR candidates + Chase-II at one ASM position.

    Returns a dict with keys (decoded_hail, polarity, theta0, delta,
    phase_rms, asm_errs, c_frame, c_soft, chase_flips) on decrypt success,
    or a dict with decoded_hail=None and the diagnostic fields on failure.
    """
    aligned_peaks = peak_values[soft_offset:]
    n_frame_bits = sc.HAIL_FRAME_LEN * 8
    n_fec_bits = sc.HAIL_FEC_TOTAL_BITS
    n_pilot_bits = len(_PILOT_BITS)     # 48: ASM + ver + type
    out = {
        "decoded_hail": None,
        "polarity": None,
        "theta0_rad": None,
        "delta_theta_per_sym": None,
        "phase_rms_residual_rad": None,
        "asm_errs_in_coherent": None,
        "c_frame": None,
        "c_soft": None,
        "fec_llrs": None,
        "chase_flips": None,
    }
    if len(aligned_peaks) < n_pilot_bits:
        # Not even enough peaks for the extended pilot fit.
        return out

    # Always run the 48-bit pilot fit first — it's fast and gives us
    # phase_rms regardless of whether a full frame decode is possible.
    fit_diag = sf.fit_phase_from_known_bits(
        aligned_peaks, 0, _PILOT_BITS)
    if fit_diag is not None:
        out["theta0_rad"] = fit_diag[0]
        out["delta_theta_per_sym"] = fit_diag[1]
        out["phase_rms_residual_rad"] = fit_diag[2]

    if len(aligned_peaks) < n_frame_bits:
        # Truncated: can't decode a full frame. The pilot-fit diagnostics
        # are still useful (phase_rms tells us if the ASM lock is real
        # or spurious).
        return out

    # Decode at the FEC channel length when peaks allow, so we can
    # populate both the legacy 'c_soft' (1064 frame LLRs) and the
    # longer 'fec_llrs' (2096 channel LLRs) from one call.
    decode_len = n_fec_bits if len(aligned_peaks) >= n_fec_bits else n_frame_bits
    coherent = sf.coherent_decode_from_pilot(
        aligned_peaks, 0, _PILOT_BITS, decode_len,
    )
    if coherent is None:
        return out
    c_frame_full, c_soft_full, c_theta0, c_delta, c_rms = coherent
    c_frame = c_frame_full[: sc.HAIL_FRAME_LEN]
    c_soft = c_soft_full[: n_frame_bits]
    out["c_frame"] = c_frame
    out["c_soft"] = c_soft
    if decode_len >= n_fec_bits:
        out["fec_llrs"] = c_soft_full[: n_fec_bits]
    out["theta0_rad"] = c_theta0
    out["delta_theta_per_sym"] = c_delta
    out["phase_rms_residual_rad"] = c_rms

    # How many of the first 32 decoded bits match the ASM? >8 wrong means
    # the linear fit hit the ±π/symbol boundary in the (now-ML) search
    # and landed on a secondary peak. Primary peak should give 0 errors.
    c_bits_first32 = np.unpackbits(
        np.frombuffer(c_frame[:4], dtype=np.uint8))
    c_asm_errs = int(np.sum(c_bits_first32 != _ASM_BITS))
    out["asm_errs_in_coherent"] = c_asm_errs

    def _xor_alt(b: bytes, even_mask: int, odd_mask: int) -> bytes:
        o = bytearray(len(b))
        for i, x in enumerate(b):
            o[i] = x ^ (even_mask if i % 2 == 0 else odd_mask)
        return bytes(o)
    candidates = [
        ("coherent", c_frame),
        ("coherent-inv", bytes(x ^ 0xFF for x in c_frame)),
        ("coherent-alt", bytes(x ^ 0xAA for x in c_frame)),
        ("coherent-alt2", bytes(x ^ 0x55 for x in c_frame)),
        ("coherent-alt-inv", _xor_alt(c_frame, 0x55, 0xAA)),
        ("coherent-alt2-inv", _xor_alt(c_frame, 0xAA, 0x55)),
    ]
    for label, candidate in candidates:
        decoded_hail = sc.decode_hail(candidate, responder_static)
        if decoded_hail is not None:
            out["decoded_hail"] = decoded_hail
            out["polarity"] = label
            return out

    # Chase-II on the base coherent frame if the fit is clean.
    if c_asm_errs <= 2 and c_soft is not None:
        chase = _chase_decrypt_body(
            c_frame, c_soft, responder_static, k=12,
        )
        if chase is not None:
            decoded_hail, n_flips = chase
            out["decoded_hail"] = decoded_hail
            out["polarity"] = f"coherent-chase{n_flips}"
            out["chase_flips"] = n_flips
    return out


def _decode_one_hail_in_block(
    samples: np.ndarray,
    responder_static: ec.EllipticCurvePrivateKey,
    samps_per_chip: int = SAMPS_PER_CHIP,
    samp_hz: float = SAMP_RATE_HZ,
    signal_threshold: float = _SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
    fec: bool = False,
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
    # In FEC mode we need enough peak_values to cover BOTH a full FEC
    # frame (HAIL_FEC_TOTAL_BITS = 2096) AND a search window of at
    # least one frame's worth, since the soft-correlator's strongest
    # ASM hit may land near the end of the first frame in the stream.
    # Without the search margin we'd find an ASM at offset ~1500 with
    # only ~600 peaks left after it — far less than the FEC frame
    # length — and the FEC fast path would discard the candidate.
    #
    # Target the largest symbol count that fits in the input block.
    # samples_per_symbol = CHIPS_PER_SYMBOL * samps_per_chip. We
    # subtract a small safety margin to leave room for the per-symbol
    # tracker's per-step bracket search.
    if fec:
        # The soft correlator needs to find the ASM anywhere within the
        # first 2096 tracked peaks AND still have 2096 peaks remaining
        # after the offset. That requires 2 × HAIL_FEC_TOTAL_BITS =
        # 4192 bits = 524 bytes of tracked symbols minimum.
        target_bytes = (2 * sc.HAIL_FEC_TOTAL_BITS + 7) // 8   # 524
    else:
        target_bytes = 2 * sc.HAIL_FRAME_LEN
    track_result = sf.decode_with_freq_tracking(
        samples,
        samps_per_chip=samps_per_chip,
        n_bytes=target_bytes,
        freq_offset_rad_per_sample=rad_per_sample,
    )
    if track_result is None:
        # Fall back to a smaller window. In FEC mode try the minimum
        # FEC frame length; in non-FEC mode try the legacy 1-frame
        # length.
        fallback_bytes = (
            (sc.HAIL_FEC_TOTAL_BITS + 7) // 8
            if fec
            else sc.HAIL_FRAME_LEN
        )
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
    decoded = track_result["bytes"]
    positions = track_result["positions"]
    peak_values = track_result.get("peak_values", [])

    # ── 5b. FEC fast path ─────────────────────────────────────────────
    # In FEC mode the on-air frame is 2096 channel bits, not 1064. The
    # tracker's peak_values[0] is the global argmax of the matched
    # filter — typically NOT the start of an ASM frame. We must find
    # the actual ASM offset first via the soft-correlator search, then
    # call dbpsk_decode_from_pilot at that offset. Without this step,
    # the pilot fit interprets random body bits as the known pilot and
    # produces garbage LLRs.
    if fec:
        if not peak_values or len(peak_values) < sc.HAIL_FEC_TOTAL_BITS:
            return {
                "status": "track_lost",
                "peak_mag": peak_mag,
                "median_mag": median_mag,
                "rad_per_sample": rad_per_sample,
                "freq_offset_hz": freq_hz,
                "note": "fec mode: peak_values too short for HAIL_FEC_TOTAL_BITS",
            }

        # Soft-correlator search for the ASM offset. The same function
        # the non-FEC path uses, just with the longer FEC frame length.
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
            # Need HAIL_FEC_TOTAL_BITS peaks starting at this offset.
            if cand_offset + sc.HAIL_FEC_TOTAL_BITS > len(peak_values):
                continue
            # Two-stage gate matching the non-FEC path:
            #   absolute soft-score threshold + peak-to-sidelobe ratio.
            if abs(cand_score) <= 10.0 or cand_pts < 3.0:
                continue

            llr_diag = _extract_llrs_at_position(peak_values, int(cand_offset))
            fec_llrs_arr = llr_diag.get("fec_llrs")
            if fec_llrs_arr is None:
                continue

            # Try the FEC decrypt at this offset.
            attempt = sc.decode_hail_fec_from_llrs(fec_llrs_arr, responder_static)
            if attempt is None:
                # Try inverted polarity in case of BPSK 180° flip
                # (DBPSK is locally invariant but the pilot fit can
                # land on +π or -π depending on which side the noise
                # pushes the angle estimator).
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
                best_attempt = {
                    "llr_diag": llr_diag,
                    "fec_llrs": fec_llrs_arr,
                }
                break  # success — stop searching

            # Remember the highest-score failed attempt for diagnostics
            if best_attempt is None:
                best_attempt = {
                    "llr_diag": llr_diag,
                    "fec_llrs": fec_llrs_arr,
                }
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
                "note": "fec mode: no soft-correlator candidate cleared the gate",
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
            return {
                "status": "decrypt_fail",
                "polarity": "fec",
                **base,
            }
        return {
            "status": "decrypt_ok",
            "polarity": polarity_label,
            "body": decoded_hail.body,
            "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
            **base,
        }

    # ── 3. Try both bit polarities (BPSK phase ambiguity) ────────────────
    decoded_inv = bytes(b ^ 0xFF for b in decoded)
    # Track the best fuzzy match across both polarities so we can at least
    # REPORT the ASM hamming distance even if exact/fuzzy decrypt fails.
    best_fuzzy = None        # (polarity, bit_offset, frame_bytes, distance)
    for variant_label, variant in (("normal", decoded), ("inverted", decoded_inv)):
        # ── First: byte-aligned ASM search (fast, common case) ─────
        info = identify_sisl_frame(variant)
        frame_bytes = None
        asm_location = None
        peak_offset: Optional[int] = None
        if info is not None and info["frame_type"] == "hail" and info["frame_bytes"] is not None:
            frame_bytes = info["frame_bytes"]
            asm_location = f"byte{info['asm_offset']}"
            peak_offset = int(info["asm_offset"]) * 8

        # ── Fallback 1: bit-level exact sliding ASM search ─────────
        if frame_bytes is None:
            bitwise = find_sisl_frame_bitwise(variant, sc.HAIL_FRAME_LEN)
            if bitwise is not None:
                bit_offset, frame_bytes = bitwise
                asm_location = f"bit{bit_offset}"
                peak_offset = int(bit_offset)

        # ── Fallback 2: fuzzy bit-level ASM search ─────────────────
        if frame_bytes is None:
            fuzzy = find_sisl_frame_bitwise_fuzzy(
                variant, sc.HAIL_FRAME_LEN, max_errors=5,
            )
            if fuzzy is not None:
                bit_offset, fuzzy_bytes, asm_distance = fuzzy
                if best_fuzzy is None or asm_distance < best_fuzzy[3]:
                    best_fuzzy = (variant_label, bit_offset, fuzzy_bytes,
                                   asm_distance)

        if frame_bytes is None:
            continue

        # Always extract LLRs at the discovered ASM offset so the
        # accumulator can chase-combine across blocks regardless of the
        # current block's decrypt outcome (A5).
        llr_diag = (
            _extract_llrs_at_position(peak_values, peak_offset)
            if peak_offset is not None and peak_values
            else {"llrs": None, "fec_llrs": None, "c_frame": None,
                  "phase_rms_residual_rad": None, "asm_errs_in_coherent": None}
        )

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
                "llrs": llr_diag["llrs"],
                "fec_llrs": llr_diag["fec_llrs"],
                "c_frame": llr_diag["c_frame"],
                "phase_rms_residual_rad": llr_diag["phase_rms_residual_rad"],
                "asm_errs_in_coherent": llr_diag["asm_errs_in_coherent"],
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
            "llrs": llr_diag["llrs"],
            "fec_llrs": llr_diag["fec_llrs"],
            "c_frame": llr_diag["c_frame"],
            "phase_rms_residual_rad": llr_diag["phase_rms_residual_rad"],
            "asm_errs_in_coherent": llr_diag["asm_errs_in_coherent"],
        }

    # ── Fallback 3: top-K soft-decision ASM search ───────────────
    # Per Gallager's panel feedback: hard-decision decoding throws away
    # 10-15 dB of effective SNR. Run the soft correlator directly on
    # the complex peak values and inspect the top-K candidate ASM
    # positions, not just the argmax. At marginal SNR the true ASM may
    # be at the 2nd or 3rd strongest position while noise wins the top.
    soft_result = None
    best_attempt = None          # dict returned by _try_coherent_decrypt_at_position
    best_soft_score = 0.0
    best_soft_offset = -1
    best_soft_frame = None
    best_pts_ratio = None
    if peak_values and len(peak_values) >= 33 and top_k_soft > 0:
        topk = find_sisl_frame_soft_topk(
            peak_values, sc.HAIL_FRAME_LEN, k=top_k_soft,
        )
        if topk:
            soft_offset, soft_score, soft_frame, pts_ratio = topk[0]
            soft_result = (soft_offset, soft_score, soft_frame)
            best_soft_score = soft_score
            best_soft_offset = soft_offset
            best_soft_frame = soft_frame
            best_pts_ratio = pts_ratio

            # Walk top-K candidates in order of |score|.
            for cand_offset, cand_score, cand_frame, cand_pts in topk:
                # Two-stage gate:
                #   (a) absolute soft-score threshold  — rejects small peaks
                #   (b) peak-to-sidelobe ratio         — rejects
                #       candidates whose score isn't clearly above the
                #       noise floor of all other positions.
                # Clean signal: pts_ratio > 5. Noise: ~2–3. Require ≥ 3.
                if abs(cand_score) <= 10.0 or cand_pts < 3.0:
                    continue   # below threshold, don't waste coherent decode
                # First try the differential soft frame directly.
                decoded_hail = sc.decode_hail(cand_frame, responder_static)
                if decoded_hail is not None:
                    # Extract LLRs at this offset for chase combining (A5).
                    llr_diag = _extract_llrs_at_position(peak_values, int(cand_offset))
                    return {
                        "status": "decrypt_ok",
                        "start_sample": positions[0] if positions else 0,
                        "asm_at_byte": f"soft-bit{cand_offset}",
                        "peak_mag": peak_mag,
                        "median_mag": median_mag,
                        "polarity": "soft" if cand_score >= 0 else "soft-inv",
                        "rad_per_sample": rad_per_sample,
                        "freq_offset_hz": freq_hz,
                        "soft_score": cand_score,
                        "pts_ratio": cand_pts,
                        "body": decoded_hail.body,
                        "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
                        "llrs": llr_diag["llrs"],
                        "fec_llrs": llr_diag["fec_llrs"],
                        "c_frame": llr_diag["c_frame"],
                        "phase_rms_residual_rad": llr_diag["phase_rms_residual_rad"],
                        "asm_errs_in_coherent": llr_diag["asm_errs_in_coherent"],
                    }
                # Then try the coherent + chase pipeline.
                attempt = _try_coherent_decrypt_at_position(
                    peak_values, cand_offset, responder_static,
                )
                if attempt["decoded_hail"] is not None:
                    decoded_hail = attempt["decoded_hail"]
                    return {
                        "status": "decrypt_ok",
                        "start_sample": positions[0] if positions else 0,
                        "asm_at_byte": f"{attempt['polarity']}-bit{cand_offset}",
                        "peak_mag": peak_mag,
                        "median_mag": median_mag,
                        "polarity": attempt["polarity"],
                        "rad_per_sample": rad_per_sample,
                        "freq_offset_hz": freq_hz,
                        "soft_score": cand_score,
                        "pts_ratio": cand_pts,
                        "theta0_rad": attempt["theta0_rad"],
                        "delta_theta_per_sym": attempt["delta_theta_per_sym"],
                        "phase_rms_residual_rad": attempt["phase_rms_residual_rad"],
                        "asm_errs_in_coherent": attempt["asm_errs_in_coherent"],
                        "chase_flips": attempt["chase_flips"],
                        "body": decoded_hail.body,
                        "caller_eph_pub_canonical": decoded_hail.caller_eph_pub_canonical,
                        # A5: surface LLRs from the coherent attempt so the
                        # accumulator can chase-combine across blocks even
                        # when the current block decrypted successfully.
                        "llrs": attempt["c_soft"],
                        "fec_llrs": attempt["fec_llrs"],
                        "c_frame": attempt["c_frame"],
                    }
                # Remember the best (highest |score|) failed attempt for
                # the frame_soft / noise_lock diagnostic below. The first
                # candidate is always the highest |score|, so only take
                # the first failed one.
                if best_attempt is None:
                    best_attempt = attempt
                    best_soft_score = cand_score
                    best_soft_offset = cand_offset
                    best_soft_frame = cand_frame
                    best_pts_ratio = cand_pts

    if best_attempt is not None:
        # None of the top-K candidates decrypted. Use the best failed
        # attempt (highest |soft_score|) for the diagnostic report.
        c_rms = best_attempt["phase_rms_residual_rad"]
        c_asm_errs = best_attempt["asm_errs_in_coherent"]
        c_frame = best_attempt["c_frame"]
        c_soft_llrs = best_attempt["c_soft"]
        coherent_hex = (c_frame[:16].hex()
                         if c_frame is not None else None)
        # Noise rejection. Two sufficient conditions for "this is
        # spurious interference, not a SISL frame":
        #   (a) phase_rms > 1.5 rad — the ML pilot fit could not find
        #       a coherent phase trajectory across the 48 known bits;
        #       essentially noise. This is a hard reject.
        #   (b) phase_rms > 0.9 rad AND asm_errs > 4 — marginal fit
        #       and wrong bits in the decoded ASM region; also noise.
        # Case (b) kept for belt-and-suspenders but (a) handles the
        # truncated-frame case where c_asm_errs is None.
        is_noise = False
        if c_rms is not None and c_rms > 1.5:
            is_noise = True
        elif (c_rms is not None and c_rms > 0.9
              and c_asm_errs is not None and c_asm_errs > 4):
            is_noise = True
        status = "noise_lock" if is_noise else "frame_soft"
        return {
            "status": status,
            "start_sample": positions[0] if positions else 0,
            "asm_at_bit": best_soft_offset,
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "polarity": "soft" if best_soft_score >= 0 else "soft-inv",
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "soft_score": best_soft_score,
            "pts_ratio": best_pts_ratio,
            "first_16_bytes_hex": (best_soft_frame[:16].hex()
                                    if best_soft_frame is not None else ""),
            "coherent_16_bytes_hex": coherent_hex,
            "asm_errs_in_coherent": c_asm_errs,
            "drift_per_symbol_rad": track_result.get(
                "drift_per_symbol_rad", 0.0),
            "theta0_rad": best_attempt["theta0_rad"],
            "delta_theta_per_sym": best_attempt["delta_theta_per_sym"],
            "phase_rms_residual_rad": c_rms,
            # D1: LLRs surfaced for accumulator / downstream decoders.
            # For frame_soft and noise_lock, we still publish the soft
            # values so callers can chase-combine across blocks. Shape is
            # (HAIL_FRAME_LEN*8,) float32, positive → bit 0, negative → bit 1.
            "llrs": c_soft_llrs,
            "c_frame": best_attempt["c_frame"],
        }

    # ── Neither polarity has an exact ASM, but we may have a fuzzy match
    # If so, return a diagnostic status showing the decoder found the
    # frame with some bit errors. This proves the demodulator is
    # working even when we can't fully decrypt.
    if best_fuzzy is not None:
        polarity_label, fuzzy_bit_offset, fuzzy_frame, fuzzy_dist = best_fuzzy
        return {
            "status": "frame_fuzzy",
            "peak_mag": peak_mag,
            "median_mag": median_mag,
            "start_sample": positions[0] if positions else 0,
            "rad_per_sample": rad_per_sample,
            "freq_offset_hz": freq_hz,
            "polarity": polarity_label,
            "asm_distance": fuzzy_dist,
            "asm_at_byte": f"bit{fuzzy_bit_offset}",
            "first_16_bytes_hex": fuzzy_frame[:16].hex(),
            "drift_per_symbol_rad": track_result.get("drift_per_symbol_rad", 0.0),
        }

    # Neither polarity contains a SISL ASM — either interference or
    # drift/noise corrupted the bits beyond recognition.
    # Report the BEST hamming distance found across both polarities,
    # even though it's above our fuzzy tolerance. This is a direct
    # measure of how close we are to a successful decode.
    best_normal = find_sisl_frame_best_match(decoded, sc.HAIL_FRAME_LEN)
    best_inverted = find_sisl_frame_best_match(decoded_inv, sc.HAIL_FRAME_LEN)
    min_hamming_normal = best_normal[2] if best_normal else None
    min_hamming_inverted = best_inverted[2] if best_inverted else None
    soft_score_val = soft_result[1] if soft_result else None
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
        "min_asm_hamming_normal": min_hamming_normal,
        "min_asm_hamming_inverted": min_hamming_inverted,
        "soft_score": soft_score_val,
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
    fec: bool = False,
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
        if fec:
            accumulator = LlrAccumulator(
                n_bits=sc.HAIL_FEC_TOTAL_BITS,
                max_copies=combine_copies,
                fec=True,
            )
        else:
            accumulator = LlrAccumulator(
                n_bits=sc.HAIL_FRAME_LEN * 8,
                pass_rms=0.3,           # only clean coherent fits
                max_copies=combine_copies,
            )

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
                fec=fec,
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

            # D4: LLR chase-combining. Try to fold the current block into
            # the accumulator and re-attempt decrypt on the sum. This runs
            # only for clean-fit blocks (accumulator has strict pass_rms).
            if accumulator is not None:
                added = accumulator.try_add(result)
                if added:
                    stats["combined_copies"] += 1
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
    max_search_chips: Optional[int] = None,
    fec: bool = False,
) -> dict:
    """Full pipeline: capture → despread → detect hail → trial decrypt.

    Returns a dict with:
        offset            — acquisition chip offset (None if no lock)
        decoded_bytes     — raw despread bytes
        frame             — identify_sisl_frame() result or None
        decoded_hail      — sisl_crypto.DecodedHail or None
        decrypted         — True iff the hail was for `responder_static`
        responder_label   — diagnostic string ("demo-responder", etc.)

    `fec`: when True, route the entire capture through
    _decode_one_hail_in_block(fec=True), which extracts 2096 channel
    LLRs and runs sisl_fec.decode + decode_hail_fec_from_llrs.
    """
    if responder_static is None:
        responder_static = demo_responder_key()

    if fec:
        raw = np.fromfile(cfile_path, dtype=np.complex64)
        decode_result = _decode_one_hail_in_block(
            raw, responder_static, fec=True,
        )
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
            out["decoded_hail"] = type("X", (), {  # tiny duck-type for callers
                "body": decode_result["body"],
                "caller_eph_pub_canonical":
                    decode_result["caller_eph_pub_canonical"],
            })()
            out["decrypted"] = True
        return out

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
    parser.add_argument("--fec", action="store_true",
                        help="use the FEC-encoded hail variant. TX side "
                             "emits a 2096-bit channel waveform "
                             "(48 uncoded header + 2048 FEC body, ~2x "
                             "the air time of an uncoded hail). RX side "
                             "extracts 2096 channel LLRs, runs the soft "
                             "Viterbi over the FEC body, and decrypts "
                             "via decode_hail_fec_from_llrs. Combine "
                             "with --combine N to chase-combine FEC "
                             "frames across copies for the full ~5 dB "
                             "(N=1) to ~13 dB (N=10) deeper-into-noise "
                             "operating point.")
    args = parser.parse_args()

    if args.mode == "tx-to-file":
        frame = build_demo_hail()
        n = tx_to_file(frame, args.capture,
                       prefix_ms=args.prefix_ms, repeats=args.repeats,
                       fec=args.fec)
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
            fec=args.fec,
        )

        if args.fec:
            print(f"FEC decode:    status={result.get('fec_status')!r}, "
                  f"polarity={result.get('fec_polarity')!r}")
            decoded_hail = result["decoded_hail"]
            if decoded_hail is None:
                print("TRIAL DECRYPT: FAILED (FEC body decoded but Poly1305 "
                      "rejected — likely phase-drift wrap in the back half "
                      "of the 2096-bit codeword; needs DBPSK in production)")
                return 1
            body = decoded_hail.body
            print("TRIAL DECRYPT: OK (this hail was for us)")
            print(f"  center_freq_offset: +{body.center_freq_offset} MHz")
            print(f"  bandwidth_code:     0x{body.bandwidth_code:02x}")
            print(f"  mode:               0x{body.mode:02x}")
            print(f"  body_nonce:         {body.body_nonce.hex()}")
            return 0

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
        block_sec = args.block_seconds
        if args.fec and block_sec < 5.0:
            print(f"  WARNING: --fec requires --block-seconds >= 5.0 "
                  f"(FEC frame is 2096 symbols at ~1 ksym/s = 2.1s; "
                  f"tracker needs 2× for search = 4.2s + margin). "
                  f"Overriding {block_sec}s → 6.0s.")
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
            fec=args.fec,
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
        print(f"  noise locks:     {stats.get('noise_locks', 0)} "
              "(spurious soft-correlator triggers, rejected)")
        print(f"  soft detected:   {stats.get('frames_soft', 0)} "
              "(soft correlator found ASM, body noisy)")
        print(f"  fuzzy matches:   {stats.get('frames_fuzzy', 0)} "
              "(ASM found with 1-3 bit errors, too noisy to decrypt)")
        print(f"  hails detected:  {stats['hails_detected']} "
              "(SISL frame parsed)")
        print(f"  hails decrypted: {stats['hails_decrypted']} "
              "(Poly1305 verified)")
        if stats.get("combined_copies", 0) or stats.get("combined_decrypts", 0):
            print(f"  combined copies: {stats.get('combined_copies', 0)} "
                  "(clean-fit copies fed into LLR accumulator)")
            print(f"  combined decrypt:{stats.get('combined_decrypts', 0)} "
                  "(rescued by chase-combining)")
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
        fec=args.fec,
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
        if args.fec:
            print(f"tx: transmitting FEC demo hail to {args.freq:.1f} MHz "
                  f"for {args.duration:.1f} s")
            print(f"  on-air:        {sc.HAIL_FEC_TOTAL_BITS} channel bits "
                  f"(48 uncoded header + 2048 FEC body)")
            print(f"  underlying:    {len(frame)}-byte hail frame, FEC-encoded")
        else:
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
