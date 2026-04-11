#!/usr/bin/env python3
"""SISL bench test helper — sweep TX power and RX gain step-by-step.

Cross-platform replacement for bench_test.sh. Runs on Linux / macOS /
Windows anywhere Python 3.8+ is installed. External tools (hackrf_info,
SoapySDRUtil, hackrf_sweep) are optional: the diag mode reports which
ones are present and skips the rest.

Usage (from the repo root or the hackathon directory):
    python hackathon/bench_test.py diag             # RF diagnostics
    python hackathon/bench_test.py loop             # pure-DSP loopback
    python hackathon/bench_test.py tx [freq_mhz]    # TX power sweep
    python hackathon/bench_test.py rx [freq_mhz]    # RX gain sweep
    python hackathon/bench_test.py help             # this help

Optional `freq_mhz` overrides the center frequency for that sweep. Both
machines must use the same value. Default is 2437 MHz. Try 5820 if the
2.4 GHz band is crowded. See sisl_dsss_demo.py --help for a full list
of suggested quieter frequencies.

Each step runs until the sub-process exits (usually 30 s duration), then
waits for ENTER before advancing. Ctrl+C aborts the current step; Ctrl+C
again aborts the whole sweep.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE / "sisl_dsss_demo.py"

# Where we stash intermediate .cfile captures. /tmp on unix, %TEMP% on Windows.
def tmp_path(name: str) -> Path:
    base = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
    base.mkdir(parents=True, exist_ok=True)
    return base / name


# ── Console helpers ────────────────────────────────────────────────────────

def banner(msg: str) -> None:
    print()
    print("=" * 64)
    print(f"  {msg}")
    print("=" * 64)


def pause(msg: str = "press ENTER to continue, Ctrl+C to abort") -> None:
    print()
    try:
        input(f"--- {msg} ---")
    except EOFError:
        # stdin not a tty (e.g. piped). Fall through.
        pass
    print()


def run(cmd: list[str], check: bool = False) -> int:
    """Run a subprocess, forward its output, return exit code.

    `check=False` by default so we can see failures without aborting
    the whole sweep. Ctrl+C during a step is caught and returns 130
    (Unix convention) so the caller can decide whether to advance
    or bail.
    """
    print(f"$ {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, check=check)
        return r.returncode
    except KeyboardInterrupt:
        print("  (interrupted)")
        return 130
    except FileNotFoundError as e:
        print(f"  ERROR: command not found — {e}")
        return 127


def demo(*args: str) -> int:
    """Run a sisl_dsss_demo.py subcommand with the current python."""
    return run([sys.executable, str(DEMO), *args])


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


# ── Mode implementations ───────────────────────────────────────────────────

def mode_diag() -> int:
    banner("0. HackRF device probe")
    if have("SoapySDRUtil"):
        run(["SoapySDRUtil", "--find=driver=hackrf"])
    else:
        print("  SoapySDRUtil not in PATH — skipping (expected on some Windows)")
    print()
    if have("hackrf_info"):
        run(["hackrf_info"])
    else:
        print("  hackrf_info not in PATH — skipping")
    pause()

    banner("0b. Spectrum sweep of 2.4 GHz band")
    if have("hackrf_sweep"):
        print("Running hackrf_sweep for ~10 seconds around 2437 MHz...")
        print("You should see WiFi bumps and a noise floor around -80..-90 dBm.")
        # hackrf_sweep runs forever; use a subprocess timeout to cap it
        try:
            subprocess.run(
                ["hackrf_sweep", "-f", "2400:2480", "-w", "1000000",
                 "-l", "32", "-g", "40"],
                timeout=10, check=False,
            )
        except subprocess.TimeoutExpired:
            print("  (10 s elapsed, stopping sweep)")
        except KeyboardInterrupt:
            print("  (interrupted)")
    else:
        print("  hackrf_sweep not in PATH — skipping")
    pause()
    return 0


def mode_loop() -> int:
    cap = str(tmp_path("sisl_bench_hail.cfile"))
    banner("L0. Pure-DSP loopback (no radio) — proves the decoder works")
    demo("--mode", "tx-to-file", "--capture", cap, "--prefix-ms", "5")
    pause()
    demo("--mode", "offline", "--capture", cap, "--as", "responder")
    print()
    print("Expected: TRIAL DECRYPT: OK")
    pause()

    banner("L1. Same capture, WRONG key — must fail with Poly1305 mismatch")
    demo("--mode", "offline", "--capture", cap, "--as", "other")
    print()
    print("Expected: TRIAL DECRYPT: FAILED (Poly1305 tag mismatch)")
    try:
        Path(cap).unlink(missing_ok=True)
    except Exception:
        pass
    return 0


def mode_tx(freq_mhz: float | None = None) -> int:
    freq_args = ["--freq", f"{freq_mhz:.3f}"] if freq_mhz is not None else []
    steps = [
        ("T0", "MINIMUM power (VGA=0, AMP off)",
         ["--tx-vga", "0"],
         "Coordinate with RX operator: they should run 'bench_test.py rx' at step R0."),
        ("T1", "VGA 10 dB, AMP off",
         ["--tx-vga", "10"],
         "RX operator: bump to step R1 (LNA 32 / VGA 40)."),
        ("T2", "VGA 20 dB, AMP off",
         ["--tx-vga", "20"],
         "RX operator: keep R1 or go to R2."),
        ("T3", "VGA 30 dB, AMP off",
         ["--tx-vga", "30"],
         "If RX isn't locking by now, attenuation may be mismatched or "
         "the RF path is broken. Check connections and attenuator values."),
        ("T4", "VGA 40 dB, AMP off",
         ["--tx-vga", "40"],
         "This is ~+40 dB above the default. If RX still shows 'no signal', "
         "the problem is NOT TX power."),
        ("T5", "VGA 40 dB, AMP ON (+14 dB)",
         ["--tx-vga", "40", "--tx-amp"],
         "WARNING: +54 dB above default. Do NOT run this without at least "
         "30 dB of attenuation to the RX — you can damage the peer front end."),
    ]
    for tag, desc, extra, note in steps:
        banner(f"{tag}. TX step — {desc}")
        print(note)
        if freq_args:
            print(f"  using center freq {freq_mhz:.3f} MHz")
        pause()
        demo("--mode", "tx", "--duration", "30", *freq_args, *extra)
    return 0


def mode_rx(freq_mhz: float | None = None) -> int:
    freq_args = ["--freq", f"{freq_mhz:.3f}"] if freq_mhz is not None else []
    steps = [
        ("R0", "default gain (LNA=16, VGA=20)",
         [],
         "TX operator should run 'bench_test.py tx' step T0 first. "
         "Expected: 'no signal' each block with low peak/median."),
        ("R1", "LNA 32, VGA 40",
         ["--rx-lna", "32", "--rx-vga", "40"],
         "TX operator: stay on T0 or advance to T1."),
        ("R2", "LNA 40, VGA 50",
         ["--rx-lna", "40", "--rx-vga", "50"],
         "TX operator: go to T2 or T3."),
        ("R3", "LNA 40, VGA 60 (near max without AMP)",
         ["--rx-lna", "40", "--rx-vga", "60"],
         "TX operator: T3. Watch the interference counter — rising means "
         "the front end is alive but WiFi is competing with the signal."),
        ("R4", "MAX gain + AMP ON",
         ["--rx-lna", "40", "--rx-vga", "62", "--rx-amp"],
         "WARNING: this boosts ALL nearby RF. ADC saturation is likely if "
         "TX is too strong. Use only if R0..R3 all showed 'no signal'."),
        ("R5", "MAX gain + AMP ON + save capture",
         ["--rx-lna", "40", "--rx-vga", "62", "--rx-amp", "--save"],
         "Same as R4 but writes /tmp/sisl_rx.cfile for later offline analysis."),
    ]
    for tag, desc, extra, note in steps:
        banner(f"{tag}. RX step — {desc}")
        print(note)
        if freq_args:
            print(f"  using center freq {freq_mhz:.3f} MHz")
        pause()
        demo("--mode", "rx", "--duration", "30", *freq_args, *extra)
    print()
    print("If R5 wrote /tmp/sisl_rx.cfile, try:")
    print(f"  python {DEMO} --mode offline --capture /tmp/sisl_rx.cfile --as responder")
    return 0


def mode_help() -> int:
    print(__doc__)
    return 0


# ── Dispatch ───────────────────────────────────────────────────────────────

MODES = {
    "diag": mode_diag,
    "loop": mode_loop,
    "tx":   mode_tx,
    "rx":   mode_rx,
    "help": mode_help,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in MODES:
        return mode_help()
    mode = argv[1]
    try:
        if mode in ("tx", "rx"):
            # Optional positional: frequency in MHz
            freq_mhz = None
            if len(argv) >= 3:
                try:
                    freq_mhz = float(argv[2])
                except ValueError:
                    print(f"bad freq argument: {argv[2]!r}", file=sys.stderr)
                    return 2
            return MODES[mode](freq_mhz)
        return MODES[mode]()
    except KeyboardInterrupt:
        print("\n(bench test aborted)")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv))
