#!/usr/bin/env python3
"""AWGN BER waterfall for sisl_fec.decode — validation of rate-1/2 K=9.

Sweeps Es/N0 from −2 dB to +6 dB in 0.5 dB steps. At each point, runs
200 trials of (encode 1000 random bits → add AWGN → decode) and
measures BER. Compares against uncoded BPSK Q(sqrt(2·Es/N0)) at the
same Es/N0.

Expected coded performance: BER ≈ 1e-4 at Es/N0 ≈ 3 dB, which is
approximately 5 dB better than uncoded BPSK at the same BER
(uncoded BPSK needs Es/N0 ≈ 8.4 dB for BER = 1e-4).

Usage:
    python bench_fec.py                         # default sweep
    python bench_fec.py --trials 500 --bits 2000
    python bench_fec.py --plot                  # if matplotlib present
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np

import sisl_fec as fec


def _uncoded_bpsk_ber(es_n0_db: float) -> float:
    """BER of uncoded BPSK over AWGN: Q(sqrt(2·Es/N0)).

    Q(x) = 0.5·erfc(x/sqrt(2)).
    """
    es_n0 = 10.0 ** (es_n0_db / 10.0)
    arg = math.sqrt(2.0 * es_n0)
    return 0.5 * math.erfc(arg / math.sqrt(2.0))


def _measure_coded_ber(n_bits: int, es_n0_db: float,
                        n_trials: int, seed: int) -> tuple[float, int, int]:
    """Encode n_bits, add AWGN at Es/N0, decode. Return (ber, errs, total)."""
    rng = np.random.default_rng(seed)
    es_n0 = 10.0 ** (es_n0_db / 10.0)
    sigma = math.sqrt(1.0 / (2.0 * es_n0))
    total_errors = 0
    total_bits = 0
    for _ in range(n_trials):
        payload = rng.integers(0, 2, size=n_bits).astype(np.uint8)
        coded = fec.encode(payload)
        symbols = (1.0 - 2.0 * coded.astype(np.float32))
        noise = rng.normal(0.0, sigma,
                            size=symbols.shape).astype(np.float32)
        y = symbols + noise
        llrs = y
        recovered = fec.decode(llrs, n_payload_bits=n_bits)
        total_errors += int(np.sum(recovered != payload))
        total_bits += n_bits
    ber = total_errors / total_bits if total_bits else float("nan")
    return ber, total_errors, total_bits


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snr-lo", type=float, default=-2.0,
                   help="lowest Es/N0 in dB (default −2)")
    p.add_argument("--snr-hi", type=float, default=6.0,
                   help="highest Es/N0 in dB (default +6)")
    p.add_argument("--snr-step", type=float, default=0.5)
    p.add_argument("--trials", type=int, default=200,
                   help="trials per Es/N0 point (default 200)")
    p.add_argument("--bits", type=int, default=1000,
                   help="payload bits per trial (default 1000)")
    p.add_argument("--plot", action="store_true",
                   help="save a waterfall plot to /tmp/sisl_fec_waterfall.png")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    snr_points = np.arange(args.snr_lo,
                             args.snr_hi + 1e-9,
                             args.snr_step)
    print(f"bench_fec: sweep Es/N0 {args.snr_lo:+.1f} to {args.snr_hi:+.1f} dB "
          f"in {args.snr_step:.1f} dB steps")
    print(f"  trials per point: {args.trials}, payload bits per trial: {args.bits}")
    print()

    header = (f"{'Es/N0 (dB)':>11}  {'coded BER':>13}  "
              f"{'uncoded BER':>13}  {'gain (dB)':>10}  {'errs':>7}")
    print(header)
    print("-" * len(header))

    coded_bers = []
    uncoded_bers = []
    t0 = time.time()
    seed = args.seed
    for es_n0 in snr_points:
        ber_coded, errs, total = _measure_coded_ber(
            args.bits, float(es_n0), args.trials, seed,
        )
        seed += 1
        ber_uncoded = _uncoded_bpsk_ber(float(es_n0))
        # Gain in dB: how much higher Es/N0 the uncoded curve would need
        # to reach the same BER. Computed numerically by inverting the
        # Q function — skip when the coded BER is effectively zero.
        if ber_coded > 0:
            # Find es_n0 such that Q(sqrt(2·es_n0)) = ber_coded.
            # Q(x) = ber_coded  →  x = sqrt(2) · erfinv(1 − 2·ber_coded)
            from math import erfc                 # noqa: F401
            # Numerical inversion:
            lo, hi = -10.0, 20.0
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                if _uncoded_bpsk_ber(mid) > ber_coded:
                    lo = mid
                else:
                    hi = mid
            equivalent_uncoded_db = 0.5 * (lo + hi)
            gain_db = equivalent_uncoded_db - float(es_n0)
            gain_str = f"{gain_db:+7.2f}"
        else:
            gain_str = "    ∞"
        print(f"{float(es_n0):+11.1f}  {ber_coded:13.3e}  "
              f"{ber_uncoded:13.3e}  {gain_str:>10}  {errs:7d}")
        coded_bers.append(ber_coded)
        uncoded_bers.append(ber_uncoded)
    elapsed = time.time() - t0
    print()
    print(f"total time: {elapsed:.1f} s")
    print()

    # Find where coded BER crosses 1e-4 (by linear interpolation in dB).
    # Useful shortcut for the gate check.
    coded_arr = np.array(coded_bers)
    if np.any(coded_arr <= 1e-4) and np.any(coded_arr > 1e-4):
        # Locate adjacent pair bracketing the 1e-4 crossing
        above = np.where(coded_arr > 1e-4)[0]
        below = np.where(coded_arr <= 1e-4)[0]
        if len(above) > 0 and len(below) > 0:
            i0 = int(above[-1])
            i1 = int(below[0])
            # Interpolate in log-BER vs linear-dB
            if coded_arr[i0] > 0 and coded_arr[i1] > 0:
                x0, x1 = snr_points[i0], snr_points[i1]
                y0, y1 = math.log10(coded_arr[i0]), math.log10(coded_arr[i1])
                target = math.log10(1e-4)
                crossing = x0 + (target - y0) * (x1 - x0) / (y1 - y0)
                # Equivalent uncoded Es/N0 at 1e-4: ~8.4 dB
                uncoded_crossing = 8.4
                coding_gain = uncoded_crossing - crossing
                print(f"coded BER = 1e-4 near Es/N0 ≈ {crossing:+.2f} dB")
                print(f"uncoded BER = 1e-4 at Es/N0 ≈ {uncoded_crossing:+.2f} dB")
                print(f"coding gain at 1e-4: ≈ {coding_gain:+.2f} dB")
                if coding_gain >= 4.5:
                    print(f"PASS: coding gain ≥ 4.5 dB at 1e-4 BER")
                else:
                    print(f"FAIL: coding gain < 4.5 dB at 1e-4 BER")
                    return 1
    else:
        print("WARNING: coded BER does not bracket 1e-4 in this sweep;")
        print("  extend the SNR range or increase trials.")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.semilogy(snr_points, np.clip(coded_arr, 1e-9, None),
                         marker="o", label="rate-1/2 K=9 coded")
            ax.semilogy(snr_points, uncoded_bers,
                         marker="s", linestyle="--",
                         label="uncoded BPSK Q(√(2·Es/N0))")
            ax.axhline(1e-4, color="gray", linestyle=":", linewidth=0.7)
            ax.set_xlabel("Es/N0 (dB)")
            ax.set_ylabel("BER")
            ax.set_title("sisl_fec rate-1/2 K=9 soft Viterbi — AWGN")
            ax.grid(True, which="both", linestyle=":")
            ax.legend()
            out = "/tmp/sisl_fec_waterfall.png"
            fig.savefig(out, dpi=120, bbox_inches="tight")
            print(f"plot saved to {out}")
        except ImportError:
            print("matplotlib not installed; skipping --plot")

    return 0


if __name__ == "__main__":
    sys.exit(main())
