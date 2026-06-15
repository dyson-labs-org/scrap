SCRAP Wallet Requirements
=========================

What a wallet must implement to send and receive payments using SCRAP,
based on spec/PTLC-FALLBACK.md, spec/HTLC-FALLBACK.md, future/CHANNELS.md,
and the existing scrap-lightning/ and scrap-core/ implementations.

Two deployment modes exist with different wallet requirements:

  MODE A — HTLC Fallback (works with current Bitcoin/Lightning today)
  MODE B — Full SCRAP (requires PTLCs; needs BIP-118 activation on Bitcoin)

Both modes are specified. Mode A is the near-term implementation;
Mode B is the target architecture.


==========================================================================
MODE A: HTLC Fallback Wallet (Current Lightning, LN-Penalty Channels)
==========================================================================

This mode uses standard Lightning HTLCs. A largely-standard LDK-based
wallet suffices, with SCRAP-specific additions for task binding.

A.1 Standard Lightning Requirements
-------------------------------------
- BOLT 2: Channel establishment, HTLC add/fulfill/fail
- BOLT 3: Commitment transaction construction (LN-penalty)
- BOLT 11: Invoice creation and payment
- BOLT 7: Gossip / channel announcements (operators only; satellites use
  pre-configured routes)
- LDK is the recommended base (Rust, embeddable, no_std compatible)

A.2 SCRAP-Specific Additions (beyond standard LN)
---------------------------------------------------
All of these are already partially implemented in scrap-lightning/:

A.2.1 Payment-Capability Binding
  - Compute: binding_hash = SHA256(token_jti || payment_hash)
  - Sign binding_hash with commander's key (currently ECDSA in scrap-core;
    should be BIP-340 Schnorr — see Gap A.1 below)
  - Store binding: TaskPaymentBinding{task_jti, payment_hash, amount_msat,
    htlc_timeout_blocks, binding_sig, capability_token_cbor}
  - Verify binding on receive: executor checks that HTLC payment_hash
    corresponds to an authorized capability token before accepting

A.2.2 Execution Proof Verification
  - On receiving proof_of_execution, verify:
      proof_hash = SHA256(task_jti || payment_hash || output_hash || timestamp)
      executor_sig over proof_hash (currently ECDSA; should be Schnorr)
  - Only fulfill HTLC after verifying proof (timeout-default: auto-fulfill
    after dispute window if no dispute raised)

A.2.3 Satellite-Specific Channel Management
  - No real-time Bitcoin network access: transactions queued for ground station
    uplink (SatelliteBroadcaster pattern)
  - Pre-configured fee rates: no mempool access (SatelliteFeeEstimator pattern)
  - Channel state persisted to flash/NVM: must survive reboots
    (SatellitePersister pattern)
  - HTLC timeouts: conservative margins due to intermittent ground contact
    GPS-disciplined: 24h/hop; ground-uplinked: 30-48h/hop

A.2.4 Watchtower Integration (MANDATORY for satellites)
  - Satellites are offline for hours/days — cannot monitor for old state broadcasts
  - Watchtower operated by satellite's own ground operator
  - Watchtower holds per-channel revocation keys (security tradeoff vs. Mode B)
  - Satellite must uplink latest commitment + revocation key at each ground pass

A.2.5 Pre-Configured Routing (no gossip needed on satellite)
  - Routes computed by ground operator and uploaded in onion-encrypted task bundle
  - Satellite needs only: next_hop pubkey, HTLC amount, payment_hash, timeout
  - No routing tables, no channel graph on satellite

GAPS IN CURRENT SCRAP-LIGHTNING IMPLEMENTATION (Mode A):
  Gap A.1: scrap-core/crypto.rs uses ECDSA; spec requires BIP-340 Schnorr
            for token signatures, binding signatures, proof signatures
  Gap A.2: No BOLT-compliant HTLC state machine — LDK wrapping is incomplete;
            SatelliteChannelManager exists but on_payment_received / htlc_handling
            is stubbed
  Gap A.3: No actual ground station uplink queue implementation in
            SatelliteBroadcaster (tx_queue present but no uplink protocol)
  Gap A.4: No watchtower protocol implementation


==========================================================================
MODE B: Full SCRAP Wallet (PTLCs + LN-Symmetry, requires BIP-118)
==========================================================================

This is the target architecture. Requires Bitcoin consensus changes
(BIP 118: SIGHASH_ANYPREVOUT) not yet activated on mainnet.

B.1 Bitcoin Primitive Requirements
------------------------------------
Every one of these must be implemented. None are optional.

B.1.1 BIP 340 — Schnorr Signatures
  - Sign and verify Schnorr signatures over secp256k1
  - Required for: token signatures, ACK signatures, claim transactions,
    channel update/settle signatures, adaptor signature construction
  - Library: secp256k1-zkp (C, Rust bindings available)
  - Current gap: scrap-core uses ECDSA — must be replaced

B.1.2 BIP 341 — Taproot / P2TR
  - Construct P2TR outputs with internal key and script tree
  - PTLC output structure:
      Internal key: MuSig2(P_satellite, P_peer)      [cooperative spend]
      Script leaf 0 (satellite claim):
        <P_satellite> OP_CHECKSIG                     [with adaptor sig]
      Script leaf 1 (timeout refund):
        <CSV_blocks> OP_CSV OP_DROP <P_peer> OP_CHECKSIG
  - Satellite recovery leaf (funded by operator):
      <6_months CLTV> OP_CLTV OP_DROP <P_operator> OP_CHECKSIG
  - Required for: all on-chain PTLC outputs, channel funding outputs,
    LN-Symmetry update/settle transactions

B.1.3 BIP 327 — MuSig2 (2-of-2 Schnorr Aggregation)
  - 2-of-2 key aggregation for channel funding outputs and PTLC internal keys
  - 2-round interactive protocol (nonce exchange, then partial sig exchange)
  - MUST use nonce pre-commitment to prevent Wagner attack
  - Required for: channel funding output cooperative close, PTLC internal key
  - Library: secp256k1-zkp (includes MuSig2 module)
  - Current gap: not implemented anywhere in scrap-lightning

B.1.4 BIP 118 — SIGHASH_ANYPREVOUT
  - LN-Symmetry update transactions use SIGHASH_ANYPREVOUTANYSCRIPT
  - Signature binds to script (not outpoint) — enables rebinding to any
    prior update output, which is how LN-Symmetry "latest state wins" works
  - Requires: ANYPREVOUT activation on Bitcoin (not yet on mainnet)
  - LDK status: experimental flag, not production-ready
  - Current gap: not implemented in scrap-lightning

B.1.5 Adaptor Signatures
  - Full adaptor signature lifecycle:
    a) CREATE: given adaptor point T, produce pre-signature (R, s') where
               s'*G == R + e*P  (not a valid signature until completed)
    b) VERIFY: verify pre-signature is committed to T before accepting task
    c) COMPLETE: given adaptor secret t, produce final sig: s = s' + t
    d) EXTRACT: given s and s', recover t = s - s' (payment receipt)
  - Nonce pre-commitment protocol:
    - Generate k (nonce private key), publish R = k*G to gateway at ground pass
    - Maintain pool of 100+ pre-committed nonces
    - NEVER reuse a nonce — nonce reuse enables full private key recovery
    - Track used nonces in NVM; survive reboots
  - Library: secp256k1-zkp (adaptor signature module)
  - Current gap: not implemented anywhere in scrap-lightning or scrap-core

B.2 Key Hierarchy
------------------
SCRAP uses HKDF (RFC 5869) NOT BIP-32. Key derivation is domain-separated
by context string. Root key never leaves HSM.

  k_root  (256 bits, hardware RNG at manufacture, never exported)
    │
    ├── k_identity  = HKDF(k_root, "identity" || satellite_id)
    │     P_identity = k_identity * G
    │     Uses: ISL authentication (SISL X3DH), onion decryption,
    │           operator communication, capability token subject key
    │
    ├── k_task_N    = HKDF(k_root, "task" || task_id_32bytes)
    │     Uses: On-chain PTLC claim transaction signature for task N
    │           Adaptor signature creation (one key per task)
    │
    ├── k_channel_C = HKDF(k_root, "channel" || channel_id_32bytes)
    │     ├── k_update  = HKDF(k_channel_C, "update")
    │     │     Uses: LN-Symmetry ANYPREVOUT update signatures
    │     ├── k_settle  = HKDF(k_channel_C, "settle")
    │     │     Uses: Settlement transaction signatures
    │     └── k_ptlc_N  = HKDF(k_channel_C, "ptlc" || ptlc_id_8bytes)
    │           Uses: Per-PTLC adaptor signature (channel payment path)
    │
    └── k_nonce_N   = HKDF(k_root, "nonce" || nonce_id)
          Uses: Deterministic nonce generation for pre-committed nonce pool

  Current gap: scrap-core uses raw key bytes; no HKDF hierarchy implemented.

B.3 LN-Symmetry Channel State Machine
---------------------------------------
Replaces LN-penalty. Each state update is 3 messages (~150ms over ISL):

  A → B:  update_propose  {state_N+1, balance_a, balance_b}
  B → A:  update_accept   {partial_sig_B, nonce_B}          [ANYPREVOUT sig]
  A → B:  update_complete {partial_sig_A, nonce_A}

  Wallet must track:
  - Current state number N (monotonic, persisted to NVM)
  - Latest update_N transaction (ANYPREVOUT signed by both parties)
  - Latest settlement_N transaction
  - Channel balances

  Force close: broadcast update_N to Bitcoin network via ground station.
  No toxic waste — counterparty can only broadcast same or later state.
  No watchtower revocation keys needed (watchtower needs only latest state).

  Current gap: not implemented; scrap-lightning wraps LDK LN-penalty.

B.4 PTLC Payment Flow (Satellite as Payer)
-------------------------------------------
Initiated by ground operator who computes route and uploads task bundle.

  1. Ground operator computes full route: Sat_A → Sat_B → ... → Sat_D
  2. Constructs Tx_1 (funding): P2TR outputs for each hop's PTLC
     Internal keys: MuSig2(payer, payee) per hop
  3. Constructs adaptor point T (locked to last operator's delivery sig)
  4. Wraps task bundle in onion layers (ChaCha20-Poly1305 per hop)
  5. Uploads signed task bundle to Sat_A during ground contact

  On ISL contact, Sat_A:
  6. Decrypts outer onion layer → learns: next_hop, task, T, PTLC output index
  7. Creates adaptor signature for its PTLC output (using k_task_N)
  8. Forwards inner encrypted blob to Sat_B
  9. Waits: either learns t from Sat_B's ack, or timeout expires

  Wallet must:
  - Decrypt onion layer using k_identity (ECDH with ephemeral key)
  - Verify adaptor point T matches last operator's nonce/pubkey
  - Create and store adaptor signature (R, s') for own PTLC output
  - Forward inner packet to next hop via SISL
  - On receiving ack signature s_ack: extract t = s_ack (complete claim tx)
  - Broadcast claim tx to Bitcoin network via ground station

B.5 PTLC Payment Flow (Satellite as Payee / Executor)
-------------------------------------------------------
  1. Receive and decrypt innermost onion layer (no next_hop field)
  2. Verify capability token in authorization field
  3. Execute task
  4. Sign acknowledgment: s_ack = k_task + e*x_satellite
     This IS the adaptor secret t for all upstream PTLCs
  5. Return s_ack to previous hop (via SISL)

  Wallet must:
  - Verify that s_ack = t (signature scalar matches adaptor point T)
  - Sign with correct k_task_N (deterministic from task_id)
  - Idempotent: same ack signature for same task_id (retry safe)

B.6 On-Chain PTLC Claiming
----------------------------
When satellite has adaptor secret t (from downstream ack):

  claim_tx:
    input:  PTLC output from Tx_1 (key-path spend via P2TR)
    output: satellite's address
    sig:    complete_adaptor_sig(adaptor_sig_stored, t)

  Wallet must:
  - Store Tx_1 TXID and output index (from task bundle)
  - Store own adaptor signature (R, s') created at task receipt
  - Complete claim tx when t learned, broadcast via ground station
  - Monitor for timeout: if t not learned within CSV blocks, refund path

B.7 Hardware Requirements for Mode B
--------------------------------------
  CPU:     ARM Cortex-M4+ (Schnorr + MuSig2 are heavier than ECDSA)
  RAM:     512 KB minimum (nonce pool, adaptor sig storage, channel state)
  Storage: 64 KB NVM (keys, used nonce set, pending claim txs, channel state)
  RNG:     Hardware TRNG (nonce generation; software RNG is insufficient)
  Clock:   GPS-disciplined preferred; see HTLC timeout margins in Mode A


==========================================================================
OPERATOR-SIDE WALLET (Ground, Always Online)
==========================================================================

The operator wallet is distinct from the satellite wallet. Operators run
standard LDK/LND/CLN nodes with SCRAP extensions. Their wallet must:

  O.1  Construct task bundles (onion-encrypted, source-routed)
       - Compute complete route based on current orbital geometry
       - Wrap capability token + task in per-hop onion layers
       - Construct Tx_1 with PTLC outputs for all hops (Mode B)
         or arrange HTLC chain via standard LN routing (Mode A)

  O.2  Issue capability tokens
       - Sign SAT-CAP tokens with operator's secp256k1 key (Schnorr in B)
       - Upload tokens to commanding satellites during ground contact

  O.3  Manage nonce pool for satellites
       - Collect pre-committed nonces (R_i) from satellites at each ground pass
       - Use nonces to construct adaptor points T for upcoming tasks
       - Provide T to payer satellite in task bundle

  O.4  Watchtower (Mode A only)
       - Monitor Bitcoin chain for old commitment broadcasts
       - Broadcast penalty transactions using revocation keys
       - Receive latest commitment + revocation key at each satellite ground pass

  O.5  Settlement
       - If satellite misses contact window: force-close channel using latest
         commitment transaction uploaded by satellite
       - If satellite claims PTLC (Mode B): extract adaptor secret from
         claim tx, complete upstream Lightning HTLC preimage


==========================================================================
IMPLEMENTATION ROADMAP
==========================================================================

Near-term (Mode A, works today):
  1. Replace ECDSA with BIP-340 Schnorr in scrap-core/crypto.rs
     Library: secp256k1 crate (already imported), enable schnorr feature
  2. Complete LDK integration in scrap-lightning (HTLC state machine)
  3. Implement ground station uplink queue in SatelliteBroadcaster
  4. Implement HKDF key hierarchy (replace raw key bytes)
  5. Add nonce pool management (needed for Mode B adaptor sigs)

Medium-term (Mode B prerequisites, no Bitcoin change needed):
  6. Implement adaptor signature create/verify/complete/extract
     (secp256k1-zkp crate, adaptor_sig module)
  7. Implement MuSig2 2-of-2 (secp256k1-zkp crate, musig module)
  8. Implement P2TR PTLC output construction (bitcoin crate + BIP 341)
  9. Implement onion packet construction and decryption
     (ChaCha20-Poly1305 already available via cryptography crate)

Long-term (Mode B full, requires BIP-118 activation):
  10. Implement LN-Symmetry channel state machine (ANYPREVOUT sigs)
  11. Replace LN-penalty channels with LN-Symmetry in scrap-lightning
  12. On-chain PTLC claim transaction broadcasting


==========================================================================
KEY DISTINCTION FROM STANDARD LIGHTNING WALLETS
==========================================================================

Standard LN wallets (LND, CLN, Phoenix, etc.) cannot be used as-is because:

  1. No adaptor signatures — cannot create payment-proof atomicity
  2. No PTLC support — all payments use hash preimages (HTLCs)
  3. No capability token verification — no concept of authorized task
  4. Always-online assumption — satellites are offline hours/days
  5. No onion task routing — LN routing is payment-only, not task-carrying
  6. No NVM persistence model for embedded/space hardware
  7. No pre-configured fee rates (no mempool access from satellite)
  8. No ANYPREVOUT support (LN-Symmetry) in production LN software
  9. No source-routed task bundles (LN uses gossip-based routing)

The closest existing base is LDK (Lightning Dev Kit) because it is modular,
no_std compatible, and allows replacing individual components — which is
exactly what scrap-lightning does.
