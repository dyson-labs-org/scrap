"""SISL DSSS hidden-signal demo.

Primary runtime is SoapySDR-only (call/respond/tx/rx).

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

Status: **UNTESTED** — written without hardware in the loop. Validate the
live pipeline at the bench before running. The pure-numpy DSP layer in
sisl_framer.py is fully tested (see test_sisl_framer.py) and is the ground
truth for spread/despread semantics.

Both tx and rx emit/capture a SISL v3 hail frame built by build_demo_hail
(using the deterministic demo_responder_key target). The offline mode
decodes the captured file via sisl_crypto.decode_hail.

Usage:
    python hackathon/demo.py --mode tx       # SoapyTX a demo hail
    python hackathon/demo.py --mode rx       # capture samples to /tmp/sisl_rx.cfile
    python hackathon/demo.py --mode offline  # decode and decrypt a capture
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import select as _select_mod
import sys
import time
from types import SimpleNamespace

import numpy as np

from cryptography.hazmat.primitives.asymmetric import ec

import sisl_crypto as sc
import sisl_fec
import sisl_rx
from sisl_payload import decode_payload_symbol
from sisl_payload_session import RLNCSession

import sisl_framer as sf
from sisl_sdr import (
    SoapyDevice,
    _AgcPpmState,
    _open_soapy_with_retry,
    _read_device_serial,
    _usb_reader_thread,
    soapy_tx_burst,
    soapy_tx_streaming,
    upsample_chips_to_samples,
)


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
ACK_TX_WINDOW = 50.0                    # responder ACK TX duration (s); caller waits this long
DEMO_PAYLOAD = (
    b"SISL RLNC fountain code over DSSS steganographic link "
    b"-- hackathon demo payload v1"
)

_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_TX = "\033[33m"
_ANSI_RX = "\033[36m"


def _phase_header(phase: int, role: str, title: str, detail: str | None = None) -> None:
    role_color = _ANSI_TX if "TX" in role else _ANSI_RX
    print(f"\n  {_ANSI_BOLD}phase {phase}{_ANSI_RESET} "
          f"{role_color}[{role}] {title}{_ANSI_RESET}")
    if detail:
        print(f"    {detail}")


def _is_debug_output_enabled() -> bool:
    return bool(getattr(sf, "SISL_DEBUG", False))


# ── Per-device RX configuration ────────────────────────────────────────────
#
# The HackRF and RTL-SDR families have very different sample rate grids
# and frequency ranges. The TX path is HackRF-only (RTL-SDR is RX-only
# hardware); the RX path can use either.

from sdr_devices import (
    DeviceInfo, DEVICES, DEVICE_PPM as _DEVICE_PPM,
    PLUGIN_INSTALL_HINTS as _PLUGIN_INSTALL_HINTS,
    format_device_open_error as _format_device_open_error,
    get_device_ppm as _get_device_ppm,
    get_band_min_vga as _get_band_min_vga,
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

    Returns the 135-byte on-wire frame. The encrypted body carries
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
        payload_len=0,
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
        payload_len=0,
    )
    # Capture the canonical frame for printing/debugging by re-encoding
    # under a separate ephemeral. The on-wire bits use the consumed eph.
    diag_eph = sc.Ephemeral()
    diag_frame = sc.encode_hail(diag_eph, responder_static.public_key(), body)
    bits = sc.encode_hail_fec(caller_eph, responder_static.public_key(), body)
    chips = sf.tx_bits_to_chips(bits)
    return chips, diag_frame


# Soapy/upsample helpers moved to sisl_sdr.py.


# ── TX to file (pure numpy, no radio) ──────────────────────────────────────

def tx_to_file(message: bytes, path: str,
               prefix_ms: float = 0.0,
               repeats: int = 1) -> int:
    """Synthesize a TX capture from `message` and write it as complex64.

    Bypasses live SDR hardware entirely. Useful for smoke-testing the TX
    upsampling path and the offline despread chain without a bench setup.

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




# USB reader + AGC/PPM state moved to sisl_sdr.py.


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
    exit_on_decrypt: bool = False,
    decode_fn=None,
    device=None,
    initial_vga_db: float | None = None,
    disable_auto_ppm: bool = False,
    coord_fd: int | None = None,
    flush_after_tx: bool = False,
) -> dict:
    """Stream samples from the selected device, decode SISL hails live.

    If `device` is a pre-opened SoapySDR.Device it is used directly —
    the caller is responsible for configuring sample rate, frequency, and
    initial gain before calling, and for closing the device afterward.
    The stats dict includes ``final_vga_db`` and ``final_center_hz`` so
    the caller can pre-seed the next phase (optimizations B and C).

    `initial_vga_db`: skip AGC warmup, start at this VGA gain (dB).
    `disable_auto_ppm`: skip auto-PPM updates; use static cal only (C).

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

    _owns_device = device is None
    if _owns_device:
        if _is_debug_output_enabled():
            print(f"opening {info.name} at {center_hz/1e6:.1f} MHz, "
                  f"{samp_hz/1e6:.3f} Msps, block={block_seconds}s "
                  f"(processing ~{int(block_seconds*samp_hz*8/1e6)} MB/block, "
                  f"{samps_per_chip} samples/chip)")
        else:
            print(f"opening {info.name} at {center_hz/1e6:.1f} MHz")
        try:
            device = _open_soapy_with_retry(info.driver)
        except RuntimeError as e:
            return {
                "ok": False,
                "error": _format_device_open_error(SoapySDR, info, e),
            }

        # Auto-load calibrated PPM correction from the device serial.
        serial = _read_device_serial(device, SoapySDR, info.driver)
        cal_ppm = _get_device_ppm(serial)
        short_serial = serial.lstrip("0") or serial
        if cal_ppm != 0.0:
            ppm_offset_hz = center_hz * cal_ppm / 1e6
            center_hz += ppm_offset_hz
            if _is_debug_output_enabled():
                print(f"  PPM cal: device {short_serial} → {cal_ppm:+.1f} ppm "
                      f"({ppm_offset_hz:+.0f} Hz)")

        device.setSampleRate(SOAPY_SDR_RX, 0, samp_hz)
        device.setFrequency(SOAPY_SDR_RX, 0, center_hz)

        if device_name == "hackrf":
            device.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if amp_on else 0.0)
            device.setGain(SOAPY_SDR_RX, 0, "LNA", float(lna_db))
            device.setGain(SOAPY_SDR_RX, 0, "VGA", float(vga_db))
            if _is_debug_output_enabled():
                print(f"  RX gain: AMP={'on' if amp_on else 'off'} "
                      f"LNA={lna_db} dB VGA={vga_db} dB")
        elif device_name == "rtlsdr":
            combined_db = max(0.0, min(49.0, float(lna_db + vga_db)))
            device.setGain(SOAPY_SDR_RX, 0, combined_db)
            if _is_debug_output_enabled():
                print(f"  RX gain: TUNER={combined_db:.1f} dB "
                      f"(from --rx-lna {lna_db} + --rx-vga {vga_db}; "
                      f"clamped to [0, 49])")
            if amp_on and _is_debug_output_enabled():
                print("  NOTE: --rx-amp ignored — RTL-SDR has no AMP stage")
        else:
            raise ValueError(f"unhandled device {device_name}")
    else:
        # Pre-opened device: reconfigure RX parameters without reopening.
        # PPM correction was already applied at SoapyDevice open time so
        # center_hz is already the corrected value.
        from SoapySDR import SOAPY_SDR_RX as _SOAPY_RX
        device.setSampleRate(_SOAPY_RX, 0, samp_hz)
        device.setFrequency(_SOAPY_RX, 0, center_hz)
        if device_name == "hackrf":
            device.setGain(_SOAPY_RX, 0, "AMP", 14.0 if amp_on else 0.0)
            device.setGain(_SOAPY_RX, 0, "LNA", float(lna_db))
            vga_start = float(initial_vga_db) if initial_vga_db is not None else float(vga_db)
            device.setGain(_SOAPY_RX, 0, "VGA", vga_start)
            if _is_debug_output_enabled():
                print(f"reusing open {info.name}: "
                      f"AMP={'on' if amp_on else 'off'} LNA={lna_db} dB "
                      f"VGA={vga_start:.0f} dB, {samp_hz/1e6:.3f} Msps, "
                      f"block={block_seconds}s "
                      f"(~{int(block_seconds*samp_hz*8/1e6)} MB/block)")
        elif device_name == "rtlsdr":
            combined_db = max(0.0, min(49.0, float(lna_db + vga_db)))
            device.setGain(_SOAPY_RX, 0, combined_db)
            if _is_debug_output_enabled():
                print(f"reusing open {info.name}: TUNER={combined_db:.1f} dB, "
                      f"block={block_seconds}s")
        else:
            raise ValueError(f"unhandled device {device_name}")
        if initial_vga_db is not None and _is_debug_output_enabled():
            print(f"  pre-seeded VGA={initial_vga_db:.0f} dB  "
                  f"{'auto-PPM disabled (static cal)' if disable_auto_ppm else 'auto-PPM enabled'}")

    assert device is not None

    stream_args = {"bufflen": "262144", "buffers": "8"}
    stream = device.setupStream(
        SOAPY_SDR_RX, SOAPY_SDR_CF32, [0], stream_args)
    device.activateStream(stream)

    # Flush ~500ms of samples after activating the RX stream.
    # After TX→RX transition, the HackRF's analog frontend retains
    # residual TX energy (PLL settling, DAC ring-down) that correlates
    # with the DSSS spreading code and produces false FRAME FOUND
    # detections.  Discarding the first 500ms clears this.
    # Only needed after TX→RX transitions, not when starting fresh in RX.
    if flush_after_tx:
        _flush_samples = int(0.5 * samp_hz)
        _flush_buf = np.empty(min(_flush_samples, 65536), dtype=np.complex64)
        _flushed = 0
        while _flushed < _flush_samples:
            _want = min(len(_flush_buf), _flush_samples - _flushed)
            sr = device.readStream(stream, [_flush_buf[:_want]], _want, timeoutUs=500_000)
            if sr.ret > 0:
                _flushed += sr.ret
            elif sr.ret == -1:  # timeout
                break

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
    _last_heartbeat = t_start

    # Per-frequency accumulator bank: each candidate frequency gets its
    # own LLR accumulator.  The correct frequency's accumulator grows
    # (constructive LLR addition) while wrong frequencies stay flat
    # (random LLR signs cancel).  Keyed by freq in kHz (rounded).
    _freq_accumulators: dict[int, sisl_rx.LlrAccumulator] = {}
    _MAX_FREQ_ACCUMULATORS = 6

    def _get_accumulator(freq_rad: float) -> sisl_rx.LlrAccumulator:
        freq_khz = int(round(freq_rad * samp_hz / (2.0 * np.pi * 1000)))
        if freq_khz not in _freq_accumulators:
            if len(_freq_accumulators) >= _MAX_FREQ_ACCUMULATORS:
                # Evict the accumulator with the fewest copies
                worst = min(_freq_accumulators, key=lambda k: _freq_accumulators[k].n_copies)
                del _freq_accumulators[worst]
            _freq_accumulators[freq_khz] = sisl_rx.LlrAccumulator(
                n_bits=sc.HAIL_FEC_TOTAL_BITS,
                max_copies=combine_copies or 64,
            )
        return _freq_accumulators[freq_khz]

    agc_ppm = _AgcPpmState(device_name, device, center_hz,
                           vga_db, lna_db,
                           initial_vga_db=initial_vga_db,
                           disable_auto_ppm=disable_auto_ppm)

    # 3-stage pipeline: USB reader → raw_queue → decode worker → result_queue → main.
    # Decode worker computes sample_p99 before decode so main thread never
    # needs the raw block array (AGC reads p99 from result dict).
    raw_queue: _queue.Queue[np.ndarray | None] = _queue.Queue(maxsize=2)
    result_queue: _queue.Queue = _queue.Queue(maxsize=1)
    reader_stop = threading.Event()
    decode_stop = threading.Event()
    overflow_count_at_last_check = 0

    _save_file_ref = save_file  # captured by worker closure

    # Frequency candidate bank: parallel correlator architecture.
    # Each entry is a rad/sample value from a prior block where a frame
    # was detected (decrypt_ok or decrypt_fail).  All candidates are
    # scored with the full MF each block; the best-scoring one enters
    # tracking mode (cheap fine refinement), avoiding the expensive
    # coarse grid that can lock onto spurs.  Capped at _MAX_FREQ_CANDS
    # to bound per-block scoring cost (~27ms each).
    _MAX_FREQ_CANDS = 6
    # Pre-seed candidates from known device PPM values.  The RX device's
    # PPM is already corrected (center_hz includes it).  The TX device's
    # crystal error creates a residual offset = -ppm_tx * center_hz.
    # We don't know which TX device is active, so seed candidates for
    # ALL known devices.  The parallel pipeline scores them all; the
    # correct one's MF periodicity dominates.  Also include 0 Hz (both
    # devices perfectly corrected).
    _freq_candidates: list[float] = [0.0]
    for _ppm_val in set(_DEVICE_PPM.values()):
        if _ppm_val == 0.0:
            continue
        _offset_hz = -_ppm_val * center_hz / 1e6
        _offset_rad = _offset_hz * 2.0 * np.pi / samp_hz
        _freq_candidates.append(_offset_rad)

    def _decode_worker() -> None:
        import os as _os
        _os.environ.setdefault("OMP_NUM_THREADS", "1")
        while not decode_stop.is_set():
            try:
                block_data = raw_queue.get(timeout=1.0)
            except _queue.Empty:
                if sf.SISL_DEBUG:
                    sf.debug_telemetry("decode", status="queue_empty")
                continue
            if block_data is None:
                result_queue.put(None)
                return
            if sf.SISL_DEBUG:
                import time as _dbg_time
                _dbg_t0 = _dbg_time.time()
                sf.debug_telemetry(
                    "decode",
                    status="block_start",
                    candidates=len(_freq_candidates),
                    block_samples=len(block_data),
                )
            try:
                _abs_sub = np.abs(block_data[::10])
                _k99 = int(0.99 * len(_abs_sub))
                sample_p99 = float(np.partition(_abs_sub, _k99)[_k99])
                if _save_file_ref is not None:
                    block_data.tofile(_save_file_ref)
                if decode_fn is not None:
                    result = decode_fn(block_data)
                else:
                    result = sisl_rx._decode_one_hail_in_block(
                        block_data, responder_static,
                        samps_per_chip=samps_per_chip,
                        samp_hz=samp_hz,
                        signal_threshold=signal_threshold,
                        top_k_soft=top_k_soft,
                        freq_candidates=_freq_candidates or None,
                    )
                    # Add new frequency candidates from blocks where a frame
                    # was actually found.  Deduplicate within 1 kHz to avoid
                    # clustering around the same frequency.
                    _s = result.get("status", "")
                    if _s in ("decrypt_ok", "decrypt_fail"):
                        _rad = result.get("rad_per_sample")
                        if _rad is not None:
                            _hz = _rad * samp_hz / (2.0 * np.pi)
                            _dup = any(abs(_hz - c * samp_hz / (2.0 * np.pi)) < 1000.0
                                       for c in _freq_candidates)
                            if not _dup:
                                _freq_candidates.append(_rad)
                                if len(_freq_candidates) > _MAX_FREQ_CANDS:
                                    _freq_candidates.pop(0)
                result["sample_p99"] = sample_p99
                if sf.SISL_DEBUG:
                    sf.debug_telemetry(
                        "decode",
                        status=result.get("status", "unknown"),
                        candidates=len(_freq_candidates),
                        elapsed_s=_dbg_time.time() - _dbg_t0,
                    )
                result_queue.put(result)
            except Exception as _e:
                print(f"  [decode worker] exception: {_e}", flush=True)
                import traceback; traceback.print_exc()
                result_queue.put({"status": "decode_error", "error": str(_e),
                                  "sample_p99": 0.0})
        result_queue.put(None)

    reader = threading.Thread(
        target=_usb_reader_thread,
        args=(device, stream, block_samples, raw_queue, reader_stop, stats),
        daemon=True,
    )
    decode_thread = threading.Thread(target=_decode_worker, daemon=True)
    reader.start()
    decode_thread.start()

    try:
        while time.time() - t_start < duration_s:
            _no_result = object()
            result = _no_result
            try:
                result = result_queue.get_nowait()
            except _queue.Empty:
                pass
            if result is _no_result:
                if coord_fd is not None:
                    ready, _, _ = _select_mod.select([coord_fd], [], [], 0)
                    if ready:
                        break  # coord has data — exit, let caller handle
                try:
                    result = result_queue.get(timeout=2.0)
                except _queue.Empty:
                    now = time.time()
                    if now - _last_heartbeat >= 5.0:
                        print(
                            "       waiting for RX blocks... "
                            f"processed={stats['blocks_processed']} "
                            f"overflows={stats.get('overflows', 0)} "
                            f"dropped={stats.get('dropped_blocks', 0)}",
                            flush=True,
                        )
                        _last_heartbeat = now
                    continue
            if result is None:
                break

            stats["blocks_processed"] += 1
            _last_heartbeat = time.time()

            current_overflows = stats["overflows"]
            if current_overflows > overflow_count_at_last_check:
                n_new = current_overflows - overflow_count_at_last_check
                overflow_count_at_last_check = current_overflows
                if _is_debug_output_enabled():
                    print(f"       [{n_new} overflow(s) during block, "
                          f"total {current_overflows}]")

            sisl_rx._print_live_event(stats["blocks_processed"], result)

            s = result["status"]
            if result.get("stop_rx"):
                stats["stop_reason"] = s
                if "stop_detail" in result:
                    stats["stop_detail"] = result["stop_detail"]
                decode_stop.set()
                break
            if s == "decrypt_ok":
                stats["hails_detected"] += 1
                stats["hails_decrypted"] += 1
                # Store the full decoded object (hail or ACK)
                if "_decoded_hail" not in stats:
                    stats["_decoded_hail"] = (result.get("decoded_hail")
                                              or result.get("decoded_ack"))
                    stats["_decode_peak_mag"] = result.get("peak_mag")
                    stats["_decode_freq_offset_hz"] = result.get("freq_offset_hz", 0.0)
                if exit_on_decrypt:
                    decode_stop.set()
                    break
            elif s == "decrypt_fail":
                stats["hails_detected"] += 1

            agc_ppm.on_block(result)

            # ── Per-frequency accumulator bank ─────────────────────
            # Feed LLRs from each frequency pipeline to its own
            # accumulator.  The correct frequency builds coherently
            # (√N gain) while wrong ones cancel.
            multi = result.get("_multi_results") or [result]
            for mr in multi:
                mr_fec = mr.get("fec_llrs")
                mr_freq = mr.get("_freq_rad") or mr.get("rad_per_sample")
                if mr_fec is None or mr_freq is None:
                    continue
                acc = _get_accumulator(mr_freq)
                added = acc.try_add({
                    "fec_llrs": mr_fec,
                    "freq_offset_hz": mr.get("freq_offset_hz"),
                })
                if added:
                    stats["combined_copies"] += 1
                # Also add extra frame copies from within the block
                for extra in mr.get("extra_fec_llrs", []):
                    if acc.try_add({"fec_llrs": extra}):
                        stats["combined_copies"] += 1

            # Try decrypt on ALL accumulators
            for freq_khz, acc in list(_freq_accumulators.items()):
                if acc.n_copies == 0:
                    continue
                combined = acc.try_decrypt(responder_static)
                if combined is not None:
                    decoded_hail, label, n_flips = combined
                    stats["combined_decrypts"] += 1
                    stats["hails_decrypted"] += 1
                    if _is_debug_output_enabled():
                        print(f"\033[32m       ACCUMULATOR DECRYPT  "
                              f"freq={freq_khz}kHz  "
                              f"n_copies={acc.n_copies}  "
                              f"pol={label}  "
                              f"nonce="
                              f"{decoded_hail.body.body_nonce.hex()}"
                              f"\033[0m")
                    if "_decoded_hail" not in stats:
                        stats["_decoded_hail"] = decoded_hail
                        stats["_decode_peak_mag"] = result.get("peak_mag")
                        stats["_decode_freq_offset_hz"] = (
                            freq_khz * 1000.0)
                    acc.reset()
                    if exit_on_decrypt:
                        decode_stop.set()

            # Print accumulator summary (best one)
            if _is_debug_output_enabled() and _freq_accumulators:
                best_acc = max(_freq_accumulators.values(),
                               key=lambda a: a.n_copies)
                if best_acc.n_copies > 0:
                    acc_l1 = float(np.mean(np.abs(best_acc.accumulated)))
                    best_khz = [k for k, v in _freq_accumulators.items()
                                if v is best_acc][0]
                    print(f"       accumulator: {best_acc.n_copies} copies "
                          f"@ {best_khz}kHz, "
                          f"mean |LLR|={acc_l1:.3f}  "
                          f"({len(_freq_accumulators)} freq bins)")
    except KeyboardInterrupt:
        print("  interrupted")
        raise  # propagate so outer loops exit cleanly
    finally:
        # Signal threads to stop, then wait for the decode worker to finish
        # its current block before touching the device.  Closing the device
        # while fftconvolve is running in the decode thread causes a segfault
        # (scipy pocketfft accesses freed memory).
        decode_stop.set()
        reader_stop.set()
        # Wait for decode thread FIRST — it may be mid-FFT.
        decode_thread.join(timeout=8.0)
        # hackrf#1570: deactivateStream hangs indefinitely when USB transfers
        # are in-flight.  For _owns_device=True, closing the device cancels
        # all USB transfers.  For _owns_device=False (shared device handle),
        # we CANNOT close the device (caller owns it for the next phase).
        # Instead, skip deactivateStream and just close the stream — the
        # reader thread exits on its next readStream timeout (50ms).
        if _owns_device:
            try:
                device.close()
            except Exception:
                pass
        reader.join(timeout=3.0)
        try:
            device.deactivateStream(stream)
        except Exception:
            pass
        try:
            device.closeStream(stream)
        except Exception:
            pass
        if save_file is not None:
            save_file.close()
        if _win_timer_set:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)  # type: ignore[attr-defined]
            except Exception:
                pass

    stats["elapsed_s"] = time.time() - t_start
    # Capture converged AGC/PPM state before releasing — callers use these
    # to pre-seed the next RX phase (optimization B).
    stats["final_vga_db"] = agc_ppm.final_vga_db
    stats["final_center_hz"] = agc_ppm.final_center_hz
    del agc_ppm  # drop reference before device close
    if _owns_device and not _reader_forced_close:
        # Explicitly close the device here so __del__ fires while still inside
        # live_rx_decode (device.__del__ → device.close() was causing exit after
        # function return in CPython 3.14 / libhackrf interaction).
        # Skip if already closed above to unblock the stuck reader (hackrf#1570).
        try:
            device.close()
        except Exception:
            pass
        del device
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


def _coord_expect_switch(coord, step: str, timeout: float = 300.0) -> None:
    if coord is None:
        return
    if not coord.wait_for_switch(timeout=timeout):
        raise TimeoutError(f"coord: timed out waiting for switch ({step})")


def _compute_rlnc_rx_timeout(
    *,
    coord_active: bool,
    k_symbols: int,
    symbol_bytes: int,
    chip_rate_hz: int,
) -> float:
    if coord_active:
        # coord_fd readability is the primary stop condition in this path.
        return 600.0
    n_coded = k_symbols + max(120, k_symbols * 8)
    n_fec = sc.payload_fec_total_bits(symbol_bytes)
    sym_dur = (n_fec * sf.CHIPS_PER_SYMBOL) / chip_rate_hz
    return max(120.0, (2 + n_coded) * sym_dur * 1.5)


def _finalize_call_payload_coord(coord, payload_early: bool) -> bool:
    if coord is None:
        return True
    if payload_early:
        _coord_expect_switch(coord, "call consume decoded-early signal")
        print("  coord: respond decoded early", flush=True)
        coord.send_switch()  # tell respond: TX stopped
    else:
        print("  coord: payload TX done — notifying respond", flush=True)
        coord.send_switch()  # tell respond: TX done
        try:
            _coord_expect_switch(coord, "call waiting respond decoded")
        except (ConnectionError, TimeoutError) as e:
            print(f"  coord: respond failed ({e})", flush=True)
            return False
        print("  coord: respond decoded", flush=True)
    coord.send_switch()
    print("  coord: told respond to TX payload ACK", flush=True)
    return True


def _run_respond_mode(
    args: argparse.Namespace,
    *,
    coord,
    chip_rate_hz: int,
    active_samps_per_chip: int,
) -> int:
    responder_static = demo_responder_key()
    coord_active = coord is not None
    print(f"respond: listening for hail on {args.freq:.1f} MHz, "
          f"will TX ACK on decrypt")

    # One hail frame = 2096 symbols × 1023 chips / chip_rate ≈ 2.14s.
    # Keep blocks small enough to process in real time (decode takes
    # ~1.2s for 3M samples at 2 Msps).  Rely on multi-copy LLR
    # accumulation across blocks rather than fitting 2.5 frames per block.
    block_sec = max(3.0, 2096 * 1023 / chip_rate_hz * 1.5)
    listen_duration = max(600.0, args.duration)

    # Apply --ppm to SoapyDevice so TX (ACK, payload ACK) uses the
    # corrected center frequency, not just RX.  This aligns ACK TX with
    # the caller's RX center so the caller sees the ACK near 0 Hz even
    # when inter-device crystal spread is large (e.g. 205 kHz at 5.8 GHz).
    respond_center_hz = args.freq * 1e6
    if args.ppm != 0.0:
        respond_center_hz += respond_center_hz * args.ppm / 1e6
    device_str = None
    if args.serial:
        device_str = f"driver=hackrf,serial={args.serial}"
    with SoapyDevice(args.device, device_str=device_str, center_hz=respond_center_hz) as sdr:
        # ── Phase 1: hail RX ──────────────────────────────────────────
        _phase_header(1, "RESPOND RX", "hail listen",
                      f"window up to {listen_duration:.0f}s")
        stream_errors = 0
        while True:
            decoded_hail = None
            while decoded_hail is None:
                hail_stats = live_rx_decode(
                    duration_s=listen_duration,
                    block_seconds=block_sec,
                    responder_static=responder_static,
                    lna_db=args.rx_lna,
                    vga_db=args.rx_vga,
                    amp_on=args.rx_amp,
                    center_hz=sdr.center_hz,
                    device_name=args.device,
                    signal_threshold=args.signal_threshold,
                    top_k_soft=args.top_k,
                    combine_copies=args.combine,
                    samps_per_chip=active_samps_per_chip,
                    exit_on_decrypt=True,
                    device=sdr.device,
                    disable_auto_ppm=True,
                )
                dh = hail_stats.get("_decoded_hail")
                if dh is not None:
                    decoded_hail = dh
                    print(f"\n\033[32m  HAIL RECEIVED — preparing ACK\033[0m")
                    break
                if not hail_stats.get("ok", True):
                    stream_errors += 1
                    print(f"RX error ({stream_errors}/3): "
                          f"{hail_stats.get('error')}", file=sys.stderr)
                    if stream_errors >= 3:
                        return 2
                    time.sleep(1.0)

            # B: carry converged AGC gain into RLNC RX — skip warmup blocks.
            _converged_vga = hail_stats.get("final_vga_db", float(args.rx_vga))
            _hail_peak = hail_stats.get("_decode_peak_mag")
            if _hail_peak and _hail_peak > _AgcPpmState.AGC_TARGET:
                import math
                _adj_db = 10.0 * math.log10(_AgcPpmState.AGC_TARGET / _hail_peak)
                _converged_vga = max(0.0, _converged_vga + _adj_db)

            # ── Phase 2: TX ACK ───────────────────────────────────────
            _phase_header(2, "RESPOND TX", "ACK transmit",
                          f"{sc.ACK_FEC_TOTAL_BITS} channel bits/frame")
            if coord_active:
                print("  coord: hail decoded — telling caller to stop TX", flush=True)
                coord.send_switch()
                _coord_expect_switch(coord, "respond waiting caller stop after hail")
                print("  coord: caller stopped — starting ACK TX", flush=True)
            responder_eph = sc.Ephemeral()
            resp_eph_priv_peek = responder_eph.peek()
            dh2_sess = sc.ecdh(resp_eph_priv_peek, decoded_hail.caller_static_pub)
            dh3_sess = sc.ecdh(resp_eph_priv_peek, decoded_hail.caller_eph_pub)
            resp_eph_pub_can = sc.pubkey_to_compressed(responder_eph.pub)
            session_keys = sc.derive_session_keys(
                decoded_hail.dh1, dh2_sess, dh3_sess,
                decoded_hail.caller_eph_pub_canonical, resp_eph_pub_can,
            )

            ack_bits = sc.encode_ack_fec(responder_eph, decoded_hail, status=1)
            ack_chips = sf.tx_bits_to_chips(ack_bits)
            ack_samples = upsample_chips_to_samples(ack_chips, SAMPS_PER_CHIP)
            ack_frame_sec = len(ack_chips) / chip_rate_hz
            print(f"  TX ACK: {sc.ACK_FEC_TOTAL_BITS} channel bits "
                  f"({ack_frame_sec:.1f}s/frame), repeating until timeout")
            print(f"  nonce echoed:  {decoded_hail.body.body_nonce.hex()}")

            ack_early = False

            def _ack_gen():
                nonlocal ack_early
                _t0 = time.time()
                while time.time() - _t0 < ACK_TX_WINDOW:
                    yield ack_samples
                    if coord_active and coord.has_data():
                        _coord_expect_switch(coord, "respond ACK early-exit check")
                        print("  coord: caller decoded ACK — stopping early")
                        ack_early = True
                        yield ack_samples
                        return

            print(f"  TX ACK: continuous stream"
                  f"{', coord early-exit' if coord_active else f', {ACK_TX_WINDOW:.0f}s window'}",
                  flush=True)
            try:
                soapy_tx_streaming(
                    _ack_gen(), sdr.center_hz,
                    samp_hz=SAMP_RATE_HZ,
                    tx_vga_db=args.tx_vga,
                    tx_amp_on=args.tx_amp,
                    device=sdr.device,
                )
            except KeyboardInterrupt:
                print("  interrupted")
            print()
            print(f"\033[1;32m  ╔══════════════════════════════════════╗\033[0m")
            print(f"\033[1;32m  ║   HANDSHAKE COMPLETE — ACK SENT      ║\033[0m")
            print(f"\033[1;32m  ╚══════════════════════════════════════╝\033[0m")
            if coord_active:
                print(f"  coord: ACK TX done{' (early)' if ack_early else ''}"
                      f" — telling caller to TX payload", flush=True)
                coord.send_switch()

            # ── Phase 3: RLNC payload RX ──────────────────────────────
            k_symbols = args.rlnc_k
            from sparse_rlnc import fragment_payload as _frag

            _wire_payload_len = decoded_hail.body.payload_len
            expected_payload_len = (
                _wire_payload_len if _wire_payload_len > 0
                else (args.payload_len or len(DEMO_PAYLOAD))
            )
            if _wire_payload_len > 0:
                print(f"  payload_len from hail: {_wire_payload_len}B")
            else:
                print(f"  payload_len not in hail, defaulting to {expected_payload_len}B",
                      file=sys.stderr)
            frags = _frag(b'\x00' * expected_payload_len, k_symbols)
            frag_size = len(frags[0])
            n_sym_bytes = 4 + frag_size + 16

            rx_session = RLNCSession(b'\x00' * expected_payload_len, k_symbols, session_keys)
            _phase_header(
                3,
                "RESPOND RX",
                "RLNC payload receive",
                f"K={k_symbols}, expected={expected_payload_len}B, symbol={n_sym_bytes}B",
            )
            if _is_debug_output_enabled():
                print(f"  pre-seeded VGA={_converged_vga:.0f} dB, "
                      f"static PPM (no auto-retune)")

            received_count = 0
            _hail_freq_offset = hail_stats.get("_decode_freq_offset_hz", 0.0)
            if abs(_hail_freq_offset) < 1.0:
                _hail_freq_offset = (hail_stats.get("final_center_hz", sdr.center_hz)
                                     - sdr.center_hz)
            if abs(_hail_freq_offset) > 1.0 and _is_debug_output_enabled():
                print(f"  pre-seeded freq offset: {_hail_freq_offset:+.0f} Hz")

            def _payload_sym_fn(block_data):
                nonlocal received_count
                sym_results = sisl_rx.decode_all_payload_in_block(
                    block_data, n_sym_bytes,
                    samps_per_chip=2,
                    samp_hz=chip_rate_hz * 2,
                    signal_threshold=args.signal_threshold,
                    max_symbols_per_block=8,
                    freq_offset_hz=_hail_freq_offset if abs(_hail_freq_offset) > 1.0 else None,
                )
                acq_sentinel = None
                complete = False
                budget_exhausted = False
                n_decoded = 0
                base = {}
                for res in sym_results:
                    if "payload_frame_bytes" not in res:
                        acq_sentinel = res
                        continue
                    try:
                        complete = rx_session.rx_frame(res["payload_frame_bytes"])
                        received_count += 1
                        n_decoded += 1
                        comb_id = int.from_bytes(res["payload_frame_bytes"][:4], "big")
                        print(
                            f"\r  RLNC RX symbols: {received_count} "
                            f"(last comb_id={comb_id})",
                            end="",
                            flush=True,
                        )
                    except ValueError:
                        if sf.SISL_DEBUG:
                            raw = res["payload_frame_bytes"]
                            import struct as _s
                            _cid = _s.unpack(">I", raw[:4])[0]
                            sf.debug_telemetry(
                                "payload",
                                status="aead_fail",
                                comb_id=_cid,
                                frame_head=raw[:8].hex(),
                            )
                    if rx_session.decode_budget_exhausted():
                        budget_exhausted = True
                        break
                if budget_exhausted:
                    return {
                        **base,
                        "status": "budget_exhausted",
                        "stop_rx": True,
                        "stop_detail": rx_session.decode_failure_reason(),
                    }
                if complete:
                    return {**base, "status": "decrypt_ok",
                            "decoded_hail": True,
                            "polarity": "rlnc",
                            "body": f"{received_count} symbols"}
                base = acq_sentinel or (sym_results[0] if sym_results else {})
                if not sym_results or (acq_sentinel and n_decoded == 0):
                    status = "no_signal"
                elif n_decoded == 0:
                    status = "decrypt_fail"
                else:
                    status = "rlnc_partial"
                return {**base, "status": status}

            rlnc_rx_timeout = _compute_rlnc_rx_timeout(
                coord_active=coord_active,
                k_symbols=k_symbols,
                symbol_bytes=n_sym_bytes,
                chip_rate_hz=chip_rate_hz,
            )
            rlnc_center_hz = hail_stats.get("final_center_hz", sdr.center_hz)
            rlnc_stats = live_rx_decode(
                duration_s=rlnc_rx_timeout,
                block_seconds=3.0,
                lna_db=args.rx_lna,
                vga_db=args.rx_vga,
                amp_on=args.rx_amp,
                center_hz=rlnc_center_hz,
                device_name=args.device,
                signal_threshold=args.signal_threshold,
                samps_per_chip=active_samps_per_chip,
                exit_on_decrypt=True,
                decode_fn=_payload_sym_fn,
                initial_vga_db=_converged_vga,
                disable_auto_ppm=True,
                device=sdr.device,
                coord_fd=coord.fileno if coord_active else None,
                flush_after_tx=True,
            )
            if received_count > 0:
                print()

            recovered = rx_session.recovered_payload()
            if recovered is None:
                if rx_session.decode_budget_exhausted():
                    reason = rx_session.decode_failure_reason() or "decoder budget exhausted"
                    print(f"  RLNC RX aborted — {reason}", flush=True)
                    if coord_active:
                        return 1
                    continue
                if coord_active:
                    n_sym = rlnc_stats.get("hails_decrypted", 0)
                    print(f"  RLNC RX failed ({received_count} symbols,"
                          f" {n_sym} decrypted) — aborting (coord active)")
                    return 1
                print(f"  RLNC RX timeout — looping back to hail listen",
                      flush=True)
                continue

            payload_out = recovered
            out_path = args.payload_out
            with open(out_path, "wb") as _f:
                _f.write(payload_out)
            print(f"\033[1;32m  PAYLOAD RECEIVED ({len(payload_out)}B) → {out_path}\033[0m")
            print(f"  content: {payload_out[:80]}")

            ack_session = RLNCSession.for_responder(payload_out, k_symbols, session_keys)

            if coord_active:
                print("  coord: payload decoded — notifying caller", flush=True)
                coord.send_switch()
                _coord_expect_switch(coord, "respond waiting call TX stop or done")
                _coord_expect_switch(coord, "respond waiting call go-ahead for ACK")
                print("  coord: caller ready for payload ACK", flush=True)

            import time as _time
            _pack_n = [0]
            _MIN_ACK_FRAMES = 20

            def _payload_ack_gen():
                _t0 = _time.monotonic()
                while _time.monotonic() - _t0 < 120.0:
                    frame = ack_session.build_ack(seq=_pack_n[0])
                    bits = sc.encode_payload_symbol_fec(frame)
                    chips = sf.tx_bits_to_chips(bits)
                    yield upsample_chips_to_samples(chips, SAMPS_PER_CHIP)
                    _pack_n[0] += 1
                    if coord_active and _pack_n[0] >= _MIN_ACK_FRAMES and coord.has_data():
                        _coord_expect_switch(coord, "respond payload ACK early-exit check")
                        print("  coord: caller decoded payload ACK — stopping early")
                        yield upsample_chips_to_samples(chips, SAMPS_PER_CHIP)
                        return

            print(f"  TX payload ACK: continuous stream"
                  f"{', coord early-exit' if coord_active else ', 120s window'}",
                  flush=True)
            soapy_tx_streaming(
                _payload_ack_gen(), sdr.center_hz,
                samp_hz=SAMP_RATE_HZ,
                tx_vga_db=args.tx_vga,
                tx_amp_on=args.tx_amp,
                device=sdr.device,
            )
            print(f"  payload ACK TX complete ({_pack_n[0]} frames)")
            if coord_active:
                print("  coord: payload ACK done — session complete", flush=True)
                coord.send_switch()
            break
    return 0


def _run_call_mode(
    args: argparse.Namespace,
    *,
    coord,
    chip_rate_hz: int,
    active_samps_per_chip: int,
) -> int:
    coord_active = coord is not None
    caller_static = demo_caller_key()
    responder_static_pub = demo_responder_key().public_key()
    center_hz = args.freq * 1e6

    call_device_str = None
    if args.serial:
        call_device_str = f"driver=hackrf,serial={args.serial}"

    caller_eph = sc.Ephemeral()
    caller_eph_priv = caller_eph.peek()
    if args.payload:
        with open(args.payload, "rb") as _pf:
            payload_for_len = _pf.read()
    else:
        payload_for_len = DEMO_PAYLOAD
    body = sc.HailBody(
        caller_static_pub=sc.pubkey_to_compressed(
            caller_static.public_key()),
        center_freq_offset=100,
        bandwidth_code=0x03, mode=0x01,
        chip_rate_code=0x32,
        body_nonce=os.urandom(8),
        flags=0x03,
        payload_len=len(payload_for_len),
    )
    dh1 = sc.ecdh(caller_eph_priv, responder_static_pub)

    hail_bits = sc.encode_hail_fec(caller_eph, responder_static_pub, body)
    hail_chips = sf.tx_bits_to_chips(hail_bits)
    hail_samples = upsample_chips_to_samples(hail_chips, SAMPS_PER_CHIP)
    initial_tx_duration = 30.0

    ack_decode_fn = sisl_rx.make_ack_decode_fn(
        caller_static_priv=caller_static,
        caller_eph_priv=caller_eph_priv,
        dh1=dh1,
        expected_nonce_echo=body.body_nonce,
        samps_per_chip=2,
        samp_hz=chip_rate_hz * 2,
    )

    print(f"call: hailing on {args.freq:.1f} MHz")
    print(f"  nonce:         {body.body_nonce.hex()}")

    with SoapyDevice(args.device, device_str=call_device_str, center_hz=center_hz) as call_sdr:
        print(f"call: pinned to HackRF {call_sdr.serial.lstrip('0')[:16]} for TX")
        phase1_start_time = time.time()
        if coord_active:
            _phase_header(
                1,
                "CALL TX",
                "hail transmit",
                "continuous stream (checks for respond stop between frames)",
            )

            def _hail_generator():
                n = 0
                t0 = time.time()
                while True:
                    n += 1
                    yield hail_samples
                    if n % 5 == 0:
                        print(
                            f"\r  hail frames sent: {n} "
                            f"({time.time() - t0:.0f}s)",
                            end="",
                            flush=True,
                        )
                    if coord.has_data():
                        return

            n_hail = soapy_tx_streaming(
                _hail_generator(),
                call_sdr.center_hz,
                samp_hz=SAMP_RATE_HZ,
                tx_vga_db=args.tx_vga,
                tx_amp_on=args.tx_amp,
                device=call_sdr.device,
            )
            print(f"\r  hail frames sent: {n_hail} (final)", flush=True)
            _coord_expect_switch(coord, "call waiting hail decoded")
            print(f"  phase 1: respond decoded hail after "
                  f"{n_hail} frames — switching to RX", flush=True)
            coord.send_switch()
        else:
            pass_repeats = max(1, int(
                initial_tx_duration * chip_rate_hz / len(hail_chips)))
            _phase_header(
                1,
                "CALL TX",
                "hail transmit",
                f"{pass_repeats} repeats, {initial_tx_duration:.0f}s continuous",
            )
            print("  transmitting...",
                  end="", flush=True)
            soapy_tx_burst(
                hail_samples, call_sdr.center_hz,
                samp_hz=SAMP_RATE_HZ,
                tx_vga_db=args.tx_vga,
                tx_amp_on=args.tx_amp,
                repeats=pass_repeats,
                device=call_sdr.device,
            )
            print(" done", flush=True)

        phase2_center_hz = call_sdr.center_hz
        _phase_header(2, "CALL RX", "ACK listen",
                      f"up to {args.duration:.0f}s")
        ack_stats = live_rx_decode(
            duration_s=args.duration,
            block_seconds=3.0,
            lna_db=args.rx_lna,
            vga_db=args.rx_vga,
            amp_on=args.rx_amp,
            center_hz=phase2_center_hz,
            device_name=args.device,
            device=call_sdr.device,
            signal_threshold=args.signal_threshold,
            samps_per_chip=active_samps_per_chip,
            exit_on_decrypt=True,
            decode_fn=ack_decode_fn,
            coord_fd=coord.fileno if coord_active else None,
            flush_after_tx=True,
        )
        ack_recv_time = time.time()
        dh = ack_stats.get("_decoded_hail")
        if not (ack_stats.get("hails_decrypted", 0) > 0
                and isinstance(dh, sc.DecodedAck)):
            if coord_active and coord.has_data():
                _coord_expect_switch(coord, "call waiting ACK TX done after miss")
                print(f"\n  ACK not decoded — respond finished ACK TX")
            else:
                print(f"\n  timeout — no ACK received")
            return 1

        print()
        print(f"\033[1;32m  ╔══════════════════════════════════════╗\033[0m")
        print(f"\033[1;32m  ║  SESSION ESTABLISHED — ACK RECEIVED  ║\033[0m")
        print(f"\033[1;32m  ╚══════════════════════════════════════╝\033[0m",
              flush=True)

        if coord_active:
            print("  coord: ACK decoded — telling respond to stop ACK TX", flush=True)
            coord.send_switch()
            _coord_expect_switch(coord, "call waiting ACK TX done before payload TX")
            print("  coord: respond done — switching to TX payload", flush=True)
        else:
            resp_window_end = (phase1_start_time + initial_tx_duration + ACK_TX_WINDOW)
            phase3_ready_at = max(resp_window_end, ack_recv_time + 2.0)
            phase3_delay = phase3_ready_at - time.time()
            print(f"  waiting {phase3_delay:.1f}s for responder ACK window to expire...",
                  flush=True)
            if phase3_delay > 0:
                time.sleep(phase3_delay)

        dh2_sess = sc.ecdh(caller_static, dh.responder_eph_pub)
        resp_eph_pub_can = sc.pubkey_to_compressed(dh.responder_eph_pub)
        caller_eph_pub_can = sc.pubkey_to_compressed(
            caller_eph_priv.public_key())
        session_keys = sc.derive_session_keys(
            dh1, dh2_sess, dh.dh3,
            caller_eph_pub_can, resp_eph_pub_can,
        )
        k_symbols = args.rlnc_k
        if args.payload:
            with open(args.payload, "rb") as _f:
                payload = _f.read()
        else:
            payload = DEMO_PAYLOAD
        from sparse_rlnc import fragment_payload as _frag_cal
        _frags_cal = _frag_cal(payload, k_symbols)
        n_sym_bytes = 4 + len(_frags_cal[0]) + 16
        session = RLNCSession(payload, k_symbols, session_keys)

        payload_ack_bytes = 52
        n_fec_bits = sc.payload_fec_total_bits(n_sym_bytes)
        sym_chips_per_frame = n_fec_bits * sf.CHIPS_PER_SYMBOL
        sym_duration_s = sym_chips_per_frame / chip_rate_hz
        sym_repeats = 1
        _ = sym_repeats

        _phase_header(
            3,
            "CALL TX",
            "RLNC payload transmit",
            f"K={k_symbols}, payload={len(payload)}B, symbol={n_sym_bytes}B, "
            f"{sym_duration_s*1000:.0f}ms/symbol",
        )

        prk = sc.derive_session_prk(session_keys)
        _tx_key_caller = session_keys["p2p_tx_key"]
        rx_key = session_keys["p2p_rx_key"]
        sess_id = session_keys["session_id"]
        _ = (prk, _tx_key_caller, rx_key, sess_id)

        def _payload_ack_fn(block_data):
            res = sisl_rx.decode_one_payload_in_block(
                block_data, payload_ack_bytes,
                samps_per_chip=2,
                samp_hz=chip_rate_hz * 2,
                signal_threshold=args.signal_threshold,
            )
            if res.get("status") == "decrypt_ok":
                raw = res["payload_frame_bytes"]
                if session.verify_ack(raw):
                    return {**res, "status": "decrypt_ok",
                            "decoded_hail": True,
                            "polarity": "rlnc-ack"}
                if _is_debug_output_enabled() and len(raw) >= 4:
                    seq = int.from_bytes(raw[:4], "big")
                    print(f"  [DEBUG] payload ACK rejected (seq={seq})", flush=True)
                res["status"] = "ack_rejected"
            return res

        rlnc_tx_vga = (args.rlnc_tx_vga
                       if args.rlnc_tx_vga is not None
                       else args.tx_vga)

        n_warmup = 2
        n_coded = k_symbols + max(120, k_symbols * 8)
        total_sym = n_warmup + n_coded
        total_dur_s = total_sym * sym_duration_s
        payload_early = False

        def _encode_symbol_to_samples(frame: bytes) -> np.ndarray:
            bits = sc.encode_payload_symbol_fec(frame)
            chips = sf.tx_bits_to_chips(bits)
            return upsample_chips_to_samples(chips, SAMPS_PER_CHIP)

        def _symbol_generator():
            nonlocal payload_early
            for i in range(total_sym):
                yield _encode_symbol_to_samples(session.next_tx_frame())
                if (i + 1) % 4 == 0 or i + 1 == total_sym:
                    print(f"\r  RLNC TX symbols: {i+1}/{total_sym}",
                          end="", flush=True)
                if coord_active and i >= n_warmup and coord.has_data():
                    print(f"\n  coord: respond decoded payload after "
                          f"{i+1} symbols — stopping TX", flush=True)
                    payload_early = True
                    return

        print(f"  TX window: up to {total_sym} symbols "
              f"({total_dur_s:.0f}s max)")
        n_sent = soapy_tx_streaming(
            _symbol_generator(),
            call_sdr.center_hz,
            samp_hz=SAMP_RATE_HZ,
            tx_vga_db=rlnc_tx_vga,
            tx_amp_on=args.tx_amp,
            device=call_sdr.device,
        )
        print(f"\r  RLNC TX symbols: {n_sent}/{total_sym} done"
              f"{', early' if payload_early else ''}")
        if not _finalize_call_payload_coord(coord if coord_active else None, payload_early):
            return 1

        comb_id = n_sent
        phase4_center_hz = ack_stats.get("final_center_hz", call_sdr.center_hz)
        print(f"  TX complete ({comb_id} symbols total). "
              f"Listening for payload ACK...")
        phase4_vga = ack_stats.get("final_vga_db", float(args.rx_vga))
        rlnc_ack_stats = live_rx_decode(
            duration_s=120.0 if coord_active else max(60.0, args.duration),
            block_seconds=3.0,
            lna_db=args.rx_lna,
            vga_db=args.rx_vga,
            amp_on=args.rx_amp,
            center_hz=phase4_center_hz,
            device_name=args.device,
            device=call_sdr.device,
            signal_threshold=args.signal_threshold,
            samps_per_chip=active_samps_per_chip,
            exit_on_decrypt=True,
            decode_fn=_payload_ack_fn,
            initial_vga_db=phase4_vga,
            disable_auto_ppm=True,
            flush_after_tx=True,
        )

    if rlnc_ack_stats.get("hails_decrypted", 0) > 0:
        print(f"\033[1;32m  PAYLOAD DELIVERED AND ACKNOWLEDGED\033[0m")
        if coord_active:
            print("  coord: payload ACK decoded — telling respond to stop", flush=True)
            coord.send_switch()
            _coord_expect_switch(coord, "call waiting payload ACK TX done")
            print("  coord: session complete", flush=True)
    else:
        print(f"  timeout — payload ACK not received "
              f"after {comb_id} symbols TX'd")
    return 0


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
                        help=("runtime mode. Canonical live runtime is SoapySDR "
                              "(tx/rx/call/respond)."),
                        required=True)
    parser.add_argument("--capture", default="/tmp/sisl_rx.cfile",
                        help="capture file (input for offline, output for tx-to-file)")
    parser.add_argument("--duration", type=float, default=600.0,
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
    parser.add_argument("--tx-vga", type=int, default=None,
                        help="tx: HackRF TX VGA (IF gain, baseband "
                             "amplification before upconversion, 0..47 dB "
                             "in 1 dB steps) (default: band-calibrated minimum)")
    parser.add_argument("--rlnc-tx-vga", type=int, default=None,
                        help="tx: HackRF TX VGA for RLNC payload symbols only "
                             "(overrides --tx-vga for Phase 3; useful when "
                             "hail/ACK needs full power but RLNC needs lower "
                             "power to avoid close-range AGC clipping)")
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
                             "bands. tx and call/respond TX are always "
                             "HackRF in the canonical Soapy runtime.")
    parser.add_argument("--serial", type=str, default=None,
                        help="HackRF serial number to open (short or full). "
                             "Required when two HackRF devices are connected "
                             "so each process claims a distinct device.")
    parser.add_argument("--payload", type=str, default=None,
                        help="file path to send as RLNC payload after session "
                             "establishment (call mode). Responder saves "
                             "received payload to /tmp/sisl_rlnc_payload.bin. "
                             "Defaults to a built-in demo string.")
    parser.add_argument("--rlnc-k", type=int, default=16,
                        help="RLNC source block count K (default 16). "
                             "Both call and respond must use the same value.")
    parser.add_argument("--payload-len", type=int, default=None,
                        help="Expected payload length in bytes (respond mode). "
                             "Must match the caller's --payload file size. "
                             "Defaults to the built-in demo payload length.")
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
    parser.add_argument("--coord", type=str, default="auto",
                        help="TCP coordination for half-duplex TX/RX role swapping. "
                             "Format: host:port. Use 0.0.0.0:PORT to listen (call "
                             "side), or REMOTE_IP:PORT to connect (respond side). "
                             "Default: 0.0.0.0:4574 for call, 127.0.0.1:4574 for "
                             "respond. Use --no-coord to disable.")
    parser.add_argument("--no-coord", action="store_true",
                        help="Disable coordination channel (timing-based mode).")
    parser.add_argument("--payload-out", type=str,
                        default="/tmp/sisl_rlnc_payload.bin",
                        help="path where respond side writes received payload "
                             "(default /tmp/sisl_rlnc_payload.bin)")
    args = parser.parse_args()

    # ── Resolve tx-vga: use band-calibrated minimum if not specified ──────────
    if args.tx_vga is None:
        cal_vga, cal_amp = _get_band_min_vga(args.freq * 1e6)
        args.tx_vga = cal_vga
        if cal_amp and not args.tx_amp:
            args.tx_amp = True
            print(f"  tx-vga cal: {args.freq:.0f} MHz → vga={cal_vga} dB + amp (auto)")
        else:
            print(f"  tx-vga cal: {args.freq:.0f} MHz → vga={cal_vga} dB (auto)")

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
        min_block_sec = max(3.0, frame_sec * 1.5)
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

    # ── TCP coordination channel (--coord host:port) ─────────────────────
    # Half-duplex test harness: alternating-turns protocol via TCP.
    # Default on for call/respond; --no-coord disables.
    coord = None
    if args.mode in ("call", "respond") and not args.no_coord:
        _coord_str = args.coord
        if _coord_str == "auto":
            _coord_str = "0.0.0.0:4574" if args.mode == "call" else "127.0.0.1:4574"
        import sisl_coord as _coord_mod
        _coord_host, _, _coord_port = _coord_str.rpartition(":")
        _coord_port = int(_coord_port)
        if _coord_host in ("0.0.0.0", ""):
            coord = _coord_mod.listen(_coord_port)
            coord.wait_for_ready()
            print("  coord: respond side ready", flush=True)
        else:
            coord = _coord_mod.connect(_coord_host, _coord_port)
            coord.send_ready()
            print("  coord: ready, waiting for hail", flush=True)

    if args.mode == "respond":
        return _run_respond_mode(
            args,
            coord=coord,
            chip_rate_hz=chip_rate_hz,
            active_samps_per_chip=active_samps_per_chip,
        )

    if args.mode == "call":
        return _run_call_mode(
            args,
            coord=coord,
            chip_rate_hz=chip_rate_hz,
            active_samps_per_chip=active_samps_per_chip,
        )

    # mode == "tx" (canonical Soapy-only path)
    if args.tx_preamble:
        frame = sc.ASM
        chips = sf.tx_bytes_to_chips(frame)
    else:
        chips, frame = build_demo_hail_fec_chips()
    samples = upsample_chips_to_samples(chips, active_samps_per_chip)
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
    _device_str = f"driver=hackrf,serial={args.serial}" if args.serial else None
    with SoapyDevice("hackrf", device_str=_device_str, center_hz=args.freq * 1e6) as tx_sdr:
        t_start = time.time()

        def _tx_frames():
            while time.time() - t_start < args.duration:
                yield samples

        n_frames = soapy_tx_streaming(
            _tx_frames(),
            tx_sdr.center_hz,
            samp_hz=SAMP_RATE_HZ,
            tx_vga_db=args.tx_vga,
            tx_amp_on=args.tx_amp,
            device=tx_sdr.device,
        )
    print(f"done ({n_frames} frame{'s' if n_frames != 1 else ''} sent)")
    return 0


if __name__ == "__main__":
    import signal
    _sigint_count = 0
    def _sigint_handler(sig, frame):
        global _sigint_count
        _sigint_count += 1
        if _sigint_count >= 2:
            print("\n  force exit", flush=True)
            os._exit(130)
        print("\n  interrupted — Ctrl-C again to force exit", flush=True)
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
