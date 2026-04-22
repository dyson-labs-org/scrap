# Agent Preamble — hackathon (SISL/RLNC/DSSS/SDR)

Read this BEFORE starting your task. Subagents do NOT see CLAUDE.md.

## The Project

A Python SDR (Software-Defined Radio) implementation of SISL (Steganographic Integrated Spread-Spectrum Link), a covert radio protocol using DSSS (Direct-Sequence Spread Spectrum) with 1023-chip PN (Pseudo-Noise) codes for spread-spectrum steganography. Payloads are delivered via RLNC (Random Linear Network Coding) over GF(2^8) with sparse fountain-code degree distribution. All frames are protected by ChaCha20-Poly1305 AEAD (Authenticated Encryption with Associated Data); key exchange uses X3DH (Extended Triple Diffie-Hellman) on secp256k1. Hardware is HackRF One via SoapySDR.

## Non-Negotiable Constraints

- samps_per_chip=2 on RX path (not 8 — TX vs RX mismatch is a known bug source)
- ASM = b"\x1A\xCF\xFC\x1D" — never change without updating all detection paths
- SISL_VERSION = 0x03 — frame version byte is part of the pilot sequence used for phase estimation
- Nonces are HKDF-derived and must never repeat under the same key
- No ARQ (Automatic Repeat reQuest) — SISL is send-only; RLNC provides reliability without retransmission requests
- GF(2^8) arithmetic must use the correct irreducible polynomial — changing it silently breaks all coefficient tables
- Trial decryption runs ECDH + ChaCha20-Poly1305 per hail candidate — this is intentionally expensive; do not cache across sessions

## Key Proven Results (Do NOT Re-Derive)

| Result | Evidence |
|--------|----------|
| samps_per_chip=2 for RX (not 8) | ad8c9b3 commit message: "Fix ACK decode: samps_per_chip=2, not 8 (TX vs RX mismatch)" |
| Hail frame = 133 bytes | sisl_crypto.py:HAIL_FRAME_LEN=133 (4+1+1+64+47+16) |
| ACK frame = 95 bytes | sisl_crypto.py:ACK_FRAME_LEN=95 (4+1+1+64+9+16) |
| FEC pilot is 48 bits uncoded | sisl_crypto.py header comment: ASM+ver+type = 6 bytes = 48 bits |
| Robust soliton R = c*log(K/delta)*sqrt(K) | sparse_rlnc.py:robust_soliton_cdf() |
| No MSG_NACK constant | 6a6c50e commit: "Remove dead MSG_NACK constant (no ARQ in SISL)" |

## Terminology

| Term | Meaning |
|------|---------|
| SISL | Steganographic Integrated Spread-Spectrum Link — the full protocol |
| Hail | Initial connection frame (caller → responder), msg_type=0x01 |
| ACK | Acknowledgment frame (responder → caller), msg_type=0x02 |
| Payload | RLNC-encoded data frame, msg_type=0x03 |
| PN code | Pseudo-Noise code — 1023-chip maximal-length sequence for spreading |
| samps_per_chip | Samples per chip in the baseband representation (=2 for RX) |
| LLR | Log-Likelihood Ratio — soft bit value for FEC decoder input |
| comb_id | Combination identifier — unique per RLNC coded packet in a session |
| session_prk | Session pseudo-random key — HKDF output used to derive RLNC coefficients |
| X3DH | Extended Triple Diffie-Hellman — Signal Protocol key agreement |
| DH1/DH2/DH3 | Three Diffie-Hellman outputs combined in X3DH |
| Elligator2 | Point encoding that makes EC public keys indistinguishable from random bytes |
| ASM | Attached Sync Marker — 4-byte frame delimiter 0x1ACFFC1D |
| FEC | Forward Error Correction — rate-1/2 K=9 convolutional code |

## Key Modules

| Module | Purpose |
|--------|---------|
| sisl_crypto.py | X3DH, ChaCha20-Poly1305, HKDF, hail/ACK encode/decode |
| sisl_rx.py | DSSS receiver: acquisition, LLR accumulation, FEC decode, trial decrypt |
| sisl_dsss.py | DSSS modulation/demodulation primitives |
| sisl_framer.py | Bit packing, differential encoding, ASM search |
| sisl_fec.py | Convolutional FEC encoder/decoder (soft Viterbi) |
| sisl_payload.py | RLNC frame encode/decode |
| sisl_payload_session.py | RLNC session management (multi-packet delivery) |
| sparse_rlnc.py | Sparse fountain RLNC: robust soliton distribution, GF(2^8) ops |
| demo.py | Top-level call/respond modes for HackRF |
| sdr_devices.py | SoapySDR device abstraction |

## Anti-Patterns

| Pattern | Problem |
|---------|---------|
| samps_per_chip=8 in RX path | TX uses 8, RX uses 2 — mismatch causes correlation failure |
| Adding MSG_NACK or retransmission logic | SISL has no ARQ; RLNC handles reliability |
| Reusing HKDF-derived nonces across sessions | ChaCha20-Poly1305 nonce reuse destroys confidentiality |
| Importing from lib/ without reading module first | API signatures change; always verify before calling |
| Changing irreducible polynomial for GF(2^8) | Silently breaks all coefficient and log tables |
| Caching ECDH trial decryption results across sessions | Each hail must be independently authenticated |
| Integer addition instead of XOR for GF(2^8) field addition | XOR is the only correct field addition |

## Expert Review: Use reviewers.yaml

If you are an expert-review agent: check for `reviewers.yaml` in the project root.
If it exists, read it and adopt the personas defined there. Do NOT invent reviewer
names — use the named experts and their association strings from the file. The
association strings activate domain-specific vocabulary via associative recall;
include them verbatim in your analysis voice.

Select reviewers by matching changed files against `trigger_paths` in the YAML.
If unsure, use the `full_review` composite panel (all four personas).

## Epistemological Rules

1. "Not Found" ≠ "Doesn't Exist". Say "I found no evidence for X (searched: [queries])."
2. Code > Comments > KB > Your assumptions. Test assertions win above all.
3. 5 rounds of kb-research, not 2. Stopping early is the #1 research failure mode.
4. Verify, don't infer. Grep for RESULTS, not TODO comments.
5. State your evidence. Every claim cites file:line, kb-ID, or command output.
6. kb_add before returning. Checkpoint every 10 tool uses.
7. project="hackathon" for all kb_add/kb_search calls.

## Stopping Conditions

Stop and return partial results if:
- Same error 3 times consecutively
- 10+ tool calls with no new findings
- 5+ search phrasings with no results
- 8+ files read without concrete output
