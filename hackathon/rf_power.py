#!/usr/bin/env python3
"""Quick RF power check at the SISL center frequency.

Opens the HackRF via SoapySDR, tunes to 2437 MHz, reads a fixed chunk
of samples every ~0.5 s, and prints a single line showing:

    t       — seconds since start
    peak    — maximum instantaneous |I+jQ| in dBFS
    rms     — RMS level in dBFS (the noise/signal floor)
    headrm  — distance from ADC saturation (larger = quieter)
    ratio   — peak / rms linear ratio (signal presence indicator)

Interpretation:

    TX OFF, noise only:
        peak ≈ -35..-50  rms ≈ -55..-70  headrm >= 30  ratio ≈ 2..10
    TX ON, signal present:
        peak jumps 20-40 dB higher than OFF baseline
        rms may also jump if signal dominates
        ratio typically still < 20 (DSSS signal looks noise-like in
        raw samples — processing gain is what separates it)

The important visual cue is the PEAK jumping when you start the TX.
Run this on the RX machine, run `--mode tx` on the other machine, and
watch the peak column. A ≥10 dB jump at TX-on is conclusive; anything
less means TX is not reaching the RX antenna.

Usage:
    python hackathon/rf_power.py                 # 30 s at default gain
    python hackathon/rf_power.py 60              # 60 s
    python hackathon/rf_power.py 60 --lna 8 --vga 10   # low-gain for antennas
    python hackathon/rf_power.py 60 --freq 2484  # override center freq

Dependencies: SoapySDR Python bindings + a HackRF.
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
except ImportError:
    print("SoapySDR Python bindings not available. Install:", file=sys.stderr)
    print("  Arch:   sudo pacman -S python-soapysdr", file=sys.stderr)
    print("  Other:  pip install soapysdr  (may require system libs)",
          file=sys.stderr)
    sys.exit(2)


def watch(
    duration_s: float,
    center_hz: float,
    samp_hz: float,
    lna_db: int,
    vga_db: int,
    amp_on: bool,
    samples_per_measurement: int,
    period_s: float,
) -> int:
    dev = SoapySDR.Device("driver=hackrf")
    dev.setSampleRate(SOAPY_SDR_RX, 0, samp_hz)
    dev.setFrequency(SOAPY_SDR_RX, 0, center_hz)
    dev.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if amp_on else 0.0)
    dev.setGain(SOAPY_SDR_RX, 0, "LNA", float(lna_db))
    dev.setGain(SOAPY_SDR_RX, 0, "VGA", float(vga_db))

    print(f"watching {center_hz/1e6:.1f} MHz at {samp_hz/1e6:.1f} Msps  "
          f"LNA={lna_db} VGA={vga_db} AMP={'on' if amp_on else 'off'}")
    print(f"measuring {samples_per_measurement} samples "
          f"(~{samples_per_measurement/samp_hz*1000:.1f} ms) every "
          f"{period_s:.1f} s")
    print()
    print(f"{'t(s)':>6}  {'peak(dBFS)':>10}  {'rms(dBFS)':>10}  "
          f"{'headrm':>8}  {'ratio':>6}  notes")
    print("-" * 70)

    stream = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
    dev.activateStream(stream)

    buf = np.empty(samples_per_measurement, dtype=np.complex64)
    t0 = time.time()
    baseline_peak = None

    try:
        while time.time() - t0 < duration_s:
            filled = 0
            while filled < samples_per_measurement:
                sr = dev.readStream(
                    stream,
                    [buf[filled:]],
                    samples_per_measurement - filled,
                    timeoutUs=1_000_000,
                )
                if sr.ret > 0:
                    filled += sr.ret
                elif sr.ret == -1:             # SOAPY_SDR_TIMEOUT
                    break
                elif sr.ret == -4:             # SOAPY_SDR_OVERFLOW
                    continue
                else:
                    print(f"readStream error {sr.ret}", file=sys.stderr)
                    break
            if filled < samples_per_measurement // 2:
                continue

            mag = np.abs(buf[:filled]).astype(np.float64)
            peak_lin = float(mag.max())
            rms_lin = float(np.sqrt(np.mean(mag * mag)))

            # Complex float samples are in roughly [-1, 1] per axis after
            # SoapyHackRF normalization, so |c| full-scale is sqrt(2).
            full_scale = np.sqrt(2.0)
            peak_db = 20 * np.log10(peak_lin / full_scale + 1e-12)
            rms_db = 20 * np.log10(rms_lin / full_scale + 1e-12)
            headroom = -peak_db       # distance from saturation
            ratio = peak_lin / (rms_lin + 1e-12)

            elapsed = time.time() - t0

            notes = ""
            if baseline_peak is None:
                baseline_peak = peak_db
                notes = "(baseline)"
            else:
                delta = peak_db - baseline_peak
                if delta > 10:
                    notes = f"+{delta:.0f} dB vs baseline — SIGNAL"
                elif delta < -10:
                    notes = f"{delta:.0f} dB vs baseline — quieter"
                elif abs(delta) > 3:
                    notes = f"{delta:+.0f} dB vs baseline"

            if peak_db > -3:
                notes += " SATURATING!"

            print(f"{elapsed:6.1f}  {peak_db:10.1f}  {rms_db:10.1f}  "
                  f"{headroom:7.1f}  {ratio:6.1f}  {notes}")

            time.sleep(period_s)
    except KeyboardInterrupt:
        print("\n(interrupted)")
    finally:
        dev.deactivateStream(stream)
        dev.closeStream(stream)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("duration", nargs="?", type=float, default=30.0,
                   help="total duration in seconds (default 30)")
    p.add_argument("--freq", type=float, default=2437.0,
                   help="center frequency in MHz (default 2437 = WiFi ch6)")
    p.add_argument("--rate", type=float, default=8.0,
                   help="sample rate in Msps (default 8)")
    p.add_argument("--lna", type=int, default=16,
                   help="HackRF LNA gain in dB (default 16)")
    p.add_argument("--vga", type=int, default=20,
                   help="HackRF VGA gain in dB (default 20)")
    p.add_argument("--amp", action="store_true",
                   help="enable HackRF 14 dB RF AMP (off by default)")
    p.add_argument("--samples", type=int, default=1 << 18,
                   help="samples per measurement (default 262144)")
    p.add_argument("--period", type=float, default=0.5,
                   help="seconds between measurements (default 0.5)")
    args = p.parse_args()

    return watch(
        duration_s=args.duration,
        center_hz=args.freq * 1e6,
        samp_hz=args.rate * 1e6,
        lna_db=args.lna,
        vga_db=args.vga,
        amp_on=args.amp,
        samples_per_measurement=args.samples,
        period_s=args.period,
    )


if __name__ == "__main__":
    sys.exit(main())
