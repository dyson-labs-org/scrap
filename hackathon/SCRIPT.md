# SISL v3 — Covert Satellite Handshake Protocol

## Authors' Reference: How This Works

This document is a detailed reference for the hackathon team. It describes
what we built, how each piece works, and why the design choices were made.
Not intended to be read verbatim — use it as background for explaining the
system to judges and audience.

---

## The One-Sentence Pitch

SISL is a covert satellite handshake protocol that lets two spacecraft
initiate an encrypted communication channel without revealing to any
observer that a signal was even transmitted.

---

## What Problem Are We Solving?

Two satellites need to find each other and agree on a private channel. The
constraints:

1. **Covertness** — an adversary with a spectrum analyzer shouldn't see any
   signal. The transmission must look like thermal noise.
2. **Authentication** — only the intended recipient should be able to decode
   the handshake. Everyone else sees noise.
3. **Forward secrecy** — even if a long-term key is later compromised, past
   handshakes can't be decrypted.
4. **Low SNR** — satellite links have terrible signal-to-noise ratios. The
   signal must be recoverable at link budgets where conventional radios see
   nothing.

---

## System Overview

The protocol has three layers, each solving a different part of the problem:

```
┌─────────────────────────────────────────────────────┐
│  CRYPTO LAYER (sisl_crypto.py)                      │
│  X3DH key agreement + ChaCha20-Poly1305 AEAD        │
│  Provides: authentication, encryption, forward secrecy│
├─────��───────────────────────────────────────────────┤
│  FEC LAYER (sisl_fec.py + sisl_crypto.py)           │
│  Rate-1/2 K=9 convolutional code + block interleaver │
│  Provides: error correction, burst tolerance          │
├─────────────────────────────────────────────────────┤
│  PHYSICAL LAYER (sisl_framer.py + sisl_rx.py)       │
│  DSSS spreading + DBPSK + matched filter              │
│  Provides: covertness, processing gain, phase immunity│
└────────────────────────────��────────────────────────┘
```

---

## Layer 1: Cryptography

### The Handshake

Alice (ground station) wants to contact Bob (satellite). Alice knows Bob's
long-term public key. The handshake is:

1. **Alice generates a fresh ephemeral keypair** — used once, then destroyed.
2. **ECDH(ephemeral_private, bob_public)** → shared secret DH1 (32 bytes).
3. **HKDF-SHA256** derives a ChaCha20 key (32 B) and nonce (12 B) from DH1.
4. **ChaCha20-Poly1305** encrypts the payload (Alice's identity, desired
   frequency, mode flags, 8-byte random nonce) and produces a 16-byte
   authentication tag.
5. The encrypted frame (133 bytes) goes on the air.

### Why X3DH?

X3DH is the same key agreement that Signal Messenger uses. It provides:

- **Authenticated key agreement** — Bob's Poly1305 tag verifies that the
  sender knew a key whose ECDH with Bob's static key produces the right
  shared secret.
- **Forward secrecy** — Alice's ephemeral key is destroyed after one use.
  Even if her long-term key is later compromised, the ephemeral private key
  no longer exists, so past sessions can't be decrypted.
- **Identity oracle** — the Poly1305 tag is the cheapest possible test for
  "is this message for me?" Wrong receiver → wrong ECDH → wrong key → tag
  fails. No need to decode the body to reject.

### The Hail Frame (133 bytes)

```
Bytes    Field               Notes
0-3      ASM (0x1ACFFC1D)   Attached Sync Marker — frame delimiter
4        Version (0x03)      Protocol version
5        Msg type (0x01)     HAIL
6-69     Ephemeral pubkey    64 bytes (Elligator² stub, not yet
                             indistinguishable from random)
70-116   Ciphertext          47 bytes of encrypted HailBody
117-132  Poly1305 tag        16 bytes — identity oracle
```

### The HailBody (47 bytes, encrypted)

```
Bytes    Field               Notes
0-32     Caller's static pub 33 bytes, compressed secp256k1
33-34    Freq offset         2 bytes, MHz offset for data channel
35       Bandwidth code      Channel width
36       Mode                DSSS/FHSS/Hybrid
37       Chip rate code      In 0.1 Mcps units
38-45    Body nonce          8 bytes random — replay protection
46       Flags               Capability bits
```

Only 12 bytes of this are "user payload" (freq, mode, nonce, flags). The
rest is the caller's public key needed for the ACK handshake. That's the
nature of authenticated key agreement — the keys are bulky.

### Curve Choice: secp256k1

We use secp256k1 (same as Bitcoin) rather than Curve25519 because the
Elligator² mapping (for making public keys indistinguishable from random
bytes) is well-studied on short Weierstrass curves. The current
implementation is a stub — the encoding is trivially distinguishable. A
production system would implement the full Elligator² map.

---

## Layer 2: Forward Error Correction

### Why FEC?

At the SNR levels where DSSS operates (post-despreading SNR of 14-30 dB),
raw bit error rates are 10⁻² to 10⁻⁵. A single bit error in the 127-byte
payload corrupts the Poly1305 tag → frame rejected. FEC lets us correct
errors that the physical layer can't avoid.

### The Code: Rate-1/2, Constraint Length 9

We use the **NASA/Voyager standard** convolutional code:

- **Rate 1/2** — every payload bit produces 2 coded bits (100% overhead)
- **Constraint length K=9** — the encoder has 8 bits of memory (256 states)
- **Generator polynomials**: G1 = 0o753, G2 = 0o561 (octal)
- **Free distance d_free = 12** — can correct up to 6 errors per constraint
  length span

This code was literally sent to the outer solar system on Voyager 1 and 2.
It's simple, well-understood, and gives ~8 dB of coding gain — meaning the
receiver can operate at 8 dB lower SNR than without FEC.

### Encoding Pipeline

```
127 bytes payload (1016 bits)
  → convolutional encode → 2048 coded bits
  → block interleave (32×64 matrix) → 2048 bits (reordered)
  → differential encode (seed = last header bit) → 2048 bits
  → prepend 48-bit uncoded header (ASM + version + type)
  → 2096 channel bits total
```

### Block Interleaving

A burst of interference (e.g., a WiFi frame at 2.4 GHz) wipes out a
contiguous run of coded bits. Viterbi decoding can correct scattered
errors but not long bursts. The interleaver solves this:

- **Write** the 2048 coded bits row-by-row into a 32×64 matrix
- **Read** them column-by-column

A 64-symbol interference burst (~65 ms at 1 Mcps) becomes 64 scattered
single-bit errors spaced 32 positions apart — well within Viterbi's
correction capability.

### Soft Viterbi Decoding

The receiver doesn't just decide "bit 0 or bit 1" — it produces a **soft
LLR** (Log-Likelihood Ratio) for each bit: a floating-point number whose
sign indicates the most likely bit value and whose magnitude indicates
confidence.

The Viterbi decoder uses these magnitudes to make better decisions. When
a weak bit disagrees with the surrounding codeword structure, the decoder
overrules it. This is worth ~2 dB over hard decisions — free performance
from keeping the analog information.

---

## Layer 3: Physical Layer (DSSS + DBPSK)

### Direct-Sequence Spread Spectrum

This is the core covertness mechanism. Each of the 2096 channel bits is
multiplied by a 1023-chip pseudorandom sequence (a Gold code). The result:

- **Before spreading**: 2096 bits at 1 Mbps → 1 MHz bandwidth, clearly
  visible on a spectrum analyzer
- **After spreading**: 2096 × 1023 = 2.14 million chips at 1 Mcps → 1 MHz
  bandwidth, but the energy per Hz is 1023× lower (30 dB below the noise
  floor)

Anyone without the spreading code sees flat noise. The receiver, which
knows the code, correlates against it and recovers the signal with 30 dB
of processing gain.

### The Gold Code

Our spreading code is 1023 chips long, generated by:

```python
seed = SHA256("SISL-public-hailing-code-v3")
code = generate_dsss_code(seed, length=1023)  # ±1 int8 array
```

The code is deterministic from the seed — any receiver with the seed can
despread. For the public hailing channel, this is intentional. For private
channels, the seed would be derived from the session key.

### DBPSK: Differential Binary Phase-Shift Keying

Standard BPSK maps bit 0 → +1 and bit 1 → -1. But BPSK has a 180° phase
ambiguity — the receiver can't tell +1 from -1 without a phase reference.
And cheap SDR oscillators drift in phase over the 2-second frame duration.

DBPSK solves both problems by encoding the bit in the **phase change**
between consecutive symbols rather than the absolute phase:

- **TX**: differentially encode before BPSK mapping
- **RX**: decode by multiplying adjacent symbols:
  `LLR[k] = Re(peak[k] × conj(peak[k-1]))`

If the phases drift by the same amount on both symbols (constant drift),
the product cancels it. The body LLRs are immune to oscillator drift,
absolute phase offset, and the 180° BPSK ambiguity.

### The Matched Filter

The matched filter is the mathematical operation that extracts the signal
from noise. It correlates the received samples with the known spreading
code:

```
MF_output[n] = Σ(received[n+k] × code[k], k=0..1022)
```

At a symbol boundary where the code aligns, all 1023 terms add coherently
→ large output. Everywhere else, the terms are ±1 random → they cancel to
near zero. The peak-to-noise ratio is √1023 ≈ 32 (30 dB).

We implement this as an FFT convolution (`scipy.signal.fftconvolve`) for
efficiency — O(N log N) instead of O(N²).

### Frequency Estimation: The FFT-Squared Trick

Cheap SDR oscillators have frequency errors of 20-100 ppm. At 5 GHz,
50 ppm = 250 kHz. If uncorrected, this 250 kHz offset rotates the phase
by 250,000 × 2π × 1.023 ms = 1608 radians per symbol — the matched
filter output is noise.

We need to estimate the carrier frequency offset before despreading. But
the signal is 17 dB below the noise — we can't see it in the spectrum.

The trick: **square the signal**. For BPSK: s(t) = A × d(t) × exp(jωt)
where d(t) = ±1. Squaring: s²(t) = A² × exp(j2ωt) — the data modulation
vanishes (since (±1)² = 1), leaving a clean spectral line at twice the
carrier offset.

We FFT the squared signal, find the top 5 peaks, and validate each by
applying the correction and checking if the matched filter sees periodic
structure (a real DSSS signal has peaks every 1023 chips; a clock spur
doesn't). The candidate with the best periodic score wins.

### Symbol Tracking

After frequency correction and matched filtering, we have a stream of
complex peak values — one per symbol (one per 1023 chips). The tracker:

1. Finds the strongest MF peak (argmax of |MF output|)
2. Steps forward by one symbol period (1023 × samps_per_chip samples)
3. Searches a local window for the next peak (parabolic sub-sample
   interpolation for timing accuracy)
4. Records the complex peak value
5. Repeats for all 2096 symbols

If the peak drops below a lock floor (2× median noise) for too many
consecutive symbols, the tracker declares "TRACK LOST."

### The Soft Correlator: Finding the Frame Start

The TX loops the same frame forever. The tracker starts at a random
position within the repeating frame. We need to find where the ASM
(0x1ACFFC1D) begins.

The soft correlator uses the **differential polarity** of the ASM's 32
bits. For each pair of adjacent bits, the expected differential is +1
(same) or -1 (different). We compute the actual differential at every
position in the peak stream and correlate with the expected template:

```
score[i] = Σ expected_diff[j] × actual_diff[i+j], j=0..30
```

The position with the highest |score| is the ASM start. We try the top 5
candidates in case noise corrupts the argmax.

---

## LLR Accumulation

The TX loops the same frame continuously. Each 6-second RX block produces
one set of 2048 body LLRs. If single-frame decode fails (SNR too low for
Viterbi to correct all errors), we **accumulate** LLRs across multiple
blocks:

```
accumulated[k] += body_llrs_this_block[k]
```

The signal component adds coherently (same sign every time). The noise
partially cancels (random sign). After N copies, SNR improves by √N
(3 dB per 4× copies).

Key property: DBPSK body LLRs are **phase-invariant** — the absolute
carrier phase can differ between blocks, but the differential product
always gives the correct sign. No polarity alignment needed between copies.

The accumulator only accepts blocks where |Δf| < 50 kHz (the frequency
estimate is plausible — spur-locked blocks produce noise LLRs that would
dilute the signal).

---

## Automatic Gain Control (AGC)

The RX AGC adjusts the SDR's gain to keep the matched filter peak near a
target magnitude. Three mechanisms:

1. **Proportional step** — adjust gain by 10×log10(target/actual) dB per
   block, clamped to ±6 dB
2. **ADC saturation detection** — if p99 of |samples| exceeds 0.9 for 2+
   consecutive blocks, reduce gain and set a ceiling. The proportional AGC
   can't exceed the ceiling.
3. **Warmup phase** — suppress auto-PPM frequency corrections for the first
   3 blocks while the AGC stabilizes, to prevent spur-chasing before the
   signal level is correct.

The saturation check requires 2 consecutive blocks to avoid false triggers
from transient WiFi bursts at 2.4 GHz.

---

## Auto-PPM Frequency Tracking

After the AGC stabilizes, the auto-PPM tracks residual frequency drift
(from crystal warm-up, temperature changes):

1. Each block's FFT-squared estimates the residual offset Δf
2. The median of the last 4 estimates is applied as a retune
3. Retunes every 10 seconds after settling (tighter at high frequencies
   where drift in Hz is larger)

Per-device PPM calibration values are stored by serial number and applied
at startup, placing the signal within a few kHz of baseband before the FFT
search begins.

---

## Link Budget & TX Power

The signal is designed to be invisible. The minimum TX power for a given
distance is:

```
P_tx = noise_floor - processing_gain - fec_gain + required_SNR + path_loss
     = -107 dBm  - 30 dB          - 8 dB     + 16 dB        + FSPL(d,f)
```

| Distance | 433 MHz | 915 MHz | 2.4 GHz | 5 GHz |
|----------|---------|---------|---------|-------|
| 1 m      | -104 dBm | -98 dBm | -89 dBm | -83 dBm |
| 100 m    | -64 dBm | -58 dBm | -49 dBm | -43 dBm |
| 1 km     | -44 dBm | -38 dBm | -29 dBm | -23 dBm |

At bench distances (1 m), the HackRF at VGA=0 (-45 dBm) is already too
powerful at sub-GHz. At 5 GHz / 1 km, you'd need VGA≈40 + AMP.

The golden rule: **if you can see the signal on a waterfall, you're too
loud.** Target SNR ≈ +16 dB post-despreading — enough to decrypt with a
few dB of margin, invisible on any spectrum analyzer.

---

## What We Demonstrated

| Frequency | Band | Distance | TX Power | Result |
|-----------|------|----------|----------|--------|
| 433 MHz   | ISM  | 1 ft     | VGA=0    | Decrypt on block 1 |
| 868 MHz   | ISM  | 1 ft     | VGA=0    | Decrypt on block 1 |
| 915 MHz   | ISM  | 1 ft     | VGA=0    | Decrypt on block 2 |
| 2437 MHz  | WiFi | 1 ft     | VGA=25   | Decrypt (with WiFi interference) |
| 4965 MHz  | C-band | 1 ft   | VGA=40   | Decrypt on block 12 |

Hardware: two HackRF One ($340 each) with rubber duck antennas, one
Nooelec RTL-SDR ($25). All on the same laptop via USB.

---

## What's Left for Production

1. **Elligator² encoding** — make the ephemeral public key
   indistinguishable from random bytes (currently a stub)
2. **Private spreading codes** — derive per-session codes from the session
   key so only the two parties can despread
3. **ACK response** — the responder's reply (95 bytes, mutual
   authentication via DH2+DH3)
4. **Frequency hopping** — FHSS mode for interference avoidance
5. **Doppler compensation** — for LEO satellites at 7.5 km/s, ±40 kHz
   Doppler at 915 MHz
6. **Rate adaptation** — longer spreading codes (2047, 4095) for weaker
   links, shorter for faster handshakes
