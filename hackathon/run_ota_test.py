#!/usr/bin/env python3
"""One-shot OTA call/respond test with timing."""
import subprocess, time, sys, re
from pathlib import Path

WD = Path(__file__).resolve().parent

print("Starting respond...", flush=True)
resp = subprocess.Popen(
    [sys.executable, str(WD / 'demo.py'),
     '--mode', 'respond', '--freq', '915',
     '--duration', '180', '--serial', '930c64dc279e7bc3',
     '--rx-lna', '20', '--rx-vga', '20', '--rx-amp', '--tx-vga', '3'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(WD))
time.sleep(6)

print("Starting call...", flush=True)
t0 = time.time()
call = subprocess.Popen(
    [sys.executable, str(WD / 'demo.py'),
     '--mode', 'call', '--freq', '915',
     '--duration', '120', '--serial', '78d063dc2b6d2267',
     '--tx-vga', '3', '--rx-lna', '20', '--rx-vga', '20', '--rx-amp'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(WD))

try:
    call_out, _ = call.communicate(timeout=240)
except subprocess.TimeoutExpired:
    call.kill()
    call_out, _ = call.communicate()

call_elapsed = time.time() - t0
time.sleep(5)
resp.terminate()
try:
    resp_out, _ = resp.communicate(timeout=20)
except subprocess.TimeoutExpired:
    resp.kill()
    resp_out, _ = resp.communicate()

ansi = re.compile(r'\x1b\[[0-9;]*m')
ct = ansi.sub('', call_out.decode('utf-8', errors='replace'))
rt = ansi.sub('', resp_out.decode('utf-8', errors='replace'))

print(f"\n{'='*60}")
print("CALL OUTPUT (last 60 lines):")
print('='*60)
for line in ct.strip().split('\n')[-60:]:
    print(line)

print(f"\n{'='*60}")
print("RESPOND OUTPUT (last 60 lines):")
print('='*60)
for line in rt.strip().split('\n')[-60:]:
    print(line)

print(f"\n{'='*60}")
print(f"CALL EXIT: {call.returncode}")
print(f"RESP EXIT: {resp.returncode}")
print(f"CALL ELAPSED: {call_elapsed:.1f}s")

# Check for key milestones
passed = "HANDSHAKE COMPLETE" in ct or "SESSION ESTABLISHED" in ct or "PAYLOAD DELIVERED" in ct
print(f"PASSED: {passed}")
sys.exit(0 if passed else 1)
