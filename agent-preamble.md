# Agent Preamble — SCRAP (scrap)

Read this BEFORE starting your task. Subagents do NOT see CLAUDE.md.

## The Project

SCRAP (Secure Capabilities and Routed Authorization Protocol) is a unified protocol for
autonomous agent task authorization and payment. It combines cryptographic capability tokens
(SAT-CAP) for command authorization with Bitcoin Lightning Network payments for trustless
settlement. Primary deployment target is LEO inter-satellite operations; the protocol applies
to any intermittently-connected autonomous agents (satellites, drones, vehicles, IoT).

Spec lives in `spec/` under the project root. Key files: SCRAP.md, SISL.md, BIP-SCRAP.md,
HTLC-FALLBACK.md, PTLC-FALLBACK.md, ADVERSARIAL.md, OPERATOR_API.md, SM.md.

## Non-Negotiable Constraints

- Payment coordination occurs between operators on the ground, NOT between satellites. Do not design satellite-to-satellite Lightning routing — this is architecturally impossible given intermittent ISL connectivity.
- Capability tokens are signed by the TARGET satellite's operator, verified by the target against its burned-in operator pubkey. The issuer is always the target's operator.
- Token encoding is TLV (Lightning-native), NOT CBOR. Earlier revisions used CBOR — that was superseded.
- All signatures are BIP-340 Schnorr on secp256k1. No ECDSA. No BLS. No Ed25519.
- Capability attenuation is strictly one-directional: delegated tokens can only NARROW permissions, never expand. Enforce this in any delegation chain logic.
- SISL is the link layer; SCRAP is the application/payment layer. Do not conflate them.
- BIP-SCRAP requires BIP-118 (ANYPREVOUT), BIP-340 (Schnorr), BIP-341 (Taproot). Do not propose designs that require currently unavailable Bitcoin opcodes beyond these three.
- ISL contact windows are 2-15 minutes typical. Protocol must complete in a single contact window. Do not assume persistent connectivity.
- The token authorizes WHAT may be done; the task request specifies HOW MUCH to pay. Payment terms are NOT in capability tokens.

## Key Proven Results (Do Not Re-Derive)

Result                                    Source
----------------------------------------  --------------------------------
Hundreds to thousands of round trips      SCRAP.md §1.2
available in a 2-15 min contact window    (1-50ms ISL latency)
MuSig2 completes in 3 round trips         SCRAP.md §1.2 (~150ms)
HTLC protocol needs ~10 messages          SCRAP.md §1.2 (~500ms)
CCSDS Proximity-1 has no security         SISL.md §2.1 (CCSDS 350.0-G-3)
Operator pubkey burned in at mfg          SCRAP.md §2.1 (trust root)
Token chain_depth: root=0                 SCRAP.md §2.2 token structure

## Terminology

Term              Definition
----------------  -------------------------------------------------------
SAT-CAP           The capability token format (TLV-encoded, Schnorr-signed)
ISL               Inter-Satellite Link
HTLC              Hash Time-Locked Contract (current fallback payment)
PTLC              Point Time-Locked Contract (preferred; requires BIP-118)
Issuer            Target satellite's operator (signs the capability token)
Subject           Commander satellite (token bearer/presenter)
Audience          Target satellite (token verifier)
Capability        String like "cmd:imaging:msi" — what is authorized
Attenuation       Narrowing of permissions in a delegation chain
Contact window    The period two satellites have ISL link visibility
Operator          Ground-based entity that owns/operates satellites
TLV               Type-Length-Value encoding (Lightning-native wire format)
SISL              Secure Inter-Satellite Link (link layer, separate from SCRAP)
X3DH              Extended Triple Diffie-Hellman (key agreement in SISL)

## Key Modules

Path                          Purpose
----------------------------  --------------------------------------------------
spec/SCRAP.md                 Main protocol spec: capability tokens + HTLC flow
spec/SISL.md                  Link-layer protocol: X3DH, AES-GCM, spread spectrum
spec/BIP-SCRAP.md             Bitcoin Improvement Proposal draft (ANYPREVOUT motivation)
spec/HTLC-FALLBACK.md         HTLC fallback (no ANYPREVOUT): current deployable path
spec/PTLC-FALLBACK.md         PTLC + onion routing (preferred, requires BIP-118)
spec/ADVERSARIAL.md           Security analysis for contested/military environments
spec/OPERATOR_API.md          Ground-side REST API for token issuance and service discovery
spec/SM.md                    Task routing state machine (FSM diagrams)
spec/AGENTS.md                Agent interaction model

## Anti-Patterns

Pattern                                          Problem
-----------------------------------------------  -----------------------------------------
Satellite-to-satellite Lightning routing         Impossible: intermittent ISL, not always-on
CBOR encoding for capability tokens              Superseded by TLV (Lightning-native)
ECDSA or Ed25519 signatures                      SCRAP uses BIP-340 Schnorr only
Payment terms inside capability token            Token = authorization; task request = payment
Delegated token expands permissions              Attenuation is strictly monotone-narrowing
Assuming persistent connectivity                 ISL contact windows are 2-15 min; design offline
Designing for unavailable opcodes                Only BIP-118/340/341 are in scope
Ground-side logic on-orbit                       Satellite code must be deterministic, minimal
Symmetric keys for command auth                  SCRAP uses asymmetric: operators sign, sats verify
Multi-hop Lightning over ISL                     Route Lightning between ground operators, not sats

## Epistemological Rules

1. "Not Found" != "Doesn't Exist". Say "I found no evidence for X."
2. Code > Comments > KB > Your assumptions.
3. 5 rounds of kb-research, not 2.
4. Verify, don't infer. Grep for actual spec text, not TODO comments.
5. State your evidence. Every claim cites file:line or command output.
6. kb_add before returning. Checkpoint every 10 tool uses.
7. project="scrap" for all kb_add/kb_search calls.

## Stopping Conditions

Stop and return partial results if:
- Same error 3 times consecutively
- 10+ tool calls with no new findings
- 5+ search phrasings with no results
- 8+ files read without concrete output
