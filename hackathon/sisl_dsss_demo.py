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

Usage:
    python hackathon/sisl_dsss_demo.py --mode tx --message "SISL HELLO"
    python hackathon/sisl_dsss_demo.py --mode rx

Requires:
    gnuradio (tested on 3.10+)
    gr-soapy or gr-osmosdr for HackRF access
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

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

CENTER_FREQ_HZ = 2_437_000_000          # WiFi ch 6
CHIP_RATE_HZ = 1_000_000                # 1 Mcps
SAMP_RATE_HZ = 8_000_000                # 8 Msps (HackRF supported integer rate)
SAMPS_PER_CHIP = SAMP_RATE_HZ // CHIP_RATE_HZ    # 8 — integer
HACKRF_TX_GAIN_DB = 0                   # minimum
HACKRF_RX_VGA_DB = 20                   # conservative
HACKRF_RX_LNA_DB = 16                   # conservative


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

        def __init__(self, mode: str, message: bytes,
                     hackrf_device: str = "hackrf=0"):
            gr.top_block.__init__(self, "SISL DSSS Hidden Signal Demo")

            self.mode = mode
            self.message = message

            if mode == "tx":
                chips = build_tx_chips(message)
                # Repeat the message indefinitely so the RX can lock at any time
                samples = upsample_chips_to_samples(chips)
                self._src = blocks.vector_source_c(
                    samples.tolist(), repeat=True, vlen=1
                )
                if _HAVE_SOAPY:
                    self._sink = soapy.sink(
                        "driver=hackrf", "fc32", 1, "", "", [""], [""]
                    )
                    self._sink.set_sample_rate(0, SAMP_RATE_HZ)
                    self._sink.set_frequency(0, CENTER_FREQ_HZ)
                    self._sink.set_gain(0, "AMP", False)
                    self._sink.set_gain(0, "VGA", HACKRF_TX_GAIN_DB)
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
                    self._src.set_frequency(0, CENTER_FREQ_HZ)
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
        end = idx + 100                           # HAIL_FRAME_LEN
        return {
            "asm_offset": idx,
            "version": version,
            "msg_type": msg_type,
            "frame_type": "hail",
            "frame_bytes": data[idx:end] if end <= len(data) else None,
        }
    if msg_type == 0x02:                          # ack
        end = idx + 95                            # ACK_FRAME_LEN
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
    parser = argparse.ArgumentParser(description="SISL Phase 1 DSSS demo")
    parser.add_argument("--mode",
                        choices=("tx", "rx", "tx-to-file", "offline"),
                        required=True)
    parser.add_argument("--message", default=None,
                        help="tx/tx-to-file: payload bytes; "
                             "offline: optional expected substring to verify")
    parser.add_argument("--capture", default="/tmp/sisl_rx.cfile",
                        help="capture file (input for offline, output for tx-to-file)")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="seconds to run tx or rx")
    parser.add_argument("--prefix-ms", type=float, default=0.0,
                        help="tx-to-file: leading silence in ms")
    parser.add_argument("--repeats", type=int, default=1,
                        help="tx-to-file: message repetitions")
    parser.add_argument("--max-search-chips", type=int, default=None,
                        help="offline: bound the acquisition search window")
    parser.add_argument("--max-bytes", type=int, default=None,
                        help="offline: stop decoding after N bytes")
    args = parser.parse_args()

    if args.mode == "tx-to-file":
        msg = (args.message or "SISL HELLO WORLD").encode()
        n = tx_to_file(msg, args.capture,
                       prefix_ms=args.prefix_ms, repeats=args.repeats)
        print(f"wrote {n} complex64 samples ({n * 8} bytes) to {args.capture}")
        print(f"  message: {msg!r}")
        print(f"  prefix:  {args.prefix_ms} ms, repeats: {args.repeats}")
        return 0

    if args.mode == "offline":
        data, offset = offline_despread(
            args.capture,
            max_search_chips=args.max_search_chips,
            max_bytes=args.max_bytes,
        )
        lock_state = "locked" if offset is not None else "NO LOCK — fallback to chip 0"
        print(f"acquisition: {lock_state}")
        if offset is not None:
            print(f"  offset:  {offset} chips "
                  f"({offset / CHIP_RATE_HZ * 1000:.1f} ms into capture)")
        print(f"  decoded: {len(data)} bytes")
        print()

        frame = identify_sisl_frame(data)
        if frame is not None:
            print(f"SISL v3 frame detected:")
            print(f"  asm at byte: {frame['asm_offset']}")
            print(f"  version:     0x{frame['version']:02x}")
            print(f"  msg type:    0x{frame['msg_type']:02x} ({frame['frame_type']})")
            if frame["frame_bytes"] is not None:
                print(f"  frame hex:   {frame['frame_bytes'].hex()}")
        else:
            print(f"No SISL frame ASM found in decoded bytes.")
            print(f"  first 64: {data[:64]!r}")

        if args.message:
            expected = args.message.encode()
            if expected in data:
                idx = data.index(expected)
                print(f"\nexpected substring {expected!r}: found at byte {idx}")
                return 0
            else:
                print(f"\nexpected substring {expected!r}: NOT FOUND")
                return 1
        return 0

    if not _HAVE_GR:
        print("gnuradio not installed — run after:")
        print("  sudo pacman -S gnuradio gnuradio-companion "
              "soapysdr soapysdr-hackrf")
        return 2

    tb = DSSSHiddenSignalTop(args.mode, args.message.encode())
    tb.start()
    time.sleep(args.duration)
    tb.stop()
    tb.wait()
    print(f"done; capture at /tmp/sisl_{args.mode}.cfile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
