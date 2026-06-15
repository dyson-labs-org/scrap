SISL Hackathon Demo Plan
========================

Objective
---------
Implement a live, visual demonstration of the SISL (Secure Inter-Satellite Link)
hailing protocol using software-defined radio. Show that a cryptographically
authenticated signal can be transmitted below the noise floor, and that only a
party with the correct key material can recover it — the core LPI/LPD property
of SISL.

Demo Narrative
--------------
"Two satellites approach each other. An observer with a spectrum analyzer sees
nothing unusual — the signal is below the noise floor. Yet the satellites
complete a cryptographic handshake, establish a secure channel, and exchange
an authorized task request. We show this happening live on the bench."

Hardware
--------
- HackRF One (x3):
    A: Satellite A — TX hail, RX ACK
    B: Satellite B — RX hail, TX ACK (full two-way RF demo)
    C: Passive observer — RX only, showing 2.4 GHz spectrum with live WiFi
       traffic and the hidden DSSS signal side by side
- RF connection: two 30dB SMA attenuators in series between HackRF A TX and
  HackRF B RX, and between HackRF B TX and HackRF A RX. See Link Budget.
- Nooelec NESDR XTR v2: spare / backup (tops out at ~2.3 GHz, not used at 2.4)
- Ham It Up Plus v2: set aside (HF upconverter, not needed)

Software Stack
--------------
- GNU Radio 3.10+          signal processing and SDR hardware abstraction
- SoapySDR                 hardware abstraction layer (HackRF + RTL-SDR)
- gr-soapy                 GNU Radio SoapySDR source/sink blocks
- Python 3.x               crypto logic (already in SISL.md reference code)
- cryptography (pip)       ChaCha20, AES-GCM, HKDF
- coincurve or python-secp256k1   secp256k1 ECDH for X3DH
- Gqrx                     live spectrum/waterfall display for audience

Installation
------------
    sudo pacman -S gnuradio gnuradio-companion soapysdr python-cryptography
    pip install coincurve
    # HackRF support
    sudo pacman -S hackrf soapysdr-hackrf
    # RTL-SDR support
    # RTL-SDR support (spare device only, not used in main demo)
    sudo pacman -S rtl-sdr soapysdr-rtlsdr


Phase 1: DSSS "Hidden Signal" Demo (Day 1, ~6 hours)
------------------------------------------------------
Goal: visually demonstrate that a DSSS signal is below the noise floor until
the correct spreading code is applied.

1.1 Transmit side (HackRF via GNU Radio)
    - Generate ChaCha20 DSSS spreading code using SISL public hailing seed:
        seed = SHA256("SISL-public-hailing-code-v2")
        code = generate_dsss_code(seed, length=1023)  # from SISL.md §4.5
    - BPSK-modulate a test message, spread with 1023-chip code at 1 Mcps
    - Drive HackRF A sink at 2437 MHz (WiFi channel 6)
    - Transmit power: minimum HackRF setting; see Link Budget below

1.2 Receive side (HackRF B via GNU Radio)
    - HackRF B source → wideband spectrum sink → display in Gqrx
    - Audience sees: WiFi traffic, no new signal visible
    - Apply correct ChaCha20 code → correlator output shows data
    - Apply wrong code → correlator output: noise

1.3 Observer (HackRF C via Gqrx)
    - HackRF C running Gqrx at 2437 MHz throughout entire demo
    - Shows live WiFi traffic before, during, and after DSSS transmission
    - Never shows the DSSS signal — this is the "nothing to see here" view

1.3 GNU Radio blocks needed
    - SoapySDR Source (HackRF B, 2.4 Msps — Nyquist for 1 Mcps signal)
    - SoapySDR Sink (HackRF A)
    - chunks_to_symbols (BPSK mapping, then multiply by spread code)
    - Multiply (spreading/despreading) — apply code BEFORE symbol decisions
    - BPSK decision block AFTER despreading (not before)
    - QT GUI Frequency Sink (waterfall for audience)
    - QT GUI Time Sink (correlator output)

    IMPORTANT: gr-digital BPSK demod makes symbol decisions before
    despreading — this is wrong for DSSS. Signal chain must be:
      TX: bits → BPSK symbols → multiply(spread_code) → HackRF
      RX: HackRF → multiply(spread_code) → integrate → bit decision

    Code sync (acquisition): gr-digital has no stock DSSS correlator.
    For Phase 1 demo, skip acquisition — use a fixed known code offset
    (both sides start at chip 0). This avoids implementing a sliding
    correlator and saves 2-3 hours. Note the gap explicitly in the demo.

Key file: sisl_dsss_demo.grc


Phase 2: Encrypted Hailing Handshake (Day 2, ~8 hours)
----------------------------------------------------------
Goal: implement SISL hail + ACK exchange with real X3DH key agreement.

2.1 Crypto layer (pure Python, no GNU Radio)
    Implement the SISL.md §4 functions directly:

    a) Key setup
       - Generate two secp256k1 identity keypairs (satellite A, satellite B)
       - Generate ephemeral keypairs per session
       - Store as {norad_id: pubkey} trust list (simple dict for demo)

    b) Hail construction (satellite A)
       - DH1 = ECDH(caller_eph_priv, responder_static_pub)
       - hail_key = HKDF(DH1, salt=SHA256("SISL-v2-hail"), info=pack(">I", target_norad))
       - Encrypt 17-byte hail body with AES-256-GCM(hail_key, random_IV)
       - Assemble 91-byte hail frame (SISL.md §5.2)

    c) ACK construction (satellite B)
       - Compute DH1, DH2, DH3 (full X3DH)
       - Derive all session keys via derive_session_keys() (SISL.md §4.3)
         NOTE: derive_session_keys() requires caller_eph_pub AND
         responder_eph_pub for transcript binding — do not pass only
         DH outputs; the ephemeral public keys are required parameters.
       - Encrypt 12-byte ACK body with ack_key

    d) Session establishment (satellite A)
       - Receive ACK, compute DH2+DH3, derive same session keys
       - Verify nonce echo in ACK body

    Test this layer independently with loopback (no radio) first.
    Reference: SISL.md §21 test vectors for verification.

    Key file: sisl_crypto.py

2.2 Frame transport (GNU Radio)
    - Hail frame (91 bytes) → packetize → DSSS spread with PUBLIC code
      → HackRF A TX at 2437 MHz
    - HackRF B RX → despread with PUBLIC code → depacketize
      → pass bytes to Python crypto layer
    - ACK frame: HackRF B TX → HackRF A RX, same path in reverse

2.3 GNU Radio custom block
    - Python block: SISLFramer
      input: byte stream from crypto layer
      output: BPSK symbols with DSSS spreading applied
    - Python block: SISLDeframer
      input: correlated BPSK symbols
      output: byte stream to crypto layer

    Key file: sisl_hail_flow.grc + sisl_framer.py


Phase 3: P2P Secure Channel + SCRAP Integration (Day 3 or stretch goal)
------------------------------------------------------------------
Goal: after handshake, switch to session-derived spreading code and pass a
SCRAP capability token + task request through the SISL link.

3.1 P2P channel
    - After ACK, both sides derive spreading_seed from session keys
    - Generate new DSSS code: generate_dsss_code(spreading_seed)
    - Switch GNU Radio multiply block to session-derived code
    - This channel is invisible to anyone who didn't witness the handshake

3.2 SCRAP task over SISL
    - Serialize a CapabilityToken (from existing scrap-core implementation)
    - Serialize a TaskRequest
    - Send over the established P2P channel
    - Receiving side verifies token, sends back ProofOfExecution stub

3.3 End-to-end demo flow
    1. Audience sees waterfall: noise only
    2. Satellite A transmits hail (below noise floor via DSSS)
    3. Satellite B decrypts hail, completes X3DH, sends ACK
    4. P2P channel established with secret spreading code
    5. SCRAP TaskRequest transmitted over P2P channel
    6. Token verified, task "executed", proof returned
    7. Audience sees the handshake messages decoded on screen

    Key file: sisl_scrap_demo.py


Frequency Plan
--------------
Use 2.4 GHz ISM band to hide signal inside active WiFi traffic:

    Hailing channel: 2437.0 MHz (WiFi channel 6 center — typically busy)
    P2P channel:     2440.0 MHz (3 MHz separation, still within channel 6)

Demo narrative: HackRF C shows the 2.4 GHz waterfall with live WiFi from
the room. Audience sees their own network traffic. Satellite A and B
complete a cryptographic handshake on the same spectrum, invisible to
anyone without the spreading code — including the WiFi devices.

HackRF A/B TX power: minimum setting; see Link Budget below
HackRF C: 2.4 Msps sample rate, center 2437 MHz, RX only


Signal Parameters for Demo
--------------------------
Bench configuration scaled from SISL.md §10.2:

    Chip rate:         1 Mcps  (HackRF bandwidth easily handles this)
    Hail data rate:    1 kbps
    Processing gain:   10*log10(1e6/1e3) = 30 dB
    P2P data rate:     10 kbps
    FEC:               omitted for demo simplicity (note gap to audience)


Link Budget and Attenuation Chain
----------------------------------
CRITICAL: a single 30dB attenuator is NOT sufficient. With HackRF at
minimum TX power (~-10 dBm) and 30dB attenuation:
  Received power = -10 - 30 = -40 dBm
  HackRF noise floor (1 MHz BW, 2437 MHz) ≈ -100 dBm
  Signal arrives 60 dB ABOVE noise floor — plainly visible, demo fails.

Required total attenuation to put signal below noise floor:
  Target: received power < noise floor (-100 dBm)
  HackRF min TX: ~-10 dBm
  Required attenuation: >90 dB

Bench setup: two 30dB attenuators in series (60dB) + HackRF at minimum
gain setting. Adjust until signal disappears in Gqrx waterfall, then
verify despreading recovers it. Use the 1+2+3+6+10+20 dB attenuator kit
to fine-tune total attenuation.


Existing Code Inventory
-----------------------
The following is already implemented in Rust in scrap-core/:

    scrap-core/src/crypto.rs     secp256k1 ECDSA sign/verify, SHA-256, key derivation
                                compute_binding_hash(), compute_proof_hash()
                                NOTE: uses ECDSA, not BIP-340 Schnorr as in SISL.md
                                Fine for demo; production should migrate to Schnorr

    scrap-core/src/token.rs      CapabilityTokenBuilder, TokenValidator
                                Full sign + validate pipeline working

    scrap-core/src/types.rs      CapabilityToken, TaskRequest, CapPayload, Constraints
                                CBOR-encoded, no_std compatible

    scrap-core/src/cbor.rs       encode/decode for all message types

    test-vectors/generate.py    Python test vector generator using secp256k1 + cbor2
                                Signs tokens, execution proofs, payment bindings
                                Can be extended for SISL demo

    test-vectors/computed.json  Pre-computed reference vectors

What does NOT exist yet (needs to be written for hackathon):

    SISL crypto layer           X3DH key agreement (DH1/DH2/DH3)
                                derive_hail_key(), derive_session_keys()
                                ChaCha20 DSSS/FHSS code generation
                                AES-256-GCM hail/ACK frame encrypt/decrypt

    SISL frame encoding         91-byte hail frame (SISL.md §5.2)
                                86-byte ACK frame (SISL.md §5.3)

    GNU Radio integration       SoapySDR source/sink for HackRF
                                DSSS TX/RX signal chain
                                GNU Radio flowgraphs (.grc files)

    SCRAP-over-SISL glue        Serialize existing scrap-core tokens into SISL
                                P2P channel transport for CapabilityToken/TaskRequest


File Structure
--------------
hackathon/
    sisl_crypto.py          NEW: X3DH, hail/ACK crypto — port from SISL.md §4
    sisl_dsss.py            NEW: ChaCha20 DSSS/FHSS — copy verbatim from SISL.md §4.5
    sisl_framer.py          NEW: GNU Radio Python block for SISL TX/RX framing
    sisl_dsss_demo.grc      NEW: Phase 1 GNU Radio flowgraph
    sisl_hail_flow.grc      NEW: Phase 2 GNU Radio flowgraph
    sisl_scrap_demo.py      NEW: Phase 3 — calls scrap-core via FFI or reimplements
                                 token serialization in Python using existing
                                 test-vectors/generate.py as reference
    test_sisl_crypto.py     NEW: verify sisl_crypto.py against SISL.md §21 test vectors


Starting Point: What to Copy vs. Write
---------------------------------------
COPY verbatim from SISL.md (fully specified, reference implementation included):
    generate_dsss_code()        SISL.md §4.5 + §21.6
    generate_fhss_sequence()    SISL.md §4.5
    derive_session_keys()       SISL.md §4.3 + §21.6
    derive_hail_key()           SISL.md §4.4
    SISL_HAIL_SEED constant     SISL.md §4.6
    Cryptographic constants     SISL.md §21.5 (pre-computed SHA256 values)

WRITE using SISL.md as spec (straightforward struct packing):
    encode_hail_frame()         91-byte layout from SISL.md §5.2
    decode_hail_frame()
    encode_ack_frame()          86-byte layout from SISL.md §5.3
    decode_ack_frame()

WRITE using test-vectors/generate.py as template (Python secp256k1 already set up):
    sisl_scrap_demo.py          Reuse existing token serialization patterns;
                                generate.py already shows how to build/sign tokens

VERIFY with test vectors before touching radio:
    SISL.md §21 provides expected outputs for derive_session_keys() and
    the DSSS code. Write test_sisl_crypto.py against these first.
    The existing test-vectors/verify.py shows the testing pattern to follow.


Stretch Goal: 5 GHz WiFi Band
-----------------------------
HackRF One covers up to 6 GHz — the 5 GHz WiFi band (IEEE 802.11a/n/ac)
is fully within range. Repeating the demo at 5 GHz is more impressive:
- 5 GHz WiFi is denser at most venues (all modern 802.11ac/WiFi 6 devices)
- Less crowded at any single channel than 2.4 GHz, making the "hidden
  signal" effect cleaner (audience sees structured 802.11 bursts, not a
  wall of noise)
- Demonstrates SISL is not limited to any one band

Candidate channels:
    5180 MHz  (channel 36, U-NII-1, commonly used indoors)
    5240 MHz  (channel 48, U-NII-1)
    5745 MHz  (channel 149, U-NII-3, often busy at conferences)

P2P channel: offset by 20 MHz from hailing channel (802.11 channel spacing).

What changes from 2.4 GHz demo:
- Update center frequency in GNU Radio flowgraph (one parameter change)
- Verify HackRF LO locks cleanly at chosen 5 GHz frequency (should be fine)
- Recheck link budget: free-space path loss increases ~6 dB vs 2.4 GHz at
  same bench distance — may need slightly less attenuation in the chain
- HackRF C observer: retune Gqrx to 5 GHz channel to show 802.11 traffic

This is a one-line frequency change once the 2.4 GHz demo is working.
Reserve 30 minutes at end of hackathon to demonstrate it.


Fallback / Minimum Viable Demo
-------------------------------
If Phase 2-3 slip, Phase 1 alone is a complete demo:
- DSSS hidden signal is visually striking and explains the core LPI property
- Can be implemented in ~2 hours with GNU Radio Companion (no custom blocks)
- Talks directly to the satellite stealth communication use case


Risks and Mitigations
---------------------
Risk: Signal visible above noise floor — demo narrative fails
Mitigation: bench-test attenuation chain FIRST with a CW tone before adding
DSSS. Dial in attenuation until tone disappears in Gqrx, then verify
despread reveals it. Need >90dB total; use stacked attenuators from kit.

Risk: DSSS code acquisition (synchronization) not a stock GNU Radio block
Mitigation: skip acquisition for Phase 1 — start both TX and RX at chip 0
(fixed offset, no sliding correlator). This is sufficient for the demo.
State the simplification explicitly. A real system needs a PN correlator;
this is a known gap, not a bug.

Risk: GNU Radio BPSK demod wrong for DSSS
Mitigation: do NOT use gr-digital BPSK demod block directly. Build the
RX chain as: HackRF → multiply(code) → integrate over chip period →
threshold → bits. This is simpler than standard BPSK demod anyway.

Risk: HackRF sample rate / bandwidth mismatch
Mitigation: set HackRF B to exactly 2.4 Msps. Do not use 1 Msps (Nyquist
violation for 1 Mcps chip rate). 2.4 Msps is a stable, well-tested rate.

Risk: GNU Radio custom Python blocks have latency/buffering issues
Mitigation: prototype crypto layer as standalone Python first (loopback via
pipes), then wrap in GNU Radio blocks only for the RF interface

Risk: Ham It Up Plus in signal path
Note: Ham It Up is an HF upconverter (covers ~100 kHz - 65 MHz input).
Does not cover 2.4 GHz. Set aside entirely.

Risk: HackRF half-duplex on single unit (now resolved)
Two HackRF units: one per satellite. Symmetric full-duplex demo possible.


Demo Script (5 minutes)
-----------------------
0:00 - Show HackRF C waterfall: 2.4 GHz band full of WiFi traffic
       "This is your WiFi. These are your devices."
0:30 - "Satellite A initiates contact" — HackRF A begins transmitting DSSS hail
0:45 - HackRF C waterfall: unchanged — WiFi traffic, no new signal visible
       "Our signal is already transmitting. You can't see it."
1:00 - HackRF B: apply correct ChaCha20 spreading code → hail decodes
1:15 - Show decoded hail frame fields: target NORAD, encrypted body
1:30 - "Satellite B computes X3DH handshake" — show key derivation on screen
2:00 - HackRF B transmits ACK, session keys derived on both sides
2:30 - "P2P channel established with session-derived spreading code"
3:00 - SCRAP task request transmitted over P2P channel
3:30 - Capability token verified, task accepted, proof returned
4:00 - Switch back to HackRF C: "WiFi world saw nothing. Not a single packet."
4:30 - Q&A
