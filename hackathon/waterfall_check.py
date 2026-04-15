import SoapySDR
import numpy as np
import subprocess
import sys
import time
import os

SERIAL_RESPONDER = "930c64dc279e7bc3"
SERIAL_CALLER = "78d063dc2b6d2267"


def capture_and_analyze(freq_mhz, serial=None, duration_s=3.0, rate=8e6):
    args = {"driver": "hackrf"}
    if serial:
        args["serial"] = serial
    sdr = SoapySDR.Device(args)
    sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, rate)
    sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, freq_mhz * 1e6)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, "AMP", 1)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, "LNA", 40)
    sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, "VGA", 40)
    rxStream = sdr.setupStream(SoapySDR.SOAPY_SDR_RX, SoapySDR.SOAPY_SDR_CF32)
    sdr.activateStream(rxStream)
    n = int(duration_s * rate)
    buf = np.zeros(n, dtype=np.complex64)
    pos = 0
    chunk = 131072
    while pos < n:
        read = min(chunk, n - pos)
        tmp = np.zeros(read, dtype=np.complex64)
        sr = sdr.readStream(rxStream, [tmp], read, timeoutUs=1000000)
        if sr.ret > 0:
            buf[pos:pos+sr.ret] = tmp[:sr.ret]
            pos += sr.ret
    sdr.deactivateStream(rxStream)
    sdr.closeStream(rxStream)
    del sdr
    time.sleep(0.5)
    power = np.abs(buf)**2
    mean_dbfs = 10*np.log10(np.mean(power) + 1e-12)
    peak_dbfs = 10*np.log10(np.max(power) + 1e-12)
    nfft = int(rate / 1e5)
    n_segs = len(buf) // nfft
    psd = np.zeros(nfft)
    for i in range(n_segs):
        seg = buf[i*nfft:(i+1)*nfft]
        psd += np.abs(np.fft.fft(seg))**2
    psd /= n_segs
    psd_db = 10*np.log10(psd / nfft + 1e-12)
    # Use noise floor (10th percentile) + 10 dB as threshold for occupancy
    noise_floor = np.percentile(psd_db, 10)
    threshold = noise_floor + 10.0
    occupancy = np.mean(psd_db > threshold)
    return mean_dbfs, peak_dbfs, occupancy


def run_ota_test(freq_mhz, tx_vga=0, tx_amp=False, duration_caller=60, duration_responder=120):
    demo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo.py")
    responder_cmd = [
        sys.executable, demo,
        "--mode", "respond",
        "--freq", str(freq_mhz),
        "--rx-amp", "--rx-lna", "40", "--rx-vga", "40",
        "--tx-vga", str(tx_vga),
        "--duration", str(duration_responder),
    ]
    caller_cmd = [
        sys.executable, demo,
        "--mode", "call",
        "--freq", str(freq_mhz),
        "--tx-vga", str(tx_vga),
        "--rx-amp", "--rx-lna", "40", "--rx-vga", "40",
        "--duration", str(duration_caller),
    ]
    if tx_amp:
        responder_cmd.append("--tx-amp")
        caller_cmd.append("--tx-amp")

    print(f"  Launching responder: {' '.join(responder_cmd)}", flush=True)
    print(f"  Launching caller:    {' '.join(caller_cmd)}", flush=True)

    resp_proc = subprocess.Popen(responder_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=os.path.dirname(demo))
    time.sleep(2)
    call_proc = subprocess.Popen(caller_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=os.path.dirname(demo))

    try:
        call_out, call_err = call_proc.communicate(timeout=duration_caller + 15)
    except subprocess.TimeoutExpired:
        call_proc.kill()
        call_out, call_err = call_proc.communicate()

    resp_proc.terminate()
    try:
        resp_out, resp_err = resp_proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        resp_proc.kill()
        resp_out, resp_err = resp_proc.communicate()

    import re as _re
    call_text = (call_out or b"").decode("utf-8", errors="replace")
    call_err_text = (call_err or b"").decode("utf-8", errors="replace")
    resp_text = (resp_out or b"").decode("utf-8", errors="replace")
    # Strip ANSI escape codes for matching
    ansi_escape = _re.compile(r'\x1b\[[0-9;]*m')
    call_clean = ansi_escape.sub('', call_text)

    passed = any(kw in call_clean for kw in [
        "HANDSHAKE COMPLETE", "ACK received", "ACK RECEIVED",
        "SESSION ESTABLISHED", "hails decrypted"
    ])
    if not passed:
        m = _re.search(r"hails decrypted:\s*([1-9]\d*)", call_clean)
        if m:
            passed = True

    return passed, call_text, call_err_text, resp_text


def main():
    freqs = [433, 915, 2437, 5800]

    print("=== WATERFALL ===", flush=True)
    waterfall_results = {}
    for freq in freqs:
        print(f"  Scanning {freq} MHz...", flush=True)
        try:
            mean_db, peak_db, occ = capture_and_analyze(freq)
            status = "CLEAR" if occ <= 0.10 else "BUSY"
            waterfall_results[freq] = (mean_db, peak_db, occ, status)
            print(f"  {freq} MHz: mean={mean_db:.1f} dBFS  peak={peak_db:.1f} dBFS  "
                  f"occupancy={occ*100:.1f}%  [{status}]", flush=True)
        except Exception as e:
            print(f"  {freq} MHz: ERROR: {e}", flush=True)
            waterfall_results[freq] = (None, None, None, "ERROR")

    for freq in freqs:
        mean_db, peak_db, occ, status = waterfall_results[freq]
        if mean_db is not None:
            print(f"{freq} MHz:  mean={mean_db:.1f} dBFS  peak={peak_db:.1f} dBFS  occupancy={occ*100:.1f}%  [{status}]")
        else:
            print(f"{freq} MHz:  ERROR")

    clear_bands = [f for f in freqs if waterfall_results[f][3] == "CLEAR"]
    if not clear_bands:
        print("All bands BUSY — using least-busy band.")
        clear_bands = [min(freqs, key=lambda f: waterfall_results[f][2] if waterfall_results[f][2] is not None else 1.0)]

    print(f"\nSelected bands for OTA testing: {clear_bands}", flush=True)

    print("\n=== OTA LOOPBACK ===", flush=True)
    print(f"{'Freq':<10} {'TX-VGA':<8} {'AMP':<5} {'Trial':<7} {'Result'}")
    print(f"{'--------':<10} {'------':<8} {'---':<5} {'-----':<7} {'------'}")

    ota_results = []
    for freq in clear_bands:
        for trial in range(1, 4):
            print(f"  OTA {freq} MHz tx-vga=0 trial {trial}...", flush=True)
            passed, call_out, call_err, resp_out = run_ota_test(freq, tx_vga=0, tx_amp=False)
            result = "PASS" if passed else "FAIL"
            ota_results.append((freq, 0, False, trial, result, call_out, call_err))
            print(f"{freq} MHz   {0:<8} {'off':<5} {trial:<7} {result}")
            if not passed:
                print(f"  CALLER STDOUT: {call_out[-500:]}", flush=True)
                print(f"  CALLER STDERR: {call_err[-500:]}", flush=True)

    print("\n=== MINIMUM TX POWER (2437 MHz) ===", flush=True)
    print(f"{'Setting':<30} {'Trial':<7} {'Result'}")
    print(f"{'-------':<30} {'-----':<7} {'------'}")

    min_power_results = []
    consecutive_fails = 0
    settings = [
        (0, False),
        (0, True),
    ]
    min_working = None
    for tx_vga, tx_amp in settings:
        if consecutive_fails >= 2:
            break
        setting_passes = 0
        for trial in range(1, 4):
            label = f"--tx-vga {tx_vga}" + (" --tx-amp" if tx_amp else "")
            print(f"  {label} trial {trial}...", flush=True)
            passed, call_out, call_err, resp_out = run_ota_test(2437, tx_vga=tx_vga, tx_amp=tx_amp)
            result = "PASS" if passed else "FAIL"
            min_power_results.append((tx_vga, tx_amp, trial, result))
            print(f"{label:<30} {trial:<7} {result}")
            if passed:
                setting_passes += 1
                if min_working is None:
                    min_working = label

        if setting_passes == 0:
            consecutive_fails += 1
        else:
            consecutive_fails = 0

    print("\n=== REPORT ===")
    print("\n=== WATERFALL ===")
    for freq in freqs:
        mean_db, peak_db, occ, status = waterfall_results[freq]
        if mean_db is not None:
            print(f"{freq} MHz:  mean={mean_db:.1f} dBFS  peak={peak_db:.1f} dBFS  occupancy={occ*100:.1f}%  [{status}]")
        else:
            print(f"{freq} MHz:  ERROR")

    print("\n=== OTA LOOPBACK ===")
    print(f"{'Freq':<10} {'TX-VGA':<8} {'AMP':<5} {'Trial':<7} {'Result'}")
    print(f"{'--------':<10} {'------':<8} {'---':<5} {'-----':<7} {'------'}")
    for freq, tx_vga, tx_amp, trial, result, _, _ in ota_results:
        amp_str = "on" if tx_amp else "off"
        print(f"{freq} MHz   {tx_vga:<8} {amp_str:<5} {trial:<7} {result}")

    print("\n=== MINIMUM TX POWER ===")
    print(f"{'Setting':<30} {'Trial':<7} {'Result'}")
    print(f"{'-------':<30} {'-----':<7} {'------'}")
    for tx_vga, tx_amp, trial, result in min_power_results:
        label = f"--tx-vga {tx_vga}" + (" --tx-amp" if tx_amp else "")
        print(f"{label:<30} {trial:<7} {result}")
    if min_working:
        print(f"\nMinimum working: {min_working}")
    else:
        print("\nMinimum working: NONE (all tests failed)")


if __name__ == "__main__":
    main()
