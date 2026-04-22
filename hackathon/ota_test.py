#!/usr/bin/env python3
"""OTA loopback test runner for HackRF One devices."""
import subprocess, time, re, sys

WORKDIR = "/home/mcelrath/Jobs/perigalacticon/dysonlabs/.worktrees/rlnc/hackathon"

def run_trial(freq_mhz, tx_vga, tx_amp, rx_lna, rx_vga, rx_amp, duration=60):
    base = ["python", "demo.py", "--freq", str(freq_mhz)]

    resp_cmd = base + ["--mode", "respond",
                       "--rx-lna", str(rx_lna), "--rx-vga", str(rx_vga),
                       "--tx-vga", str(tx_vga),
                       "--duration", "90"]
    if rx_amp:
        resp_cmd += ["--rx-amp"]
    else:
        resp_cmd += ["--no-rx-amp"]
    if tx_amp:
        resp_cmd += ["--tx-amp"]

    call_cmd = base + ["--mode", "call",
                       "--tx-vga", str(tx_vga),
                       "--rx-lna", str(rx_lna), "--rx-vga", str(rx_vga),
                       "--duration", str(duration)]
    if rx_amp:
        call_cmd += ["--rx-amp"]
    else:
        call_cmd += ["--no-rx-amp"]
    if tx_amp:
        call_cmd += ["--tx-amp"]

    print(f"  respond: {' '.join(resp_cmd)}", flush=True)
    print(f"  call:    {' '.join(call_cmd)}", flush=True)

    resp = subprocess.Popen(resp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=WORKDIR)
    time.sleep(2)
    call = subprocess.Popen(call_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=WORKDIR)

    try:
        call_out, call_err = call.communicate(timeout=duration + 30)
        resp.terminate()
        resp_out, resp_err = resp.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        call.kill(); resp.kill()
        call_out, _ = call.communicate()
        resp_out, _ = resp.communicate()

    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    call_text = ansi_escape.sub('', call_out.decode(errors='replace'))
    resp_text = ansi_escape.sub('', resp_out.decode(errors='replace'))

    passed = any(kw in call_text for kw in ["HANDSHAKE COMPLETE", "ACK RECEIVED", "hails decrypted: "])
    if not passed:
        passed = any(kw in resp_text for kw in ["HANDSHAKE COMPLETE", "ACK SENT"])

    return passed, call_text[-2000:], resp_text[-2000:]


def run_trials(freq_mhz, tx_vga, tx_amp, rx_lna, rx_vga, rx_amp, n=3, duration=60):
    results = []
    for i in range(n):
        print(f"\n  Trial {i+1}/{n} @ {freq_mhz} MHz tx-vga={tx_vga} tx-amp={tx_amp} rx-lna={rx_lna} rx-vga={rx_vga} rx-amp={rx_amp}", flush=True)
        passed, call_text, resp_text = run_trial(freq_mhz, tx_vga, tx_amp, rx_lna, rx_vga, rx_amp, duration)
        results.append(passed)
        status = "PASS" if passed else "FAIL"
        print(f"  => {status}", flush=True)
        if not passed:
            print("  --- call tail ---")
            print(call_text[-500:])
            print("  --- resp tail ---")
            print(resp_text[-500:])
        time.sleep(2)
    return results


results_table = []

# ===== Step 1: Diagnose 2437 MHz =====
print("\n" + "="*60)
print("STEP 1: Diagnosing 2437 MHz (ADC clipping fix)")
print("="*60, flush=True)

settings_2437 = [
    # rx_lna, rx_vga, rx_amp, tx_vga
    (16, 32, True,  0,  "a: reduced gain, amp on"),
    (24, 40, True,  0,  "b: moderate gain, amp on"),
    (40, 40, False, 0,  "c: amp off"),
    (16, 32, False, 0,  "d: low gain, no amp"),
    (16, 32, True,  20, "a+tx20: tx-vga=20"),
    (24, 40, True,  20, "b+tx20: tx-vga=20"),
]

found_2437 = None
for rx_lna, rx_vga, rx_amp, tx_vga, label in settings_2437:
    print(f"\n--- 2437 MHz setting {label} ---", flush=True)
    passed, call_text, resp_text = run_trial(2437, tx_vga=tx_vga, tx_amp=False,
                                              rx_lna=rx_lna, rx_vga=rx_vga, rx_amp=rx_amp,
                                              duration=60)
    status = "PASS" if passed else "FAIL"
    print(f"  => {status}", flush=True)
    if not passed:
        print(call_text[-400:])
    if passed:
        found_2437 = (rx_lna, rx_vga, rx_amp, tx_vga, label)
        print(f"  FOUND WORKING SETTING: {label}", flush=True)
        break

if found_2437 is None:
    print("  2437 MHz: ALL SETTINGS FAILED", flush=True)
    results_table.append(("2437 MHz", "N/A", "off", "N/A", "N/A", "N/A", "1", "0/1", "FAILED ALL"))
else:
    rx_lna, rx_vga, rx_amp, tx_vga, label = found_2437
    # Run 2 more trials to confirm
    r = run_trials(2437, tx_vga=tx_vga, tx_amp=False, rx_lna=rx_lna, rx_vga=rx_vga, rx_amp=rx_amp, n=2)
    total = 1 + sum(r)
    results_table.append(("2437 MHz", tx_vga, "off", rx_lna, rx_vga, "on" if rx_amp else "off", 3, f"{total}/3", f"setting {label}"))

# ===== Step 2: 915 MHz =====
print("\n" + "="*60)
print("STEP 2: Testing 915 MHz")
print("="*60, flush=True)

print("\n--- 915 MHz: tx-vga=0 rx-amp on rx-lna=40 rx-vga=40 ---", flush=True)
r915_a = run_trials(915, tx_vga=0, tx_amp=False, rx_lna=40, rx_vga=40, rx_amp=True, n=3)
pass915_a = sum(r915_a)

if pass915_a == 0:
    print("\n--- 915 MHz: tx-vga=20 fallback ---", flush=True)
    r915_b = run_trials(915, tx_vga=20, tx_amp=False, rx_lna=24, rx_vga=32, rx_amp=True, n=3)
    pass915_b = sum(r915_b)
    if pass915_b > 0:
        results_table.append(("915 MHz", 20, "off", 24, 32, "on", 3, f"{pass915_b}/3", "fallback tx-vga=20"))
        best_915 = (20, False, 24, 32, True)
    else:
        results_table.append(("915 MHz", 20, "off", 24, 32, "on", 6, f"0/6", "FAILED ALL"))
        best_915 = None
else:
    results_table.append(("915 MHz", 0, "off", 40, 40, "on", 3, f"{pass915_a}/3", ""))
    best_915 = (0, False, 40, 40, True)

# ===== Step 3: 5800 MHz =====
print("\n" + "="*60)
print("STEP 3: Testing 5800 MHz")
print("="*60, flush=True)

print("\n--- 5800 MHz: tx-vga=47 rx-amp on ---", flush=True)
r5800_a = run_trials(5800, tx_vga=47, tx_amp=False, rx_lna=40, rx_vga=40, rx_amp=True, n=3)
pass5800_a = sum(r5800_a)

if pass5800_a == 0:
    print("\n--- 5800 MHz: tx-vga=47 tx-amp on fallback ---", flush=True)
    r5800_b = run_trials(5800, tx_vga=47, tx_amp=True, rx_lna=40, rx_vga=40, rx_amp=True, n=3)
    pass5800_b = sum(r5800_b)
    if pass5800_b > 0:
        results_table.append(("5800 MHz", 47, "on", 40, 40, "on", 3, f"{pass5800_b}/3", "tx-amp enabled"))
        best_5800 = (47, True, 40, 40, True)
    else:
        results_table.append(("5800 MHz", 47, "on", 40, 40, "on", 6, f"0/6", "FAILED ALL"))
        best_5800 = None
else:
    results_table.append(("5800 MHz", 47, "off", 40, 40, "on", 3, f"{pass5800_a}/3", ""))
    best_5800 = (47, False, 40, 40, True)

# ===== Step 4: Minimum TX power sweeps =====
print("\n" + "="*60)
print("STEP 4: Minimum TX power sweeps")
print("="*60, flush=True)

min_power = {}

# 433 MHz already known: tx-vga=0 works
min_power[433] = "tx-vga=0, no amp (from previous session)"

def min_power_sweep(freq_mhz, tx_amp, rx_lna, rx_vga, rx_amp):
    last_pass_vga = None
    consecutive_fail = 0
    for vga in [0, 10, 20, 30]:
        r = run_trials(freq_mhz, tx_vga=vga, tx_amp=tx_amp, rx_lna=rx_lna, rx_vga=rx_vga, rx_amp=rx_amp, n=2)
        if sum(r) == 2:
            last_pass_vga = vga
            consecutive_fail = 0
        else:
            consecutive_fail += 1
            if consecutive_fail >= 2:
                break
    return last_pass_vga

if best_915:
    tx_vga0, tx_amp0, rx_lna0, rx_vga0, rx_amp0 = best_915
    print(f"\n--- 915 MHz min power sweep ---", flush=True)
    # Start from vga=0 up
    lp = min_power_sweep(915, tx_amp0, rx_lna0, rx_vga0, rx_amp0)
    min_power[915] = f"tx-vga={lp}, {'amp' if tx_amp0 else 'no amp'}" if lp is not None else "could not determine"
else:
    min_power[915] = "FAILED - no working setting"

if best_5800:
    tx_vga0, tx_amp0, rx_lna0, rx_vga0, rx_amp0 = best_5800
    print(f"\n--- 5800 MHz min power sweep ---", flush=True)
    lp = min_power_sweep(5800, tx_amp0, rx_lna0, rx_vga0, rx_amp0)
    min_power[5800] = f"tx-vga={lp}, {'amp' if tx_amp0 else 'no amp'}" if lp is not None else "could not determine (max power needed)"
else:
    min_power[5800] = "FAILED - no working setting"

if found_2437:
    rx_lna, rx_vga, rx_amp, tx_vga_w, label = found_2437
    print(f"\n--- 2437 MHz min power sweep ---", flush=True)
    lp = min_power_sweep(2437, False, rx_lna, rx_vga, rx_amp)
    min_power[2437] = f"tx-vga={lp}, no amp" if lp is not None else "could not determine"
else:
    min_power[2437] = "FAILED - no working setting"

# ===== Step 5: Full report =====
print("\n" + "="*60)
print("=== COMPLETE OTA RESULTS ===")
print("="*60)
print(f"{'Freq':<10} {'TX-VGA':<8} {'TX-AMP':<8} {'RX-LNA':<8} {'RX-VGA':<8} {'RX-AMP':<8} {'Trials':<8} {'Pass/Total':<12} {'Notes'}")
print(f"{'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12} {'-'*30}")
# Prior result
print(f"{'433 MHz':<10} {'0':<8} {'off':<8} {'40':<8} {'40':<8} {'on':<8} {'3':<8} {'3/3':<12} from previous session")
for row in results_table:
    freq, tx_vga, tx_amp, rx_lna, rx_vga, rx_amp, trials, pt, notes = row
    print(f"{str(freq):<10} {str(tx_vga):<8} {str(tx_amp):<8} {str(rx_lna):<8} {str(rx_vga):<8} {str(rx_amp):<8} {str(trials):<8} {str(pt):<12} {notes}")

print("\n=== MINIMUM TX POWER PER BAND ===")
for freq, note in min_power.items():
    print(f"  {freq} MHz: {note}")
print(f"  433 MHz: tx-vga=0, no amp  (from previous session)")

print("\n=== NOTES ===")
print("  - 2437 MHz diagnosis: suspected ADC clipping at full gain (LNA=40/VGA=40/AMP=on)")
print("  - USB: 8 other devices on same bus — may affect sample rates")
print("  - HackRF TX power drops significantly above 1 GHz; higher tx-vga needed at 915/2437/5800 MHz")
