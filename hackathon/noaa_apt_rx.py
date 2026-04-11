#!/usr/bin/env python3
"""
NOAA APT Weather Satellite Receiver
Receives 137.x MHz FM signal, demodulates, writes audio WAV for noaa-apt decoder.

Usage:
    python3 noaa_apt_rx.py --freq 137620000 --out noaa.wav
    noaa-apt noaa.wav   # produces noaa.png

Hardware: RTL-SDR (Nooelec NESDR) or HackRF via SoapySDR
Pass time: check https://www.n2yo.com or `predict` tool
Record for ~10-14 minutes (full pass)
"""

import argparse
import sys
from gnuradio import gr, blocks, filter, analog
from gnuradio.filter import firdes
import osmosdr  # gr-osmosdr covers both RTL-SDR and HackRF via SoapySDR

# Sample rates
SDR_RATE   = 1_200_000   # Input from SDR (1.2 Msps — stable RTL-SDR rate)
AUDIO_RATE =     11_025  # APT audio rate (noaa-apt expects this exactly)
# Decimation: SDR_RATE / AUDIO_RATE must be integer or handled by rational resampler
# 1_200_000 / 11_025 = 108.84... use rational resampler: 441/4800 = 11025/120000
# Actual decimation path: 1.2M → (decimate 10) → 120k → (resample 441/4800) → 11025

APT_FM_DEVIATION = 17_000  # Hz, APT uses ~17 kHz deviation


class NOAAAptReceiver(gr.top_block):
    def __init__(self, freq_hz, output_file, device_args=""):
        super().__init__("NOAA APT Receiver")

        # --- Source ---
        self.src = osmosdr.source(args=device_args)
        self.src.set_sample_rate(SDR_RATE)
        self.src.set_center_freq(freq_hz)
        self.src.set_freq_corr(0)
        self.src.set_gain_mode(False)
        self.src.set_gain(40)        # LNA gain (dB) — adjust if signal weak/overloaded
        self.src.set_if_gain(20)
        self.src.set_bb_gain(20)
        self.src.set_antenna("", 0)
        self.src.set_bandwidth(200_000, 0)

        # --- Low-pass filter (anti-alias before decimation) ---
        # Cutoff slightly above APT bandwidth (~34 kHz total, ±17 kHz deviation)
        lp_taps = firdes.low_pass(
            gain=1.0,
            sampling_freq=SDR_RATE,
            cutoff_freq=40_000,
            transition_width=10_000,
            window=firdes.WIN_HAMMING,
        )
        self.lpf = filter.fir_filter_ccf(
            decimation=10,          # 1.2M → 120k
            taps=lp_taps,
        )

        # --- FM demodulator ---
        # quad_demod gain = sample_rate / (2 * pi * max_deviation)
        quad_gain = (SDR_RATE / 10) / (2 * 3.14159 * APT_FM_DEVIATION)
        self.fm_demod = analog.quadrature_demod_cf(gain=quad_gain)

        # --- Rational resampler: 120k → 11025 Hz ---
        # 11025 / 120000 = 441 / 4800
        self.resampler = filter.rational_resampler_fff(
            interpolation=441,
            decimation=4800,
            taps=[],
            fractional_bw=0.4,
        )

        # --- Scale to 16-bit PCM range and write WAV ---
        self.scaler = blocks.multiply_const_ff(32767.0)
        self.f2s = blocks.float_to_short(1, 1.0)
        self.wav_sink = blocks.wavfile_sink(
            output_file,
            1,           # mono
            AUDIO_RATE,
            blocks.FORMAT_WAV,
            blocks.FORMAT_PCM_16,
            False,
        )

        # --- Connect ---
        self.connect(self.src, self.lpf, self.fm_demod, self.resampler,
                     self.scaler, self.f2s, self.wav_sink)


def main():
    p = argparse.ArgumentParser(description="NOAA APT SDR receiver")
    p.add_argument("--freq", type=int, default=137_620_000,
                   help="Center frequency Hz (default: 137620000 = NOAA-18)")
    p.add_argument("--out", default="noaa_apt.wav",
                   help="Output WAV file (feed to noaa-apt)")
    p.add_argument("--device", default="",
                   help="SoapySDR/osmosdr device string. "
                        "RTL-SDR: '' or 'rtl=0'. "
                        "HackRF: 'soapy=0,driver=hackrf'")
    p.add_argument("--duration", type=int, default=0,
                   help="Record seconds then stop (0 = run until Ctrl-C)")
    args = p.parse_args()

    print(f"Tuning to {args.freq/1e6:.4f} MHz → {args.out}")
    print("Recording... Ctrl-C to stop" if args.duration == 0
          else f"Recording {args.duration}s...")

    tb = NOAAAptReceiver(args.freq, args.out, args.device)
    tb.start()

    try:
        if args.duration > 0:
            import time
            time.sleep(args.duration)
        else:
            tb.wait()
    except KeyboardInterrupt:
        pass
    finally:
        tb.stop()
        tb.wait()

    print(f"Saved {args.out}")
    print(f"Decode with:  noaa-apt {args.out}")


if __name__ == "__main__":
    main()
