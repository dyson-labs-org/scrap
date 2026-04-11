#!/bin/bash
# SISL bench test helper — sweep TX power and RX gain step-by-step.
#
# Usage (from either machine):
#   ./hackathon/bench_test.sh tx     # run on TX machine
#   ./hackathon/bench_test.sh rx     # run on RX machine
#   ./hackathon/bench_test.sh loop   # pure-DSP loopback (no radio)
#   ./hackathon/bench_test.sh diag   # RF diagnostics (probe, spectrum)
#
# Each step prints what it's running and pauses for you to observe
# /Ctrl+C if something looks wrong. RX and TX steps are coordinated:
# when you run "rx step 1", the TX machine should be running "tx step 1"
# already.

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE" || exit 1

pause() {
    echo
    read -rp "--- press ENTER to continue, Ctrl+C to abort ---"
    echo
}

banner() {
    echo
    echo "============================================================"
    echo "  $*"
    echo "============================================================"
}

mode=${1:-help}

case "$mode" in

# ─────────────────────────────────────────────────────────────────────
diag)
    banner "0. HackRF device probe (both machines should show one)"
    SoapySDRUtil --find='driver=hackrf'
    echo
    hackrf_info
    pause

    banner "0b. Spectrum sweep of 2.4 GHz band (watch for local WiFi)"
    echo "Running hackrf_sweep for 10 seconds around 2437 MHz..."
    echo "You should see WiFi bumps and a noise floor around -80..-90 dBm."
    timeout 10 hackrf_sweep -f 2400:2480 -w 1000000 -l 32 -g 40 2>&1 | head -40
    pause
    ;;

# ─────────────────────────────────────────────────────────────────────
loop)
    banner "L0. Pure-DSP loopback (no radio) — proves the decoder works"
    python sisl_dsss_demo.py --mode tx-to-file \
        --capture /tmp/sisl_bench_hail.cfile --prefix-ms 5
    pause
    python sisl_dsss_demo.py --mode offline \
        --capture /tmp/sisl_bench_hail.cfile --as responder
    echo
    echo "That should report: TRIAL DECRYPT: OK"
    pause

    banner "L1. Same capture, WRONG key — must fail with Poly1305 mismatch"
    python sisl_dsss_demo.py --mode offline \
        --capture /tmp/sisl_bench_hail.cfile --as other
    rm -f /tmp/sisl_bench_hail.cfile
    ;;

# ─────────────────────────────────────────────────────────────────────
tx)
    banner "T0. TX step 0 — MINIMUM power (VGA=0, AMP off)"
    echo "Coordinate with RX operator: they should run './bench_test.sh rx'"
    echo "at step 0 (default gain)."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 0

    banner "T1. TX step 1 — VGA 10 dB, AMP off"
    echo "RX operator: bump LNA/VGA to 32/40 (step 1)."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 10

    banner "T2. TX step 2 — VGA 20 dB, AMP off"
    echo "RX operator: keep LNA/VGA at 32/40 or go higher."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 20

    banner "T3. TX step 3 — VGA 30 dB, AMP off"
    echo "If RX isn't locking by now, attenuation is mismatched with link"
    echo "budget or the RF path is broken. Check connections / attenuators."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 30

    banner "T4. TX step 4 — VGA 40 dB, AMP off"
    echo "This is ~+40 dB above the default. Should be audible even with"
    echo "heavy attenuation. If RX still shows 'no signal', the problem"
    echo "is NOT TX power."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 40

    banner "T5. TX step 5 — VGA 40 dB, AMP ON (+14 dB)"
    echo "WARNING: total TX power +54 dB above default. Do NOT run this"
    echo "without at least 30 dB of attenuation to the RX — you can damage"
    echo "the peer's front end. Skip with Ctrl+C if unsure."
    pause
    python sisl_dsss_demo.py --mode tx --duration 30 --tx-vga 40 --tx-amp
    ;;

# ─────────────────────────────────────────────────────────────────────
rx)
    banner "R0. RX step 0 — default gain (LNA=16, VGA=20)"
    echo "TX operator should run './bench_test.sh tx' step 0 FIRST."
    echo "Expected: 'no signal' every block with very low peak/median."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30

    banner "R1. RX step 1 — LNA 32, VGA 40"
    echo "TX operator: stay at step 0 OR go to step 1."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30 --rx-lna 32 --rx-vga 40

    banner "R2. RX step 2 — LNA 40, VGA 50"
    echo "TX operator: go to step 2 or 3."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30 --rx-lna 40 --rx-vga 50

    banner "R3. RX step 3 — LNA 40, VGA 60 (near max without AMP)"
    echo "TX operator: go to step 3."
    echo "Watch for interference counter rising — means you're picking up"
    echo "WiFi, which is good (front end is alive) but the signal has to"
    echo "compete with that noise floor."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30 --rx-lna 40 --rx-vga 60

    banner "R4. RX step 4 — MAX gain + AMP ON"
    echo "WARNING: this will boost ALL nearby RF including your own WiFi."
    echo "ADC saturation is likely if TX is too strong or attenuation is"
    echo "too light. Use only if steps R0-R3 all showed 'no signal'."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30 --rx-lna 40 --rx-vga 62 --rx-amp

    banner "R5. Diagnostic capture with --save"
    echo "Same as R4 but also writes /tmp/sisl_rx.cfile for offline analysis."
    pause
    python sisl_dsss_demo.py --mode rx --duration 30 \
        --rx-lna 40 --rx-vga 62 --rx-amp --save
    echo
    echo "Now run offline:"
    echo "  python sisl_dsss_demo.py --mode offline --capture /tmp/sisl_rx.cfile --as responder"
    ;;

# ─────────────────────────────────────────────────────────────────────
*)
    cat <<EOF
SISL bench test helper — usage: $0 <mode>

Modes:
  diag   — RF diagnostics: probe HackRF, sweep 2.4 GHz for local traffic
  loop   — pure-DSP loopback (no radio) end-to-end sanity check
  tx     — sweep TX power from 0 dB → VGA 40 + AMP (5 steps)
  rx     — sweep RX gain from default → LNA 40 / VGA 62 + AMP (6 steps)

Typical flow:
  1. On RX machine:  $0 diag    # confirm HackRF is alive, see the band
  2. On either:      $0 loop    # confirm the DSP stack works without radio
  3. On RX machine:  $0 rx      # start RX, park on step R0
  4. On TX machine:  $0 tx      # start TX, step T0
  5. If no hails at (T0,R0), both hit ENTER to advance one step at a time.
     Look for RX ratio climbing past 20 on any block. When DECRYPTED lines
     appear, you've found a working operating point.

Notes:
  • Steps are paired by number. (T0,R0) is the softest config.
  • (T5,R4) is the loudest, ~+68 dB above default. Use only with attenuators.
  • Ctrl+C at any pause to abort the sweep cleanly.
  • bench_test.sh rx leaves raw samples in /tmp/sisl_rx.cfile on step R5.
EOF
    ;;
esac
