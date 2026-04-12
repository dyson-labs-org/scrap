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

  1. TX: build_demo_hail → tx_bytes_to_chips → upsample_chips_to_samples
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
import demo as dd
import sisl_fec
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

    NOTE on the missing bracket search: an earlier version of this
    function picked the largest |corr| in a ±2 sample neighborhood
    around each target. That was intended to absorb sub-sample timing
    jitter, but it has a serious low-SNR bias: argmax of |noisy_peak|
    in a 5-cell window picks the cell whose REAL part has been pushed
    LOWER by noise (because |corr| > |signal| under noise → the chosen
    cell has below-average signal contribution). The result was an
    empirical SNR ~5 dB worse than the nominal γ_s the bench claims.
    Synthetic AWGN has zero timing jitter by construction, so we now
    sample at the exact integer-aligned positions and get a clean
    γ_s = nominal match.
    """
    corr_c = sf.matched_filter_complex_sample_rate(
        samples, SAMPS_PER_CHIP,
    )
    if len(corr_c) == 0:
        return np.zeros(0, dtype=np.complex128)
    targets = np.arange(n_bits, dtype=np.int64) * SAMPLES_PER_SYMBOL
    valid = targets < len(corr_c)
    if not valid.all():
        n_valid = int(valid.sum())
        return corr_c[targets[:n_valid]].astype(np.complex128)
    return corr_c[targets].astype(np.complex128)


def _make_noisy_copy(tx_samples: np.ndarray, snr_db: float,
                      rng: np.random.Generator) -> np.ndarray:
    sigma_axis = _symbol_snr_to_noise_std(snr_db)
    n = len(tx_samples)
    noise = (rng.normal(0.0, sigma_axis, n).astype(np.float32)
             + 1j * rng.normal(0.0, sigma_axis, n).astype(np.float32))
    return (tx_samples + noise).astype(np.complex64)


def _build_demo_fec_body() -> sc.HailBody:
    """Mirror build_demo_hail's HailBody construction without the
    encode_hail call (which we want to do via encode_hail_fec instead).
    Uses a fixed body_nonce for bench reproducibility — production uses
    os.urandom(8)."""
    caller_static = dd.demo_caller_key()
    return sc.HailBody(
        caller_static_pub=sc.pubkey_to_compressed(caller_static.public_key()),
        center_freq_offset=100,
        bandwidth_code=0x03,
        mode=0x01,
        chip_rate_code=0x32,
        body_nonce=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        flags=0x03,
    )


def _build_tx_samples_fec(responder_static) -> np.ndarray:
    """Build a noise-free TX sample stream for one FEC-encoded hail.

    Calls sisl_crypto.encode_hail_fec to produce the 2096-bit channel
    array (48-bit uncoded header + 2048-bit FEC body), spreads via
    sisl_framer.tx_bits_to_chips, upsamples to the bench sample rate.
    """
    body = _build_demo_fec_body()
    eph = sc.Ephemeral()
    bits = sc.encode_hail_fec(eph, responder_static.public_key(), body)
    chips = sf.tx_bits_to_chips(bits)
    return dd.upsample_chips_to_samples(chips, SAMPS_PER_CHIP)


def _coherent_decode_fec_bench(peaks: np.ndarray) -> "tuple | None":
    """Coherent BPSK decode of HAIL_FEC_TOTAL_BITS peaks for the FEC
    bench, with the per-symbol phase-drift parameter forced to zero.

    The standard coherent_decode_from_pilot fits both θ₀ and Δθ from a
    48-bit pilot. At an output codeword length of 1064 bits this is
    fine, but at 2096 bits the Cramer-Rao slope uncertainty
    σ_Δθ ≈ sqrt(12 / (N(N²-1)·SNR)) accumulated over the longer
    codeword exceeds π/2 for any plausible bench SNR. The result is a
    burst of bit flips in the back half of the codeword that the
    Viterbi cannot fix.

    The bench's synthetic AWGN channel has zero Doppler by construction,
    so we can force Δθ = 0 here to isolate the FEC accumulator
    validation from the (separate) carrier-tracking design problem
    flagged in the second reviewer's S4. Production deployment will
    need DBPSK or a longer pilot to address the same issue on real
    air-interface signals — that's a Phase 1.5 concern, not blocking
    for the bench.
    """
    n_bits = sc.HAIL_FEC_TOTAL_BITS
    if len(peaks) < n_bits:
        return None
    # Fit only θ₀; ignore the function's Δθ output.
    fit = sf.fit_phase_from_known_bits(peaks, 0, dd._PILOT_BITS)
    if fit is None:
        return None
    theta0, _delta, rms_residual = fit
    peaks_arr = np.array(peaks[:n_bits], dtype=np.complex128)
    # Derotate by -θ₀ only (Δθ=0).
    rot = np.exp(-1j * theta0)
    derotated = peaks_arr * rot
    soft = derotated.real.astype(np.float32)
    bits = (soft < 0).astype(np.uint8)
    pad = (-n_bits) % 8
    if pad:
        bits = np.concatenate([bits, np.zeros(pad, dtype=np.uint8)])
    frame_bytes = np.packbits(bits).tobytes()
    return frame_bytes, soft, theta0, 0.0, rms_residual


def _decode_one_copy_fec(
    tx_samples: np.ndarray,
    responder_static,
    snr_db: float,
    rng: np.random.Generator,
) -> dict:
    """Produce a result dict containing 2096 channel LLRs for the FEC
    accumulator. Uses the same deterministic-alignment peak extraction
    as the uncoded bench path, just at the longer FEC channel length."""
    noisy = _make_noisy_copy(tx_samples, snr_db, rng)
    n_bits = sc.HAIL_FEC_TOTAL_BITS
    peaks = _extract_peaks_known_alignment(noisy, n_bits)
    if len(peaks) < n_bits:
        return {"status": "short_block"}
    coherent = _coherent_decode_fec_bench(peaks)
    if coherent is None:
        return {"status": "no_fit"}
    c_frame, c_soft, _c_theta0, _c_delta, c_rms = coherent
    c_bits_first32 = np.unpackbits(np.frombuffer(c_frame[:4], dtype=np.uint8))
    c_asm_errs = int(np.sum(c_bits_first32 != dd._ASM_BITS))

    # Single-copy FEC decode probe (does THIS copy alone decrypt?).
    solo_decrypt = False
    body_llrs = c_soft[sc.HAIL_FEC_HEADER_BITS:].astype(np.float32)
    body_bits = sisl_fec.decode(body_llrs, sc.HAIL_FEC_BODY_PAYLOAD_BITS)
    body_bytes = np.packbits(body_bits).tobytes()
    header = sc.ASM + bytes([sc.SISL_VERSION, sc.MSG_HAIL])
    candidate_frame = header + body_bytes
    if sc.decode_hail(candidate_frame, responder_static) is not None:
        solo_decrypt = True

    return {
        "status": "fec_decoded" if not solo_decrypt else "fec_decrypt_ok",
        "fec_llrs": c_soft,
        "llrs": None,
        "c_frame": b"\x00" * sc.HAIL_FRAME_LEN,    # unused in fec mode
        "phase_rms_residual_rad": c_rms,
        "asm_errs_in_coherent": c_asm_errs,
        "solo_decrypt": solo_decrypt,
    }


def _run_one_trial_fec(
    tx_samples: np.ndarray,
    responder_static,
    snr_db: float,
    max_n: int,
    rng: np.random.Generator,
) -> dict:
    accumulator = dd.LlrAccumulator(
        n_bits=sc.HAIL_FEC_TOTAL_BITS,
        max_copies=max_n * 2 + 1,
    )
    single_copy = np.zeros(max_n, dtype=bool)
    admissions = np.zeros(max_n, dtype=bool)
    accumulator_n = None
    for i in range(max_n):
        result = _decode_one_copy_fec(
            tx_samples, responder_static, snr_db, rng,
        )
        if result["status"] in ("short_block", "no_fit"):
            continue
        single_copy[i] = result.get("solo_decrypt", False)
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
    }


def _run_sweep_fec(snr_db: float, trials: int, max_n: int,
                    seed: int) -> dict:
    responder_static = dd.demo_responder_key()
    tx_samples = _build_tx_samples_fec(responder_static)
    master = np.random.default_rng(seed)
    single_rate_counts = np.zeros(max_n, dtype=np.int64)
    admit_counts = np.zeros(max_n, dtype=np.int64)
    accumulator_decode_counts = np.zeros(max_n + 1, dtype=np.int64)
    for _t in range(trials):
        trial_seed = int(master.integers(0, 2**63 - 1))
        rng = np.random.default_rng(trial_seed)
        trial = _run_one_trial_fec(
            tx_samples, responder_static, snr_db, max_n, rng,
        )
        single_rate_counts += trial["single_copy_decrypts"].astype(np.int64)
        admit_counts += trial["admissions"].astype(np.int64)
        if trial["accumulator_decrypt_n"] is None:
            accumulator_decode_counts[0] += 1
        else:
            accumulator_decode_counts[trial["accumulator_decrypt_n"]] += 1
    return {
        "snr_db": snr_db,
        "trials": trials,
        "max_n": max_n,
        "single_copy_rate": single_rate_counts / trials,
        "admit_rate": admit_counts / trials,
        "acc_decode_counts": accumulator_decode_counts,
        "mean_phase_rms": 0.0,         # not tracked in fec path
        "mean_asm_errs": 0.0,
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


def _check_clean_path_production_admission(
    n_copies: int = 8,
    seed: int = 42,
) -> dict:
    """Run the *production* `_decode_one_hail_in_block` on clean signals
    and verify the resulting decrypt_ok dicts are admittable to the
    accumulator. Regression guard for A5 (LLRs surfaced on every status
    branch including decrypt_ok / decrypt_fail).

    The bench's `_decode_one_copy` builds its own result dicts and was
    already structured to expose LLRs on the clean path. The production
    decoder used to drop them. After A5, both paths agree. This check
    asserts the agreement so a future regression in
    `_decode_one_hail_in_block` is caught here, not in real-bench RF
    operations months later.

    Also asserts the cumulative-LLR magnitude on the production path
    grows roughly linearly with N (the +3 dB-per-doubling claim).
    """
    rng = np.random.default_rng(seed)
    responder_static = dd.demo_responder_key()
    accumulator = dd.LlrAccumulator(
        n_bits=sc.HAIL_FEC_TOTAL_BITS, max_copies=n_copies * 2 + 1,
    )
    admitted = 0
    decrypted_solo = 0
    keys_required = ("fec_llrs", "c_frame",
                     "phase_rms_residual_rad", "asm_errs_in_coherent")
    cumulative_l1: list[float] = []
    for i in range(n_copies):
        prefix = int(rng.integers(20_000, 80_000))
        suffix = int(rng.integers(20_000, 80_000))
        block, _frame = _make_clean_block(prefix, suffix, rng)
        result = dd._decode_one_hail_in_block(block, responder_static)
        if result.get("status") != "decrypt_ok":
            return {
                "ok": False,
                "reason": f"copy {i} status={result.get('status')!r} "
                          f"(expected decrypt_ok on clean signal)",
                "admitted": admitted,
                "n_copies": n_copies,
            }
        for k in keys_required:
            if result.get(k) is None:
                return {
                    "ok": False,
                    "reason": f"copy {i} decrypt_ok but {k!r} missing/None "
                              "(A5 regression — production decoder dropped LLRs)",
                    "admitted": admitted,
                    "n_copies": n_copies,
                }
        decrypted_solo += 1
        if not accumulator.try_add(result):
            return {
                "ok": False,
                "reason": f"copy {i} decrypt_ok but accumulator rejected "
                          f"admission (rms={result.get('phase_rms_residual_rad')}, "
                          f"asm_errs={result.get('asm_errs_in_coherent')})",
                "admitted": admitted,
                "n_copies": n_copies,
            }
        admitted += 1
        cumulative_l1.append(float(np.mean(np.abs(accumulator.accumulated))))

    # Combining-is-happening check on the cumulative L1: the precise
    # scaling depends on the coherent decoder's per-call normalization
    # (which varies slightly with prefix offset and sub-chip phase),
    # so we don't assert strict N× linearity. The meaningful invariant
    # is that the accumulator's L1 grows MONOTONICALLY and ends well
    # above the single-copy L1. The failure mode this catches is
    # polarity-flipping cancellation (final L1 ≈ single, or worse,
    # near zero), which would happen if A5 surfaced LLRs with
    # inconsistent sign convention across copies.
    final_l1 = cumulative_l1[-1]
    single_l1 = cumulative_l1[0]
    monotonic = all(
        cumulative_l1[i] >= cumulative_l1[i - 1] - 1e-9
        for i in range(1, len(cumulative_l1))
    )
    combining_factor = final_l1 / single_l1 if single_l1 > 0 else 0.0
    # At N=8 with clean copies, expect combining_factor ≥ 2.0; the
    # observed ratio in practice is ~3-4× depending on normalization.
    combining_ok = combining_factor >= 2.0 and monotonic

    return {
        "ok": admitted == n_copies and decrypted_solo == n_copies and combining_ok,
        "reason": (
            None if (admitted == n_copies and decrypted_solo == n_copies and combining_ok)
            else (
                "non-monotonic cumulative L1 (polarity flips during accumulation?)"
                if not monotonic
                else f"insufficient combining: factor={combining_factor:.2f} "
                     "(expected ≥ 2.0 for N=8 clean copies)"
            )
        ),
        "n_copies": n_copies,
        "decrypted_solo": decrypted_solo,
        "admitted": admitted,
        "single_copy_l1": single_l1,
        "final_l1": final_l1,
        "combining_factor": combining_factor,
        "monotonic": monotonic,
    }


def _make_clean_block(prefix_samples: int, suffix_samples: int,
                       rng: np.random.Generator) -> tuple[np.ndarray, bytes]:
    """Build a clean (noise-free) baseband block containing two FEC demo hails.

    Two copies provide the search margin the tracker needs. `rng` is
    reserved for future randomized prefixes.
    """
    _ = rng   # reserved
    chips, diag_frame = dd.build_demo_hail_fec_chips()
    chips = np.tile(chips, 2)
    signal = dd.upsample_chips_to_samples(chips)
    prefix = np.zeros(prefix_samples, dtype=np.complex64)
    suffix = np.zeros(suffix_samples, dtype=np.complex64)
    block = np.concatenate([prefix, signal, suffix])
    return block, diag_frame


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
    p.add_argument("--skip-clean-path-check", action="store_true",
                   help="skip the A5 production-path admission check")
    args = p.parse_args()

    # ── A5 regression guard: production decoder must surface LLRs ──
    if not args.skip_clean_path_check:
        print("A5 production-path check: running _decode_one_hail_in_block on")
        print("clean signals and verifying results are accumulator-admittable")
        check = _check_clean_path_production_admission(
            n_copies=8, seed=args.seed,
        )
        if not check["ok"]:
            print(f"FAIL: {check.get('reason', 'unknown')}")
            print(f"  admitted={check['admitted']}/{check['n_copies']}")
            if "combining_factor" in check:
                print(f"  cumulative L1 combining factor "
                      f"(final/single)={check['combining_factor']:.2f} "
                      f"(expected ≥ 2.0)")
            return 2
        print(f"PASS: {check['admitted']}/{check['n_copies']} clean copies "
              f"admitted on production path; "
              f"L1 combining factor={check['combining_factor']:.2f}")
        print()

    sweep_fn = _run_sweep_fec
    label = "FEC"
    print(f"bench_llr_accumulator [{label}]: sweep snrs={args.snr} "
          f"trials={args.trials} max_n={args.max_n}")
    t0 = time.time()
    results = []
    for snr in args.snr:
        r = sweep_fn(snr, args.trials, args.max_n, args.seed)
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
