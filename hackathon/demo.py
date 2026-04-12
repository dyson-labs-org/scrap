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
    python hackathon/demo.py --mode tx       # tx a demo hail forever
    python hackathon/demo.py --mode rx       # capture samples to /tmp/sisl_rx.cfile
    python hackathon/demo.py --mode offline  # decode and decrypt a capture

Requires:
    gnuradio (tested on 3.10+)
    gr-soapy or gr-osmosdr for HackRF access
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import os
import platform
import sys
import time
from types import SimpleNamespace

import numpy as np

from cryptography.hazmat.primitives.asymmetric import ec

import sisl_crypto as sc
import sisl_fec
import sisl_rx

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


_IS_WINDOWS = platform.system() == "Windows"

# ── Demo parameters ─────────────────────────────────────────────────────────

CENTER_FREQ_HZ = 2_437_000_000          # default: WiFi ch 6 (may be noisy!)
CHIP_RATE_HZ = 1_000_000                # 1 Mcps — fixed across devices
SAMP_RATE_HZ = 8_000_000                # 8 Msps (HackRF default)
SAMPS_PER_CHIP = SAMP_RATE_HZ // CHIP_RATE_HZ    # 8 — integer
HACKRF_TX_VGA_DB = 0                    # TX IF gain, 0..47 dB. Default = min.
HACKRF_TX_AMP_ON = False                # TX RF PA (14 dB). Off by default.
HACKRF_RX_VGA_DB = 40                   # HackRF NF is ~10-12 dB; needs more
HACKRF_RX_LNA_DB = 40                   # gain than RTL-SDR to compensate


# ── Per-device RX configuration ────────────────────────────────────────────
#
# The HackRF and RTL-SDR families have very different sample rate grids
# and frequency ranges. The TX path is HackRF-only (RTL-SDR is RX-only
# hardware); the RX path can use either.

from sdr_devices import (
    DeviceInfo, DEVICES, PLUGIN_INSTALL_HINTS as _PLUGIN_INSTALL_HINTS,
    format_device_open_error as _format_device_open_error,
    get_device_ppm as _get_device_ppm,
)


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


# ── SoapySDR TX burst (for ACK, no GnuRadio) ────────────────────────────────

def soapy_tx_burst(
    samples: np.ndarray,
    center_hz: float,
    samp_hz: float = SAMP_RATE_HZ,
    tx_vga_db: int = HACKRF_TX_VGA_DB,
    tx_amp_on: bool = HACKRF_TX_AMP_ON,
    repeats: int = 1,
) -> None:
    """Transmit a finite sample buffer via SoapySDR (no GnuRadio).

    Opens a HackRF for TX, writes the samples `repeats` times, then
    closes. Used for ACK transmission in the listen-after-talk handshake.
    """
    import SoapySDR
    from SoapySDR import SOAPY_SDR_TX, SOAPY_SDR_CF32

    device = SoapySDR.Device("driver=hackrf")
    device.setSampleRate(SOAPY_SDR_TX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_TX, 0, center_hz)
    device.setGain(SOAPY_SDR_TX, 0, "VGA", float(tx_vga_db))
    device.setGain(SOAPY_SDR_TX, 0, "AMP", 14.0 if tx_amp_on else 0.0)

    stream = device.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
    device.activateStream(stream)

    full = np.tile(samples, repeats) if repeats > 1 else samples
    offset = 0
    chunk = 65536
    while offset < len(full):
        end = min(offset + chunk, len(full))
        sr = device.writeStream(stream, [full[offset:end]], end - offset,
                                timeoutUs=1_000_000)
        if sr.ret > 0:
            offset += sr.ret
        elif sr.ret == -1:  # timeout
            continue
        else:
            break

    device.deactivateStream(stream)
    device.closeStream(stream)


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
                     samps_per_chip: int = SAMPS_PER_CHIP):
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
                    frame = sc.ASM
                    self.hail_frame = frame
                    chips = sf.tx_bytes_to_chips(frame)
                else:
                    # FEC TX path: encode_hail_fec produces a 2096-bit
                    # channel array (48 uncoded header + 2048 FEC body).
                    chips, frame = build_demo_hail_fec_chips()
                    self.hail_frame = frame
                # Repeat the hail indefinitely so the RX can lock at any time
                samples = upsample_chips_to_samples(chips, samps_per_chip)
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
    chips = sf.tx_bytes_to_chips(message)
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







import queue as _queue
import threading


def _usb_reader_thread(
    device,
    stream,
    block_samples: int,
    block_queue: _queue.Queue,
    stop_event: threading.Event,
    stats: dict,
) -> None:
    """Background thread: drain SDR USB buffer into a queue of numpy blocks.

    Continuously reads samples from the SDR and enqueues full blocks for
    processing. If the main thread falls behind, the oldest queued block
    is dropped rather than blocking the reader (a blocked reader causes
    USB overflows and corrupted samples).
    """
    _is_windows = _IS_WINDOWS
    read_chunk = 32768 if _is_windows else 0

    local_buf = np.empty(block_samples, dtype=np.complex64)
    while not stop_event.is_set():
        filled = 0
        while filled < block_samples and not stop_event.is_set():
            remain = block_samples - filled
            want = min(read_chunk, remain) if read_chunk else remain
            sr = device.readStream(
                stream, [local_buf[filled:filled + want]],
                want, timeoutUs=500_000,
            )
            if sr.ret > 0:
                filled += sr.ret
            elif sr.ret == -1:
                continue
            elif sr.ret == -4:
                stats["overflows"] += 1
                continue
            else:
                break
        if filled >= block_samples // 2 and not stop_event.is_set():
            blk = local_buf[:filled].copy()
            while True:
                try:
                    block_queue.put_nowait(blk)
                    break
                except _queue.Full:
                    try:
                        block_queue.get_nowait()
                        stats["dropped_blocks"] += 1
                    except _queue.Empty:
                        break
            local_buf = np.empty(block_samples, dtype=np.complex64)
    block_queue.put(None)


class _AgcPpmState:
    """Encapsulates AGC and PPM calibration state for live RX."""

    RECAL_INTERVAL = 10.0
    SETTLED_THRESHOLD_HZ = 500.0
    AGC_TARGET = 200.0
    AGC_MIN_PEAK = 50.0
    AGC_MAX_PEAK = 400.0

    def __init__(self, device_name: str, device, center_hz: float,
                 vga_db: float, lna_db: float):
        self._device_name = device_name
        self._device = device
        self._center_hz = float(center_hz)
        self._nominal_center_hz = float(center_hz)
        self._total_correction_hz = 0.0
        self._settled = False
        self._last_recal_t = time.time()
        self._offset_history: collections.deque[float] = collections.deque(maxlen=8)
        # Suppress PPM updates for the first few blocks while the AGC
        # stabilizes. At startup the gain may be wildly wrong (too low
        # → weak signal → FFT locks onto spurs → PPM diverges; too high
        # → ADC clips → corrupted freq estimates → PPM diverges). Let
        # AGC settle for AGC_WARMUP_BLOCKS before enabling auto-PPM.
        self._agc_warmup_blocks = 3
        self._blocks_seen = 0
        self._agc_stable = False  # True once gain hasn't changed for 1 block
        self._clip_count = 0     # consecutive clipping blocks

        if device_name == "hackrf":
            self._current_vga = float(vga_db)
            self._vga_min, self._vga_max = 0.0, 62.0
        else:
            self._current_vga = max(0.0, min(49.0, float(lna_db + vga_db)))
            self._vga_min, self._vga_max = 0.0, 49.0
        self._prev_vga = self._current_vga
        # Ceiling starts at max; lowered by ADC saturation detection.
        # The proportional AGC respects this ceiling so it can't ramp
        # back into the clipping zone.
        self._vga_ceiling = self._vga_max

    def _set_rx_vga(self, gain: float) -> None:
        from SoapySDR import SOAPY_SDR_RX
        if self._device_name == "hackrf":
            self._device.setGain(SOAPY_SDR_RX, 0, "VGA", gain)
        else:
            self._device.setGain(SOAPY_SDR_RX, 0, gain)

    def on_block(self, result: dict, block_data: np.ndarray) -> None:
        """Run AGC and PPM updates after decoding one block."""
        self._blocks_seen += 1
        # AGC runs every block. PPM is suppressed until the AGC has
        # stabilized (gain unchanged for 1 block after warmup period).
        # This prevents the frequency estimator from chasing spurs
        # while the signal level is still changing.
        self._update_agc(result, block_data)
        gain_changed = (self._current_vga != self._prev_vga)
        self._prev_vga = self._current_vga
        if not self._agc_stable:
            if self._blocks_seen >= self._agc_warmup_blocks and not gain_changed:
                self._agc_stable = True
                print("       AGC stable — enabling auto-PPM")
        if self._agc_stable:
            self._update_ppm(result)

    def _update_ppm(self, result: dict) -> None:
        from SoapySDR import SOAPY_SDR_RX
        foff = result.get("freq_offset_hz")
        now = time.time()
        if foff is not None and abs(foff) > 0:
            self._offset_history.append(foff)
            do_retune = False
            if not self._settled:
                do_retune = len(self._offset_history) >= 2
            elif now - self._last_recal_t >= self.RECAL_INTERVAL:
                do_retune = True
            if do_retune and self._offset_history:
                correction = float(np.median(list(self._offset_history)[-4:]))
                self._center_hz += correction
                self._total_correction_hz += correction
                self._device.setFrequency(
                    SOAPY_SDR_RX, 0, self._center_hz)
                total_ppm = (self._total_correction_hz
                             / self._nominal_center_hz * 1e6)
                print(f"       AUTO-PPM: retune {correction:+.0f} Hz "
                      f"(total {self._total_correction_hz:+.0f} Hz / "
                      f"{total_ppm:+.1f} ppm)")
                self._offset_history.clear()
                self._last_recal_t = now
                if abs(correction) < self.SETTLED_THRESHOLD_HZ:
                    self._settled = True

    def _update_agc(self, result: dict, block_data: np.ndarray) -> None:
        sample_p99 = float(np.percentile(np.abs(block_data), 99))
        if sample_p99 > 0.9 and self._current_vga > self._vga_min:
            self._clip_count += 1
            # Only set the ceiling after 2 consecutive clipping blocks.
            # A single WiFi burst at 2.4 GHz can spike p99 > 0.9 for one
            # block without meaning the DSSS signal is too strong. Setting
            # the ceiling from a transient burst permanently caps gain
            # too low, killing the signal.
            if self._clip_count >= 2:
                reduce_db = min(6.0, max(3.0,
                                20.0 * np.log10(sample_p99 / 0.5)))
                self._current_vga = max(
                    self._vga_min, self._current_vga - reduce_db)
                self._vga_ceiling = self._current_vga
                self._set_rx_vga(self._current_vga)
                print(f"       AGC: sustained clipping (p99={sample_p99:.2f}), "
                      f"gain → {self._current_vga:.0f} dB "
                      f"(ceiling set)")
            else:
                print(f"       AGC: transient clipping (p99={sample_p99:.2f}), "
                      f"monitoring")
        else:
            self._clip_count = 0
            pk = result.get("peak_mag")
            if pk is not None and pk > 1:
                if pk < self.AGC_MIN_PEAK or pk > self.AGC_MAX_PEAK:
                    step_db = 10.0 * np.log10(self.AGC_TARGET / pk)
                    step_db = max(-6.0, min(6.0, step_db))
                    new_vga = max(self._vga_min, min(
                        self._vga_ceiling, self._current_vga + step_db))
                    if abs(new_vga - self._current_vga) >= 1.0:
                        self._current_vga = round(new_vga)
                        self._set_rx_vga(self._current_vga)
                        print(f"       AGC: peak={pk:.0f}, "
                              f"gain → {self._current_vga:.0f} dB")


def live_rx_decode(
    duration_s: float = 10.0,
    block_seconds: float = 1.5,
    responder_static: ec.EllipticCurvePrivateKey | None = None,
    save_path: str | None = None,
    lna_db: int = HACKRF_RX_LNA_DB,
    vga_db: int = HACKRF_RX_VGA_DB,
    amp_on: bool = False,
    center_hz: float = CENTER_FREQ_HZ,
    device_name: str = "hackrf",
    signal_threshold: float = sisl_rx._SIGNAL_FLOOR_RATIO,
    top_k_soft: int = 5,
    combine_copies: int = 0,
    samps_per_chip: int | None = None,
) -> dict:
    """Stream samples from the selected device, decode SISL hails live.

    `device_name` ∈ DEVICES.keys(). HackRF uses three gain stages
    (AMP/LNA/VGA); RTL-SDR has a single tuner gain, so when device_name
    is "rtlsdr" we clamp (lna_db + vga_db) into [0, 49] and apply it as
    the single gain (amp_on is ignored — RTL-SDR has no pre-tuner AMP).

    Frequency and sample-rate capabilities vary per device; we validate
    `center_hz` against the selected device's range before opening it.

    Returns a stats dict: blocks_processed, hails_detected, hails_decrypted,
    overflows, elapsed_s, ok, error.
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

    # Always use 2 samples/chip for RX — Nyquist is sufficient and
    # higher oversampling just wastes USB bandwidth and processing time.
    # At chip-rate 1 on HackRF this gives 2 Msps instead of 8 Msps:
    # 4× less data → no USB overflows, no SNR loss.
    base_chip_rate_hz = info.samp_hz // info.samps_per_chip
    if samps_per_chip is not None:
        # --chip-rate override: derive chip rate from the override
        chip_rate_hz = info.samp_hz // samps_per_chip
    else:
        chip_rate_hz = base_chip_rate_hz
    samps_per_chip = 2
    samp_hz = chip_rate_hz * samps_per_chip
    # Clamp to device limits
    samp_hz = max(2_000_000, min(info.samp_hz, samp_hz))

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

    # Auto-load calibrated PPM correction from the device serial.
    serial = ""
    try:
        hw_dict = dict(device.getHardwareInfo())
        serial = hw_dict.get("serial", "")
    except Exception:
        pass
    if not serial:
        try:
            found = SoapySDR.Device.enumerate(info.driver)
            if found:
                serial = str(dict(found[0]).get("serial", ""))
        except Exception:
            pass
    cal_ppm = _get_device_ppm(serial)
    short_serial = serial.lstrip("0") or serial
    if cal_ppm != 0.0:
        ppm_offset_hz = center_hz * cal_ppm / 1e6
        center_hz += ppm_offset_hz
        print(f"  PPM cal: device {short_serial} → {cal_ppm:+.1f} ppm "
              f"({ppm_offset_hz:+.0f} Hz)")

    device.setSampleRate(SOAPY_SDR_RX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_RX, 0, center_hz)

    if device_name == "hackrf":
        device.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if amp_on else 0.0)
        device.setGain(SOAPY_SDR_RX, 0, "LNA", float(lna_db))
        device.setGain(SOAPY_SDR_RX, 0, "VGA", float(vga_db))
        print(f"  RX gain: AMP={'on' if amp_on else 'off'} "
              f"LNA={lna_db} dB VGA={vga_db} dB")
    elif device_name == "rtlsdr":
        combined_db = max(0.0, min(49.0, float(lna_db + vga_db)))
        device.setGain(SOAPY_SDR_RX, 0, combined_db)
        print(f"  RX gain: TUNER={combined_db:.1f} dB "
              f"(from --rx-lna {lna_db} + --rx-vga {vga_db}; "
              f"clamped to [0, 49])")
        if amp_on:
            print("  NOTE: --rx-amp ignored — RTL-SDR has no AMP stage")
    else:
        raise ValueError(f"unhandled device {device_name}")

    stream_args = {"bufflen": "262144", "buffers": "8"}
    stream = device.setupStream(
        SOAPY_SDR_RX, SOAPY_SDR_CF32, [0], stream_args)
    device.activateStream(stream)

    _is_windows = _IS_WINDOWS
    _win_timer_set = False
    if _is_windows:
        try:
            import ctypes
            ctypes.windll.winmm.timeBeginPeriod(1)  # type: ignore[attr-defined]
            _win_timer_set = True
        except Exception:
            pass

    save_file = open(save_path, "wb") if save_path else None
    block_samples = int(block_seconds * samp_hz)

    stats: dict = {
        "ok": True,
        "blocks_processed": 0,
        "hails_detected": 0,
        "hails_decrypted": 0,
        "overflows": 0,
        "dropped_blocks": 0,
        "combined_copies": 0,
        "combined_decrypts": 0,
    }
    t_start = time.time()

    accumulator = None
    if combine_copies > 0:
        accumulator = sisl_rx.LlrAccumulator(
            n_bits=sc.HAIL_FEC_TOTAL_BITS,
            max_copies=combine_copies,
        )

    agc_ppm = _AgcPpmState(device_name, device, center_hz,
                           vga_db, lna_db)

    block_queue: _queue.Queue[np.ndarray | None] = _queue.Queue(maxsize=4)
    reader_stop = threading.Event()
    overflow_count_at_last_check = 0

    reader = threading.Thread(
        target=_usb_reader_thread,
        args=(device, stream, block_samples, block_queue, reader_stop, stats),
        daemon=True,
    )
    reader.start()

    try:
        while time.time() - t_start < duration_s:
            try:
                block_data = block_queue.get(timeout=2.0)
            except _queue.Empty:
                continue
            if block_data is None:
                break
            filled = len(block_data)
            if filled < block_samples // 2:
                continue

            stats["blocks_processed"] += 1

            current_overflows = stats["overflows"]
            if current_overflows > overflow_count_at_last_check:
                n_new = current_overflows - overflow_count_at_last_check
                overflow_count_at_last_check = current_overflows
                print(f"       [{n_new} overflow(s) during block, "
                      f"total {current_overflows}]")

            if save_file is not None:
                block_data.tofile(save_file)

            result = sisl_rx._decode_one_hail_in_block(
                block_data, responder_static,
                samps_per_chip=samps_per_chip,
                samp_hz=samp_hz,
                signal_threshold=signal_threshold,
                top_k_soft=top_k_soft,
            )
            sisl_rx._print_live_event(stats["blocks_processed"], result)

            s = result["status"]
            if s == "decrypt_ok":
                stats["hails_detected"] += 1
                stats["hails_decrypted"] += 1
                # Store the full DecodedHail for ACK construction
                if "_decoded_hail" not in stats:
                    stats["_decoded_hail"] = result.get("decoded_hail")
            elif s == "decrypt_fail":
                stats["hails_detected"] += 1

            agc_ppm.on_block(result, block_data)

            if accumulator is not None:
                # Only feed the accumulator when the frequency estimate
                # is plausible. At low SNR (5 GHz), the FFT often locks
                # onto spurs giving |Δf| >> 50 kHz. The body LLRs from
                # spur-locked blocks are noise that DILUTES the real
                # signal in the accumulator instead of building it.
                foff = result.get("freq_offset_hz", 0)
                freq_ok = abs(foff) < 50_000  # ±50 kHz gate
                if freq_ok:
                    added = accumulator.try_add(result)
                    if added:
                        stats["combined_copies"] += 1
                    for extra_llrs in result.get("extra_fec_llrs", []):
                        extra_result = {"fec_llrs": extra_llrs}
                        if accumulator.try_add(extra_result):
                            stats["combined_copies"] += 1
                else:
                    stats["acc_freq_rejects"] = \
                        stats.get("acc_freq_rejects", 0) + 1
                if accumulator.n_copies > 0:
                    acc_l1 = float(np.mean(np.abs(accumulator.accumulated)))
                    print(f"       accumulator: {accumulator.n_copies} "
                          f"frame copies combined, "
                          f"mean |LLR|={acc_l1:.0f}")
                    combined = accumulator.try_decrypt(responder_static)
                    if combined is not None:
                        decoded_hail, label, n_flips = combined
                        stats["combined_decrypts"] += 1
                        stats["hails_decrypted"] += 1
                        print(f"\033[32m       ACCUMULATOR DECRYPT  "
                              f"n_copies={accumulator.n_copies}  "
                              f"pol={label}  "
                              f"mode=0x{decoded_hail.body.mode:02x}  "
                              f"nonce="
                              f"{decoded_hail.body.body_nonce.hex()}"
                              f"\033[0m")
                        accumulator.reset()
    except KeyboardInterrupt:
        print("  interrupted")
    finally:
        # Deactivate the stream FIRST — this unblocks any pending
        # readStream call in the reader thread, which otherwise hangs
        # for up to 500 ms on Windows while USB buffers overflow and
        # SoapySDR prints "O" to stdout for each one.
        reader_stop.set()
        device.deactivateStream(stream)
        reader.join(timeout=3.0)
        device.closeStream(stream)
        if save_file is not None:
            save_file.close()
        if _win_timer_set:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)  # type: ignore[attr-defined]
            except Exception:
                pass

    stats["elapsed_s"] = time.time() - t_start
    return stats


def offline_decode_hail(
    cfile_path: str,
    responder_static: ec.EllipticCurvePrivateKey | None = None,
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
    decode_result = sisl_rx._decode_one_hail_in_block(raw, responder_static)
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
        out["decoded_hail"] = SimpleNamespace(
            body=decode_result["body"],
            caller_eph_pub_canonical=decode_result["caller_eph_pub_canonical"],
        )
        out["decrypted"] = True
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SISL Phase 1 DSSS demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_format_freq_suggestions(),
    )
    parser.add_argument("--mode",
                        choices=("tx", "rx", "tx-to-file", "offline",
                                 "call", "respond"),
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
    parser.add_argument("--rx-amp", action="store_true", default=True,
                        help="rx: HackRF 14 dB RF preamplifier (on by "
                             "default — improves noise figure from ~12 dB "
                             "to ~4 dB). Use --no-rx-amp to disable if the "
                             "ADC saturates at very close range. "
                             "RTL-SDR has no AMP stage; flag is ignored.")
    parser.add_argument("--no-rx-amp", action="store_false", dest="rx_amp",
                        help="rx: disable HackRF RX AMP")
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
    parser.add_argument("--ppm", type=float, default=0.0,
                        help="rx: known crystal PPM offset (e.g. from a "
                             "prior calibration at a lower frequency). "
                             "Pre-adjusts the RX center frequency to "
                             "compensate for the crystal error, so the "
                             "FFT frequency estimator only needs to find "
                             "the small residual. Critical at 5+ GHz "
                             "where 50 ppm = 250 kHz offset.")
    parser.add_argument("--signal-threshold", type=float,
                        default=sisl_rx._SIGNAL_FLOOR_RATIO,
                        help=f"rx: peak/median ratio that counts as signal "
                             f"present (default {sisl_rx._SIGNAL_FLOOR_RATIO}). "
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
    parser.add_argument("--combine", type=int, default=20,
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
    parser.add_argument("--chip-rate", type=float, default=1.0,
                        help="chip rate in Mcps (default 1.0). Higher rates "
                             "shorten each symbol, reducing phase drift per "
                             "symbol and allowing faster frame repetition. "
                             "Must divide evenly into the device sample rate "
                             "with quotient ≥ 2. E.g. at 8 Msps: 1.0 → 8 "
                             "samp/chip, 2.0 → 4, 4.0 → 2. The occupied "
                             "bandwidth equals the chip rate, so 2 Mcps "
                             "occupies 2 MHz. TX and RX must use the same "
                             "chip rate.")
    args = parser.parse_args()

    # ── Resolve chip rate → samples per chip for the selected device ──
    chip_rate_hz = int(args.chip_rate * 1e6)
    device_info = DEVICES[args.device]
    # TX always uses HackRF
    tx_info = DEVICES["hackrf"]
    if args.mode in ("tx", "tx-to-file"):
        active_samp_hz = tx_info.samp_hz
    else:
        active_samp_hz = device_info.samp_hz
    if active_samp_hz % chip_rate_hz != 0:
        parser.error(
            f"--chip-rate {args.chip_rate} Mcps ({chip_rate_hz} Hz) does not "
            f"divide evenly into the device sample rate "
            f"({active_samp_hz} Hz). Quotient would be "
            f"{active_samp_hz / chip_rate_hz:.2f} — must be an integer ≥ 2."
        )
    active_samps_per_chip = active_samp_hz // chip_rate_hz
    if active_samps_per_chip < 2:
        parser.error(
            f"--chip-rate {args.chip_rate} Mcps gives only "
            f"{active_samps_per_chip} sample(s)/chip at "
            f"{active_samp_hz/1e6:.0f} Msps — need ≥ 2."
        )

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
        # Minimum block must hold ≥2 FEC frames. Frame duration depends
        # on chip rate: 2096 symbols × 1023 chips/symbol / chip_rate.
        frame_sec = 2096 * 1023 / chip_rate_hz
        min_block_sec = max(3.0, frame_sec * 2.5)
        if block_sec < min_block_sec:
            block_sec = min_block_sec
        # Apply PPM pre-correction to the initial center frequency.
        # This shifts the tuner to compensate for the known crystal
        # error, placing the signal near 0 Hz in baseband so the FFT
        # estimator only needs to find the small residual.
        rx_center_hz = args.freq * 1e6
        if args.ppm != 0.0:
            ppm_offset_hz = rx_center_hz * args.ppm / 1e6
            rx_center_hz += ppm_offset_hz
            print(f"  PPM pre-correction: {args.ppm:+.1f} ppm → "
                  f"tuning to {rx_center_hz/1e6:.6f} MHz "
                  f"({ppm_offset_hz:+.0f} Hz)")
        stats = live_rx_decode(
            duration_s=args.duration,
            block_seconds=block_sec,
            responder_static=responder,
            save_path=save,
            lna_db=args.rx_lna,
            vga_db=args.rx_vga,
            amp_on=args.rx_amp,
            center_hz=rx_center_hz,
            device_name=args.device,
            signal_threshold=args.signal_threshold,
            top_k_soft=args.top_k,
            combine_copies=args.combine,
            samps_per_chip=active_samps_per_chip,
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
        if stats.get("dropped_blocks", 0):
            print(f"  dropped blocks:  {stats['dropped_blocks']} "
                  "(queue full, reader kept draining USB)")
        print(f"  hails detected:  {stats['hails_detected']} "
              "(SISL frame parsed)")
        print(f"  hails decrypted: {stats['hails_decrypted']} "
              "(Poly1305 verified)")
        if stats.get("combined_copies", 0) or stats.get("combined_decrypts", 0):
            print(f"  combined copies: {stats.get('combined_copies', 0)}")
            print(f"  combined decrypt:{stats.get('combined_decrypts', 0)}")
        return 0 if stats["hails_decrypted"] > 0 else 1

    # ── mode == "respond": listen for hail → TX ACK → print session keys ──
    if args.mode == "respond":
        responder_static = demo_responder_key()
        center_hz = args.freq * 1e6
        print(f"respond: listening for hail on {args.freq:.1f} MHz, "
              f"will TX ACK on decrypt")

        # Listen-after-talk: coprime periods T_respond=3s (2s TX, 1s gap)
        # Responder listens continuously until hail received, then TX ACK
        block_sec = max(3.0, 2096 * 1023 / chip_rate_hz * 2.5)
        decoded_hail = None

        # Phase 1: listen for hail
        while decoded_hail is None:
            stats = live_rx_decode(
                duration_s=args.duration,
                block_seconds=block_sec,
                responder_static=responder_static,
                lna_db=args.rx_lna, vga_db=args.rx_vga,
                amp_on=args.rx_amp, center_hz=center_hz,
                device_name=args.device,
                signal_threshold=args.signal_threshold,
                top_k_soft=args.top_k,
                combine_copies=args.combine,
                samps_per_chip=active_samps_per_chip,
            )
            # Check if any hail was decrypted — pull DecodedHail from stats
            dh = stats.get("_decoded_hail")
            if dh is not None:
                decoded_hail = dh
                print(f"\n\033[32m  HAIL RECEIVED — preparing ACK\033[0m")
                break
            if not stats.get("ok", True):
                print(f"RX error: {stats.get('error')}", file=sys.stderr)
                return 2

        # Phase 2: TX ACK (repeat 3× for reliability, T_respond=3s)
        responder_eph = sc.Ephemeral()
        ack_bits = sc.encode_ack_fec(responder_eph, decoded_hail, status=1)
        ack_chips = sf.tx_bits_to_chips(ack_bits)
        ack_samples = upsample_chips_to_samples(ack_chips, SAMPS_PER_CHIP)
        ack_repeats = 5  # ~7.6 seconds at 1 Mcps
        print(f"  TX ACK: {sc.ACK_FEC_TOTAL_BITS} channel bits × "
              f"{ack_repeats} repeats → "
              f"{len(ack_chips) * ack_repeats / chip_rate_hz:.1f}s on air")
        soapy_tx_burst(
            ack_samples, center_hz,
            samp_hz=SAMP_RATE_HZ,
            tx_vga_db=args.tx_vga,
            tx_amp_on=args.tx_amp,
            repeats=ack_repeats,
        )
        print(f"\033[32m  ACK TRANSMITTED — handshake complete\033[0m")
        # Session keys available on responder side already (encode_ack
        # computed all three DH terms). Print confirmation.
        print(f"  nonce echoed:  {decoded_hail.body.body_nonce.hex()}")
        return 0

    # ── mode == "call": TX hail → listen for ACK → session keys ──────────
    if args.mode == "call":
        caller_static = demo_caller_key()
        responder_static_pub = demo_responder_key().public_key()
        center_hz = args.freq * 1e6

        # Build the hail — retain ephemeral key for ACK decode
        caller_eph = sc.Ephemeral()
        caller_eph_priv = caller_eph.peek()  # retain for ACK decode
        body = sc.HailBody(
            caller_static_pub=sc.pubkey_to_compressed(
                caller_static.public_key()),
            center_freq_offset=100,
            bandwidth_code=0x03, mode=0x01,
            chip_rate_code=0x32,
            body_nonce=os.urandom(8),
            flags=0x03,
        )
        # Compute DH1 for later ACK verification
        dh1 = sc.ecdh(caller_eph_priv, responder_static_pub)

        hail_bits = sc.encode_hail_fec(
            caller_eph, responder_static_pub, body)
        hail_chips = sf.tx_bits_to_chips(hail_bits)
        hail_samples = upsample_chips_to_samples(
            hail_chips, SAMPS_PER_CHIP)

        # Listen-after-talk: coprime periods
        # Caller: TX 5s, RX 2s → period T₁=7s
        TX_DURATION = 5.0
        RX_DURATION = 2.0
        MAX_ROUNDS = int(args.duration / (TX_DURATION + RX_DURATION))

        print(f"call: hailing on {args.freq:.1f} MHz")
        print(f"  nonce:         {body.body_nonce.hex()}")
        print(f"  duty cycle:    TX {TX_DURATION:.0f}s / RX {RX_DURATION:.0f}s "
              f"(coprime period 7s)")
        print(f"  max rounds:    {MAX_ROUNDS}")

        for round_num in range(1, MAX_ROUNDS + 1):
            # TX phase
            tx_repeats = max(1, int(TX_DURATION * chip_rate_hz
                                    / len(hail_chips)))
            print(f"\n  round {round_num}: TX hail "
                  f"({tx_repeats} repeats)...", end="", flush=True)
            soapy_tx_burst(
                hail_samples, center_hz,
                samp_hz=SAMP_RATE_HZ,
                tx_vga_db=args.tx_vga,
                tx_amp_on=args.tx_amp,
                repeats=tx_repeats,
            )
            print(" done. Listening for ACK...", flush=True)

            # RX phase — capture one block and try ACK decode
            import SoapySDR as _soapy
            from SoapySDR import SOAPY_SDR_RX as _RX, SOAPY_SDR_CF32 as _CF32
            rx_samp_hz = active_samps_per_chip * chip_rate_hz
            rx_samp_hz = max(2_000_000, min(DEVICES["hackrf"].samp_hz,
                                             rx_samp_hz))
            rx_dev = _soapy.Device("driver=hackrf")
            rx_dev.setSampleRate(_RX, 0, rx_samp_hz)
            rx_dev.setFrequency(_RX, 0, center_hz)
            rx_dev.setGain(_RX, 0, "AMP", 14.0 if args.rx_amp else 0.0)
            rx_dev.setGain(_RX, 0, "LNA", float(args.rx_lna))
            rx_dev.setGain(_RX, 0, "VGA", float(args.rx_vga))
            rx_stream = rx_dev.setupStream(_RX, _CF32)
            rx_dev.activateStream(rx_stream)

            n_rx_samples = int(RX_DURATION * rx_samp_hz)
            rx_buf = np.empty(n_rx_samples, dtype=np.complex64)
            filled = 0
            while filled < n_rx_samples:
                sr = rx_dev.readStream(
                    rx_stream, [rx_buf[filled:]], n_rx_samples - filled,
                    timeoutUs=500_000)
                if sr.ret > 0:
                    filled += sr.ret
                elif sr.ret == -1:
                    continue
                else:
                    break
            rx_dev.deactivateStream(rx_stream)
            rx_dev.closeStream(rx_stream)
            del rx_dev

            if filled > n_rx_samples // 2:
                ack_result = sisl_rx.decode_one_ack_in_block(
                    rx_buf[:filled],
                    caller_static_priv=caller_static,
                    caller_eph_priv=caller_eph_priv,
                    dh1=dh1,
                    expected_nonce_echo=body.body_nonce,
                    samps_per_chip=active_samps_per_chip,
                    samp_hz=rx_samp_hz,
                )
                s = ack_result.get("status", "")
                foff = ack_result.get("freq_offset_hz", 0)
                if s == "decrypt_ok":
                    da = ack_result["decoded_ack"]
                    print(f"\n\033[32m  ACK RECEIVED — "
                          f"status={da.body.status} "
                          f"nonce_echo={da.body.nonce_echo.hex()} "
                          f"Δf={foff:+.0f}Hz\033[0m")
                    print(f"  SESSION ESTABLISHED")
                    return 0
                elif s in ("decrypt_fail", "track_lost"):
                    print(f"    ({s} Δf={foff:+.0f}Hz)")
                else:
                    print(f"    ({s})")

        print(f"\n  timeout after {MAX_ROUNDS} rounds — no ACK received")
        return 1

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
        samps_per_chip=active_samps_per_chip,
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
    print(f"  chip rate:     {chip_rate_hz/1e6:.1f} Mcps "
          f"({active_samps_per_chip} samples/chip at "
          f"{tx_info.samp_hz/1e6:.0f} Msps)")
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
