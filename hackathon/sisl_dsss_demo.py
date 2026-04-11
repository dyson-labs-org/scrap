"""Phase 1: SISL DSSS hidden-signal demo.

GNU Radio top-block that drives two HackRF units through the SISL public
hailing code and shows that the signal is below the noise floor to a naive
observer but recovers cleanly to a receiver with the correct spreading code.

Per Hackathon.md §1 and §Signal Parameters:

    Center frequency: 2437 MHz  (WiFi channel 6 — "hide in WiFi noise")
    Chip rate:        1 Mcps
    Sample rate:      2.4 Msps (Nyquist + margin)
    Samples/chip:     2.4  → zero-order-hold upsample
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
SAMP_RATE_HZ = 2_400_000                # 2.4 Msps
SAMPS_PER_CHIP = SAMP_RATE_HZ / CHIP_RATE_HZ     # 2.4 — fractional
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
                        1.0, "driver=hackrf", "", 1, "fc32", "", [""]
                    )
                    self._sink.set_sample_rate(0, SAMP_RATE_HZ)
                    self._sink.set_frequency(0, CENTER_FREQ_HZ)
                    self._sink.set_gain(0, HACKRF_TX_GAIN_DB)
                else:
                    # Fallback: file sink so something exists without SoapySDR
                    self._sink = blocks.file_sink(
                        gr.sizeof_gr_complex, "/tmp/sisl_tx.cfile"
                    )
                self.connect(self._src, self._sink)

            elif mode == "rx":
                if _HAVE_SOAPY:
                    self._src = soapy.source(
                        1.0, "driver=hackrf", "", 1, "fc32", "", [""]
                    )
                    self._src.set_sample_rate(0, SAMP_RATE_HZ)
                    self._src.set_frequency(0, CENTER_FREQ_HZ)
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


# ── Offline despread utility ────────────────────────────────────────────────

def offline_despread(cfile_path: str, n_bytes: int,
                     samps_per_chip: float = SAMPS_PER_CHIP) -> bytes:
    """Read a complex64 capture, decimate to chips, despread.

    Assumes:
      - chip-0 alignment at the start of the file (Phase 1 simplification)
      - one symbol period = CHIPS_PER_SYMBOL * samps_per_chip samples
      - real-valued information on the I channel only (the demo TX uses
        zero-imaginary BPSK)
    """
    raw = np.fromfile(cfile_path, dtype=np.complex64)
    i_component = raw.real.astype(np.float32)

    # Integer-decimate by nearest-int samps_per_chip (coarse)
    n_int = int(round(samps_per_chip))
    decimated = i_component[::n_int]
    # Sign → ±1 chips
    chips = np.sign(decimated).astype(np.int8)
    chips[chips == 0] = 1
    return sf.rx_chips_to_bytes(chips, n_bytes)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="SISL Phase 1 DSSS demo")
    parser.add_argument("--mode", choices=("tx", "rx", "offline"),
                        required=True)
    parser.add_argument("--message", default="SISL HELLO WORLD")
    parser.add_argument("--capture", default="/tmp/sisl_rx.cfile",
                        help="RX capture file for offline decode")
    parser.add_argument("--duration", type=float, default=10.0,
                        help="seconds to run tx or rx")
    args = parser.parse_args()

    if args.mode == "offline":
        msg = args.message.encode()
        data = offline_despread(args.capture, n_bytes=len(msg))
        print(f"recovered: {data!r}")
        print(f"match:     {data == msg}")
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
