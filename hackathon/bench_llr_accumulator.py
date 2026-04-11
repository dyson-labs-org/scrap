#!/usr/bin/env python3
"""AWGN validation for the LLR chase-combining accumulator.

Hypothesis under test: for N independent AWGN copies of the same SISL
hail at per-copy symbol SNR γ_s, LLR accumulation via the coherent-
decode pipeline gives effective SNR γ_s + 10·log10(N). In particular,
doubling N should drop the frame error rate (FER) by ~3 dB of
waterfall movement, and N=4 should rescue blocks that single-copy
decode cannot.

This is the gate the FEC reviewer asked for: if √N gain does not
appear in this simulation, the chase-combining architecture (KSP-WCC
§4.6) is moot and no amount of polar coding rescues it.

The sim deliberately BYPASSES the per-symbol tracker and the block-
level signal threshold in `_decode_one_hail_in_block`. Those stages
have their own (separate) failure modes at low SNR that hide the
accumulator's behavior. The test isolates the accumulator by:

  1. TX: build_demo_hail → build_tx_chips → upsample_chips_to_samples
  2. AWGN noise at the sample level at known symbol SNR
  3. Run the real matched filter (sisl_framer.matched_filter_complex_sample_rate)
  4. Extract peak_values at deterministic symbol boundaries (we know
     the TX started at sample 0) — NO tracker, NO lock floor
  5. Run the real coherent decode pipeline
     (sisl_framer.coherent_decode_from_pilot) to produce LLRs
  6. Feed into LlrAccumulator.try_add / try_decrypt after each copy

No mocks; uses the exact primitives the RX path uses, just without
the tracker short-circuit.

Usage:
    python bench_llr_accumulator.py                   # default sweep
    python bench_llr_accumulator.py --snr 0 -3 -6 -9  # custom symbol SNRs
    python bench_llr_accumulator.py --trials 30       # more averaging
    python bench_llr_accumulator.py --max-n 16        # deeper combining
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sisl_crypto as sc
import sisl_dsss_demo as dd
import sisl_framer as sf


SAMP_HZ = 2_000_000.0
SAMPS_PER_CHIP = 2
CHIPS_PER_SYMBOL = sf.CHIPS_PER_SYMBOL     # 1023
SAMPLES_PER_SYMBOL = CHIPS_PER_SYMBOL * SAMPS_PER_CHIP


def _symbol_snr_to_noise_std(snr_db: float) -> float:
    """Return per-axis Gaussian σ for complex AWGN at the given symbol SNR.

    TX signal is BPSK ±1 at the chip level, zero-order-hold upsampled to
    SAMPS_PER_CHIP samples per chip, emitted as real-valued complex64
    (imaginary = 0). Each chip has energy SAMPS_PER_CHIP (|s|²=1 over
    SAMPS_PER_CHIP samples). A symbol spans CHIPS_PER_SYMBOL chips, so
    symbol energy E_s = CHIPS_PER_SYMBOL · SAMPS_PER_CHIP.

    Coherent matched-filter integration over one symbol (CHIPS_PER_SYMBOL
    · SAMPS_PER_CHIP samples) yields signal power E_s² / σ⁴ · (stuff...);
    the simpler route is to solve σ² from the wanted post-despread
    symbol SNR:

        γ_s = E_s / N0     (single-sided)
            = (CHIPS_PER_SYMBOL · SAMPS_PER_CHIP) / σ_total²

    where σ_total² = σ_re² + σ_im² is the per-sample complex noise power
    and the sample-rate IS the noise bandwidth. Solving:
        σ_total² = CHIPS_PER_SYMBOL · SAMPS_PER_CHIP / 10^(γ_s/10)
        σ_axis = sqrt(σ_total² / 2)
    """
    lin = 10.0 ** (snr_db / 10.0)
    total = CHIPS_PER_SYMBOL * SAMPS_PER_CHIP / lin
    return float(np.sqrt(total / 2.0))


def _extract_peaks_known_alignment(
    samples: np.ndarray,
    n_bits: int,
) -> np.ndarray:
    """Run matched filter, extract one peak per symbol at deterministic
    sample positions. Bypasses the tracker completely.

    In simulation we know the TX started at sample 0. The matched
    filter uses a reversed kernel with mode='valid', so output index 0
    is the correlation across samples [0, SAMPLES_PER_SYMBOL) i.e. the
    start of the first symbol. Symbol k's peak lives at output index
    k · SAMPLES_PER_SYMBOL.
    """
    corr_c = sf.matched_filter_complex_sample_rate(
        samples, SAMPS_PER_CHIP,
    )
    if len(corr_c) == 0:
        return np.zeros(0, dtype=np.complex128)
    peaks = np.zeros(n_bits, dtype=np.complex128)
    for k in range(n_bits):
        target = k * SAMPLES_PER_SYMBOL
        if target >= len(corr_c):
            return peaks[:k]
        # Check the immediate neighborhood for the true peak (noise may
        # push it ±1 sample). Bracketed argmax over ±2 samples.
        lo = max(0, target - 2)
        hi = min(len(corr_c), target + 3)
        mag = np.abs(corr_c[lo:hi])
        local = int(np.argmax(mag))
        peaks[k] = corr_c[lo + local]
    return peaks


def _make_noisy_copy(tx_samples: np.ndarray, snr_db: float,
                      rng: np.random.Generator) -> np.ndarray:
    sigma_axis = _symbol_snr_to_noise_std(snr_db)
    n = len(tx_samples)
    noise = (rng.normal(0.0, sigma_axis, n).astype(np.float32)
             + 1j * rng.normal(0.0, sigma_axis, n).astype(np.float32))
    return (tx_samples + noise).astype(np.complex64)


def _decode_one_copy(
    tx_samples: np.ndarray,
    responder_static,
    snr_db: float,
    rng: np.random.Generator,
) -> dict:
    """Produce the same fields LlrAccumulator.try_add expects, without
    running the full _decode_one_hail_in_block (which short-circuits
    at low SNR due to the tracker)."""
    noisy = _make_noisy_copy(tx_samples, snr_db, rng)
    n_bits = sc.HAIL_FRAME_LEN * 8
    peaks = _extract_peaks_known_alignment(noisy, n_bits)
    if len(peaks) < n_bits:
        return {"status": "short_block"}

    # Full pilot-fit coherent decode at the known alignment.
    coherent = sf.coherent_decode_from_pilot(
        peaks, 0, dd._PILOT_BITS, n_bits,
    )
    if coherent is None:
        return {"status": "no_fit"}
    c_frame, c_soft, c_theta0, c_delta, c_rms = coherent
    # ASM error count, for gate consistency with the production path
    c_bits_first32 = np.unpackbits(
        np.frombuffer(c_frame[:4], dtype=np.uint8))
    c_asm_errs = int(np.sum(c_bits_first32 != dd._ASM_BITS))

    # Single-copy decrypt check
    # Also try the 6 XOR candidates (matches production)
    def _xor_alt(b, e, o):
        out = bytearray(len(b))
        for i, x in enumerate(b):
            out[i] = x ^ (e if i % 2 == 0 else o)
        return bytes(out)
    candidates = [
        c_frame,
        bytes(x ^ 0xFF for x in c_frame),
        bytes(x ^ 0xAA for x in c_frame),
        bytes(x ^ 0x55 for x in c_frame),
        _xor_alt(c_frame, 0x55, 0xAA),
        _xor_alt(c_frame, 0xAA, 0x55),
    ]
    solo_decrypt = False
    for cand in candidates:
        if sc.decode_hail(cand, responder_static) is not None:
            solo_decrypt = True
            break

    return {
        "status": "frame_soft" if not solo_decrypt else "decrypt_ok",
        "llrs": c_soft,
        "c_frame": c_frame,
        "phase_rms_residual_rad": c_rms,
        "asm_errs_in_coherent": c_asm_errs,
        "solo_decrypt": solo_decrypt,
    }


def _run_one_trial(
    tx_samples: np.ndarray,
    responder_static,
    snr_db: float,
    max_n: int,
    rng: np.random.Generator,
) -> dict:
    accumulator = dd.LlrAccumulator(
        n_bits=sc.HAIL_FRAME_LEN * 8,
        max_copies=max_n * 2 + 1,   # never hit the halving decay in sim
    )
    single_copy = np.zeros(max_n, dtype=bool)
    admissions = np.zeros(max_n, dtype=bool)
    phase_rms_samples = np.zeros(max_n, dtype=np.float64)
    asm_errs_samples = np.zeros(max_n, dtype=np.int64)
    accumulator_n = None

    for i in range(max_n):
        result = _decode_one_copy(tx_samples, responder_static,
                                    snr_db, rng)
        if result["status"] == "short_block" or result["status"] == "no_fit":
            continue
        single_copy[i] = result.get("solo_decrypt", False)
        phase_rms_samples[i] = result.get("phase_rms_residual_rad") or 0.0
        asm_errs_samples[i] = result.get("asm_errs_in_coherent") or 0
        if accumulator.try_add(result):
            admissions[i] = True
            if accumulator_n is None:
                combined = accumulator.try_decrypt(responder_static)
                if combined is not None:
                    accumulator_n = i + 1

    return {
        "single_copy_decrypts": single_copy,
        "accumulator_decrypt_n": accumulator_n,
        "admissions": admissions,
        "phase_rms_samples": phase_rms_samples,
        "asm_errs_samples": asm_errs_samples,
    }


def _run_sweep(snr_db: float, trials: int, max_n: int,
               seed: int) -> dict:
    responder_static = dd.demo_responder_key()
    frame = dd.build_demo_hail()
    chips = dd.build_tx_chips(frame)
    tx_samples = dd.upsample_chips_to_samples(chips, SAMPS_PER_CHIP)

    master = np.random.default_rng(seed)
    single_rate_counts = np.zeros(max_n, dtype=np.int64)
    admit_counts = np.zeros(max_n, dtype=np.int64)
    accumulator_decode_counts = np.zeros(max_n + 1, dtype=np.int64)
    phase_rms_all = []
    asm_errs_all = []

    for _t in range(trials):
        trial_seed = int(master.integers(0, 2**63 - 1))
        rng = np.random.default_rng(trial_seed)
        trial = _run_one_trial(
            tx_samples, responder_static, snr_db, max_n, rng,
        )
        single_rate_counts += trial["single_copy_decrypts"].astype(np.int64)
        admit_counts += trial["admissions"].astype(np.int64)
        if trial["accumulator_decrypt_n"] is None:
            accumulator_decode_counts[0] += 1
        else:
            accumulator_decode_counts[trial["accumulator_decrypt_n"]] += 1
        phase_rms_all.extend(trial["phase_rms_samples"].tolist())
        asm_errs_all.extend(trial["asm_errs_samples"].tolist())

    return {
        "snr_db": snr_db,
        "trials": trials,
        "max_n": max_n,
        "single_copy_rate": single_rate_counts / trials,
        "admit_rate": admit_counts / trials,
        "acc_decode_counts": accumulator_decode_counts,
        "mean_phase_rms": float(np.mean(phase_rms_all)),
        "mean_asm_errs": float(np.mean(asm_errs_all)),
    }


def _acc_fer_at_n(counts: np.ndarray, trials: int) -> np.ndarray:
    max_n = len(counts) - 1
    decoded_cumulative = np.zeros(max_n + 1, dtype=np.int64)
    decoded_cumulative[0] = 0
    for k in range(1, max_n + 1):
        decoded_cumulative[k] = decoded_cumulative[k - 1] + counts[k]
    fer = 1.0 - decoded_cumulative / trials
    return fer[1:]


def _print_sweep_table(results: list) -> None:
    print()
    print("=" * 88)
    print("  D4 LLR accumulator — AWGN validation sweep (tracker bypassed)")
    print("=" * 88)
    print()
    print(f"{'SNR':>6}  {'admit%':>7}  {'rms̄':>6}  {'asm̄':>5}  "
          f"{'FER_solo':>9}  {'FER_N=1':>8}  {'FER_N=2':>8}  "
          f"{'FER_N=4':>8}  {'FER_N=8':>8}  {'FER_N=16':>9}")
    print("-" * 88)
    for r in results:
        snr = r["snr_db"]
        trials = r["trials"]
        max_n = r["max_n"]
        solo = float(r["single_copy_rate"].mean())
        fer_solo = 1.0 - solo
        acc_fer = _acc_fer_at_n(r["acc_decode_counts"], trials)
        admit = float(r["admit_rate"].mean())
        rms_mean = r["mean_phase_rms"]
        asm_mean = r["mean_asm_errs"]
        def fer_at(n: int) -> str:
            if n > max_n:
                return "   —"
            return f"{acc_fer[n-1]:8.3f}"
        print(f"{snr:+6.1f}  {admit*100:6.1f}%  {rms_mean:6.2f}  {asm_mean:5.1f}  "
              f"{fer_solo:9.3f}  "
              f"{fer_at(1):>8}  {fer_at(2):>8}  {fer_at(4):>8}  "
              f"{fer_at(8):>8}  {fer_at(16):>9}")
    print()


def _check_sqrt_n_gain(results: list) -> int:
    good = 0
    for r in results:
        trials = r["trials"]
        max_n = r["max_n"]
        if max_n < 4:
            continue
        acc_fer = _acc_fer_at_n(r["acc_decode_counts"], trials)
        if acc_fer[0] > 0.20 and acc_fer[0] - acc_fer[3] >= 0.15:
            good += 1
    return good


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--snr", nargs="*", type=float,
                   default=[6.0, 3.0, 0.0, -3.0, -6.0],
                   help="symbol SNRs in dB to sweep "
                        "(default: +6 to -6, bracketing the waterfall)")
    p.add_argument("--trials", type=int, default=20)
    p.add_argument("--max-n", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    print(f"bench_llr_accumulator: sweep snrs={args.snr} "
          f"trials={args.trials} max_n={args.max_n}")
    t0 = time.time()
    results = []
    for snr in args.snr:
        r = _run_sweep(snr, args.trials, args.max_n, args.seed)
        results.append(r)
        elapsed = time.time() - t0
        solo = float(r['single_copy_rate'].mean())
        print(f"  snr={snr:+.1f}  solo={solo:.2f}  "
              f"admit={r['admit_rate'].mean():.2f}  "
              f"rms={r['mean_phase_rms']:.2f}  "
              f"asm_errs={r['mean_asm_errs']:.1f}  "
              f"({elapsed:.0f}s elapsed)")
    _print_sweep_table(results)

    good = _check_sqrt_n_gain(results)
    if good > 0:
        print(f"PASS: {good}/{len(results)} SNRs show N=4 "
              f"rescue of ≥15 pp of FER")
        return 0
    else:
        print(f"FAIL: no SNR shows N=4 accumulator rescue ≥15 pp of FER.")
        print(f"Either (a) all SNRs are outside the waterfall,")
        print(f"(b) the accumulator is broken. Inspect table above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
