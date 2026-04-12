#!/usr/bin/env python3
"""Radio characterization sweep across frequencies.

Measures the HackRF TX → RTL-SDR RX link quality at each frequency:
  - Peak/median ratio (signal presence strength)
  - Phase noise (rms residual from pilot fit)
  - R[1] frequency offset and stability
  - Per-copy DBPSK body LLR magnitude (accumulator contribution)
  - V-V drift estimate (residual after R[1])

Usage:
  1. Start TX on HackRF (any frequency — we'll retune the RX):
       python sisl_dsss_demo.py --mode tx --fec --freq 433 --tx-vga 30 --tx-amp --duration 600

  2. Run this script (it retunes the RTL-SDR across frequencies):
       python bench_radio_characterize.py

  The TX must be running on the SAME frequency for each measurement.
  So either run this script once per TX frequency, or modify the TX
  to hop frequencies (not implemented).

  Simpler: run TX at one frequency and this script at the same frequency:
       python bench_radio_characterize.py --freq 433
       python bench_radio_characterize.py --freq 868
       python bench_radio_characterize.py --freq 915
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


def characterize_block(samples: np.ndarray, samps_per_chip: int,
                       samp_hz: float) -> dict:
    samples = (samples - samples.mean()).astype(np.complex64)

    rad = sf.estimate_freq_offset_rad_per_sample(samples, iterations=3)
    freq_hz = rad * samp_hz / (2 * np.pi)

    corr_c = sf.matched_filter_complex_sample_rate(
        sf.apply_freq_correction(samples, rad), samps_per_chip)
    if len(corr_c) == 0:
        return {"ok": False}

    mag = np.abs(corr_c).astype(np.float32)
    peak_mag = float(mag.max())
    median_mag = float(np.median(mag))
    ratio = peak_mag / median_mag if median_mag > 0 else 0

    target_bytes = (2 * sc.HAIL_FEC_TOTAL_BITS + 7) // 8
    tr = sf.decode_with_freq_tracking(
        samples, samps_per_chip=samps_per_chip,
        n_bytes=target_bytes, freq_offset_rad_per_sample=rad)
    if tr is None:
        tr = sf.decode_with_freq_tracking(
            samples, samps_per_chip=samps_per_chip,
            n_bytes=(sc.HAIL_FEC_TOTAL_BITS + 7) // 8,
            freq_offset_rad_per_sample=rad)
    if tr is None:
        return {
            "ok": True, "peak_mag": peak_mag, "median_mag": median_mag,
            "ratio": ratio, "freq_offset_hz": freq_hz,
            "tracker": False,
        }

    pv = np.array(tr["peak_values"], dtype=np.complex128)
    drift_vv = sf.estimate_drift_per_symbol(pv)
    drift_deg = drift_vv * 180 / np.pi

    peak_mags = np.abs(pv)
    peak_mag_mean = float(peak_mags.mean())
    peak_mag_std = float(peak_mags.std())

    # Try DBPSK decode at the best soft-correlator offset
    topk = dd.find_sisl_frame_soft_topk(pv.tolist(), sc.HAIL_FRAME_LEN, k=5)
    phase_rms = None
    pilot_errs = None
    body_l1 = None
    soft_score = None
    asm_found = False

    for off, score, _frame, pts in topk:
        if off + sc.HAIL_FEC_TOTAL_BITS > len(pv):
            continue
        if abs(score) <= 8.0:
            continue
        res = sf.dbpsk_decode_from_pilot(
            pv[off:].tolist(), dd._PILOT_BITS, sc.HAIL_FEC_TOTAL_BITS)
        if res is None:
            continue
        _, soft, _t0, _dt, rms = res
        hdr = np.packbits((soft[:48] < 0).astype(np.uint8)).tobytes()
        if hdr[:4] == sc.ASM:
            asm_found = True
        phase_rms = rms
        pilot_bits_decoded = (soft[:48] < 0).astype(np.uint8)
        pilot_errs = int(np.sum(pilot_bits_decoded != dd._PILOT_BITS))
        body_llrs = soft[sc.HAIL_FEC_HEADER_BITS:]
        body_l1 = float(np.mean(np.abs(body_llrs)))
        soft_score = score
        break

    return {
        "ok": True,
        "peak_mag": peak_mag,
        "median_mag": median_mag,
        "ratio": ratio,
        "freq_offset_hz": freq_hz,
        "tracker": True,
        "n_peaks": len(pv),
        "drift_vv_deg": drift_deg,
        "peak_mag_mean": peak_mag_mean,
        "peak_mag_std": peak_mag_std,
        "phase_rms": phase_rms,
        "pilot_errs": pilot_errs,
        "body_l1": body_l1,
        "soft_score": soft_score,
        "asm_found": asm_found,
    }


def run_characterization(freq_mhz: float, n_blocks: int, block_seconds: float,
                         lna_db: int, vga_db: int,
                         device_name: str = "hackrf",
                         amp_on: bool = False) -> list[dict]:
    try:
        import SoapySDR
        from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
    except ImportError:
        print("SoapySDR not available")
        return []

    if device_name not in dd.DEVICES:
        print(f"unknown device {device_name!r}")
        return []
    info = dd.DEVICES[device_name]
    center_hz = freq_mhz * 1e6
    samp_hz = info.samp_hz
    samps_per_chip = info.samps_per_chip

    device = SoapySDR.Device(info.driver)
    device.setSampleRate(SOAPY_SDR_RX, 0, samp_hz)
    device.setFrequency(SOAPY_SDR_RX, 0, center_hz)

    if device_name == "hackrf":
        device.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if amp_on else 0.0)
        device.setGain(SOAPY_SDR_RX, 0, "LNA", float(lna_db))
        device.setGain(SOAPY_SDR_RX, 0, "VGA", float(vga_db))
        gain_str = (f"AMP={'on' if amp_on else 'off'} "
                    f"LNA={lna_db} dB VGA={vga_db} dB")
    else:
        combined_db = max(0.0, min(49.0, float(lna_db + vga_db)))
        device.setGain(SOAPY_SDR_RX, 0, combined_db)
        gain_str = f"TUNER={combined_db:.0f} dB"

    stream = device.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32, [0])
    device.activateStream(stream)

    block_samples = int(block_seconds * samp_hz)
    buf = np.empty(block_samples, dtype=np.complex64)
    results = []

    print(f"\n{'='*72}")
    print(f"  {freq_mhz:.0f} MHz — {info.name} {gain_str}, "
          f"{n_blocks} blocks × {block_seconds:.1f}s")
    print(f"{'='*72}")
    print(f"{'blk':>4}  {'peak':>6}  {'med':>6}  {'ratio':>5}  "
          f"{'Δf Hz':>8}  {'drift°':>7}  {'rms':>5}  "
          f"{'p_err':>5}  {'body_L1':>8}  {'score':>6}  {'ASM':>3}")
    print("-" * 72)

    try:
        for b in range(n_blocks):
            filled = 0
            while filled < block_samples:
                sr = device.readStream(stream, [buf[filled:]],
                                       block_samples - filled,
                                       timeoutUs=2_000_000)
                if sr.ret > 0:
                    filled += sr.ret
                elif sr.ret == -4:
                    break
                else:
                    break
            if filled < block_samples // 2:
                print(f"  block {b}: short ({filled} samples)")
                continue

            r = characterize_block(buf[:filled], samps_per_chip, samp_hz)
            results.append(r)

            if not r["ok"]:
                print(f"  block {b}: failed")
                continue

            pk = r.get("peak_mag", 0)
            md = r.get("median_mag", 0)
            rat = r.get("ratio", 0)
            foff = r.get("freq_offset_hz", 0)
            drft = r.get("drift_vv_deg", 0)
            rms = r.get("phase_rms")
            pe = r.get("pilot_errs")
            bl1 = r.get("body_l1")
            sc_val = r.get("soft_score")
            asm = r.get("asm_found", False)

            rms_s = f"{rms:.2f}" if rms is not None else "  —"
            pe_s = f"{pe}/48" if pe is not None else "  —"
            bl1_s = f"{bl1:.0f}" if bl1 is not None else "     —"
            sc_s = f"{sc_val:+.1f}" if sc_val is not None else "   —"
            asm_s = "YES" if asm else " no"

            print(f"{b+1:4d}  {pk:6.0f}  {md:6.1f}  {rat:5.1f}  "
                  f"{foff:+8.0f}  {drft:+7.1f}  {rms_s:>5}  "
                  f"{pe_s:>5}  {bl1_s:>8}  {sc_s:>6}  {asm_s:>3}")

    except KeyboardInterrupt:
        print("  interrupted")
    finally:
        device.deactivateStream(stream)
        device.closeStream(stream)

    return results


def print_summary(freq_mhz: float, results: list[dict]):
    good = [r for r in results if r.get("ok") and r.get("tracker")]
    if not good:
        print(f"\n  {freq_mhz:.0f} MHz: no valid blocks")
        return

    ratios = [r["ratio"] for r in good]
    foffs = [r["freq_offset_hz"] for r in good]
    drifts = [r.get("drift_vv_deg", 0) for r in good]
    rms_vals = [r["phase_rms"] for r in good if r.get("phase_rms") is not None]
    pe_vals = [r["pilot_errs"] for r in good if r.get("pilot_errs") is not None]
    bl1_vals = [r["body_l1"] for r in good if r.get("body_l1") is not None]
    asm_count = sum(1 for r in good if r.get("asm_found"))

    print(f"\n  {freq_mhz:.0f} MHz SUMMARY ({len(good)} valid blocks):")
    print(f"    peak/median ratio:  {np.median(ratios):.1f} median "
          f"[{min(ratios):.1f} .. {max(ratios):.1f}]")
    print(f"    freq offset:        {np.median(foffs):+.0f} Hz median "
          f"[{min(foffs):+.0f} .. {max(foffs):+.0f}]")
    print(f"    freq offset std:    {np.std(foffs):.0f} Hz "
          f"(stability across blocks)")
    print(f"    V-V drift:          {np.median(drifts):+.1f}°/sym median "
          f"[{min(drifts):+.1f} .. {max(drifts):+.1f}]")
    if rms_vals:
        print(f"    phase_rms:          {np.median(rms_vals):.3f} median "
              f"[{min(rms_vals):.3f} .. {max(rms_vals):.3f}]")
    if pe_vals:
        print(f"    pilot BER:          {np.mean(pe_vals)/48:.1%} mean "
              f"({np.mean(pe_vals):.1f}/48)")
    if bl1_vals:
        print(f"    body LLR |mean|:    {np.median(bl1_vals):.0f} median "
              f"[{min(bl1_vals):.0f} .. {max(bl1_vals):.0f}]")
    print(f"    ASM found:          {asm_count}/{len(good)} blocks")

    if rms_vals:
        med_rms = float(np.median(rms_vals))
        if med_rms < 0.5:
            verdict = "EXCELLENT — single-copy decrypt expected"
        elif med_rms < 0.9:
            verdict = "GOOD — single-copy or 2-4 copy decrypt"
        elif med_rms < 1.2:
            verdict = "MARGINAL — needs 4-16 copy combining"
        elif med_rms < 1.5:
            verdict = "POOR — needs 16-64 copy combining"
        else:
            verdict = "VERY POOR — may not converge"
        print(f"    verdict:            {verdict}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--freq", type=float, nargs="+", default=[433],
                   help="frequencies in MHz to characterize (default: 433)")
    p.add_argument("--blocks", type=int, default=5,
                   help="blocks per frequency (default: 5)")
    p.add_argument("--block-seconds", type=float, default=6.0)
    p.add_argument("--rx-lna", type=int, default=20)
    p.add_argument("--rx-vga", type=int, default=5)
    p.add_argument("--rx-amp", action="store_true",
                   help="enable RX pre-amp (HackRF only)")
    p.add_argument("--device", choices=list(dd.DEVICES.keys()),
                   default="hackrf",
                   help="RX device (default: hackrf)")
    args = p.parse_args()

    print("Radio characterization sweep")
    print(f"  device:      {args.device}")
    print(f"  frequencies: {args.freq} MHz")
    print(f"  blocks/freq: {args.blocks}")
    print(f"  NOTE: TX must be running on the target frequency")

    for freq in args.freq:
        results = run_characterization(
            freq, args.blocks, args.block_seconds,
            args.rx_lna, args.rx_vga,
            device_name=args.device, amp_on=args.rx_amp)
        print_summary(freq, results)
    print()


if __name__ == "__main__":
    main()
