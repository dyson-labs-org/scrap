# Satellite Payment Channels with PTLC Lightning and LN-Symmetry

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
   - 2.1 [System Components](#21-system-components)
   - 2.2 [Operator Channel Topology](#22-operator-channel-topology)
   - 2.3 [Why Satellite Channels Don't Work](#23-why-satellite-channels-dont-work)
   - 2.4 [DEPRECATED: Satellite Channel Topologies](#24-deprecated-satellite-channel-topologies)
   - 2.5 [Operator Channel Payment Flow](#25-operator-channel-payment-flow)
   - 2.6 [Adaptor Signature Binding (PTLC Version)](#26-adaptor-signature-binding-ptlc-version)
   - 2.7 [Comparison: On-Chain vs Operator Channels](#27-comparison-on-chain-vs-operator-channels)
   - 2.8 [Autonomous Satellite-to-Satellite Payments](#28-autonomous-satellite-to-satellite-payments)
3. [LN-Symmetry (Eltoo) Overview](#3-ln-symmetry-eltoo-overview)
   - 3.1 [Why LN-Symmetry for Satellites](#31-why-ln-symmetry-for-satellites)
   - 3.2 [LN-Symmetry Transaction Structure](#32-ln-symmetry-transaction-structure)
   - 3.3 [State Updates via ISL](#33-state-updates-via-isl)
   - 3.4 [MuSig2 Nonce Management](#34-musig2-nonce-management)
4. [PTLC Multi-Hop Payments](#4-ptlc-multi-hop-payments)
   - 4.1 [PTLC vs HTLC in Channels](#41-ptlc-vs-htlc-in-channels)
   - 4.2 [Multi-Hop PTLC Payment](#42-multi-hop-ptlc-payment)
   - 4.3 [PTLC State Machine in LN-Symmetry Channels](#43-ptlc-state-machine-in-ln-symmetry-channels)
   - 4.4 [PTLC State Transitions](#44-ptlc-state-transitions)
   - 4.5 [PTLC Output Structure (On-Chain Settlement)](#45-ptlc-output-structure-on-chain-settlement)
   - 4.6 [PTLC Timeout Handling](#46-ptlc-timeout-handling)
5. [Channel Lifecycle](#5-channel-lifecycle)
   - 5.1 [Channel Opening (Ground Contact)](#51-channel-opening-ground-contact)
   - 5.2 [Normal Operation (In Space)](#52-normal-operation-in-space)
   - 5.3 [Settlement (Ground Contact)](#53-settlement-ground-contact)
   - 5.4 [State Disagreement Resolution](#54-state-disagreement-resolution)
6. [Routing](#6-routing)
   - 6.1 [Pre-Loaded Route Tables](#61-pre-loaded-route-tables)
   - 6.2 [ISL-Aware Routing](#62-isl-aware-routing)
   - 6.3 [Forwarding Fees](#63-forwarding-fees)
   - 6.4 [PTLC Timeout Budget Calculation](#64-ptlc-timeout-budget-calculation)
7. [Watchtower Service](#7-watchtower-service)
   - 7.1 [Ground-Based Watchtowers](#71-ground-based-watchtowers)
8. [Integration with Task Payments](#8-integration-with-task-payments)
   - 8.1 [Relationship to On-Chain PTLC Model](#81-relationship-to-on-chain-ptlc-model)
   - 8.2 [Channel Funding from Task Revenue](#82-channel-funding-from-task-revenue)
   - 8.3 [Task-Payment Routing Coupling](#83-task-payment-routing-coupling)
   - 8.4 [Channel Provisioning Strategies](#84-channel-provisioning-strategies)
   - 8.5 [Liquidity Planning](#85-liquidity-planning)
   - 8.6 [Route Selection Algorithm](#86-route-selection-algorithm)
   - 8.7 [Scaling Analysis](#87-scaling-analysis)
   - 8.8 [Channel Graph Synchronization](#88-channel-graph-synchronization)
9. [Security Considerations](#9-security-considerations)
   - 9.1 [Threat Model](#91-threat-model)
10. [Implementation Considerations](#10-implementation-considerations)
    - 10.1 [Satellite Requirements](#101-satellite-requirements)
    - 10.2 [Protocol Messages](#102-protocol-messages)
    - 10.3 [Key Hierarchy](#103-key-hierarchy-shared-with-on-chain-ptlc)
    - 10.4 [Version Negotiation](#104-version-negotiation)
    - 10.5 [Failure Recovery](#105-failure-recovery)
11. [Future Extensions](#11-future-extensions)
12. [Comparison: On-Chain PTLCs vs Payment Channels](#12-comparison-on-chain-ptlcs-vs-payment-channels)
13. [Upgrade Path from On-Chain PTLCs](#13-upgrade-path-from-on-chain-ptlcs)

---

## 1. Overview

This proposal describes a payment channel architecture for satellite task payments using **operator-level Lightning channels**. Operators maintain channels with each other on the ground, enabling instant multi-hop payments without on-chain transactions for each task.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KEY INSIGHT                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PROBLEM: Satellite-to-satellite channels don't work                        │
│  ─────────────────────────────────────────────────────                      │
│    - ISL connectivity is sparse and intermittent                            │
│    - Multi-hop Lightning requires real-time coordination                    │
│    - Store-and-forward payments take hours (9+ for 3-hop)                   │
│    - HTLC timeouts become impractically long                                │
│                                                                             │
│  SOLUTION: Operator-level channels                                          │
│  ────────────────────────────────                                           │
│    - Operators are ALWAYS ONLINE (ground-based)                             │
│    - Standard Lightning multi-hop works (milliseconds)                      │
│    - Satellites only execute tasks, no payment logic                        │
│    - Payment coordination happens on the ground                             │
│                                                                             │
│  SEPARATION OF CONCERNS:                                                    │
│  ───────────────────────                                                    │
│    SATELLITES: Execute tasks, route data via ISL                            │
│    OPERATORS:  Handle payments via Lightning channels                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DESIGN GOALS                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. NO ON-CHAIN TX PER TASK                                                 │
│     Payments settle via channel updates, not blockchain transactions.       │
│     On-chain only for channel open/close (amortized over many tasks).       │
│                                                                             │
│  2. INSTANT PAYMENT SETUP                                                   │
│     Tasks can start immediately - no waiting for confirmations.             │
│     Payment coordination happens in seconds (operators online).             │
│                                                                             │
│  3. ATOMIC TASK-PAYMENT BINDING                                             │
│     Adaptor signatures bind payment to task completion.                     │
│     Either task completes and everyone gets paid, or refund.                │
│                                                                             │
│  4. STANDARD LIGHTNING COMPATIBILITY                                        │
│     Operator channels are normal Lightning channels.                        │
│     Can connect to broader Lightning Network if desired.                    │
│                                                                             │
│  5. SCALABLE                                                                │
│     O(operators) channels, not O(satellites).                               │
│     10 operators = ~45 channels (full mesh).                                │
│     1000 satellites = still ~45 channels.                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Entity Definitions**: See PTLC-FALLBACK.md "Entity Definitions" section for the complete glossary of terms including Customer, Satellite, Operator, Gateway, Ground Station, and Watchtower. This document uses consistent terminology.

---

## 2. Architecture

### 2.1 System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SYSTEM ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                    PAYMENT LAYER (Ground-Based)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │   │
│  │   │   Op_X      │     │   Op_Y      │     │   Op_Z      │          │   │
│  │   │  (ground)   │◄───►│  (ground)   │◄───►│  (ground)   │          │   │
│  │   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘          │   │
│  │          │    Lightning       │    Lightning      │                 │   │
│  │          │    Channels        │    Channels       │                 │   │
│  │          │                    │                   │                 │   │
│  │   ┌──────┴──────┐      ┌──────┴──────┐    ┌──────┴──────┐          │   │
│  │   │   Gateway   │◄────►│  Gateway    │    │  Gateway    │          │   │
│  │   │  (optional) │      │ (optional)  │    │ (optional)  │          │   │
│  │   └─────────────┘      └─────────────┘    └─────────────┘          │   │
│  │                                                                     │   │
│  │   Operators are ALWAYS ONLINE. Standard Lightning routing.          │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ════════════════════════════════════════════════════════════════════════  │
│                                                                             │
│                    TASK LAYER (Space-Based)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │       ┌───────┐         ┌───────┐         ┌───────┐                │   │
│  │       │ Sat_B │◄──ISL──►│ Sat_C │◄──ISL──►│ Sat_D │                │   │
│  │       │ (Op_X)│         │ (Op_Y)│         │ (Op_Z)│                │   │
│  │       └───────┘         └───────┘         └───────┘                │   │
│  │                                                                     │   │
│  │   Satellites execute tasks and route data via ISL.                  │   │
│  │   NO payment logic on satellites. NO channels between satellites.   │   │
│  │                                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Operator Channel Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OPERATOR CHANNEL TOPOLOGY                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Operators form a Lightning network on the ground.                          │
│  Channels exist between OPERATORS, not satellites.                          │
│                                                                             │
│  FULL MESH (small federations):                                             │
│  ─────────────────────────────────                                          │
│                                                                             │
│                    ┌─────────┐                                              │
│                    │ Gateway │                                              │
│                    └────┬────┘                                              │
│           ┌─────────────┼─────────────┐                                     │
│           │             │             │                                     │
│      ┌────▼────┐   ┌────▼────┐   ┌────▼────┐                               │
│      │  Op_X   │◄─►│  Op_Y   │◄─►│  Op_Z   │                               │
│      └────┬────┘   └────┬────┘   └────┬────┘                               │
│           │             │             │                                     │
│           │             │             │                                     │
│       ┌───┴───┐     ┌───┴───┐     ┌───┴───┐                                │
│       │Sat_B  │     │Sat_C  │     │Sat_D  │                                │
│       │Sat_B' │     │Sat_C' │     │Sat_D' │                                │
│       │...    │     │...    │     │...    │                                │
│       └───────┘     └───────┘     └───────┘                                │
│                                                                             │
│  CHANNEL COUNT:                                                             │
│  ──────────────                                                             │
│    N operators = N×(N-1)/2 channels                                         │
│      5 operators  = 10 channels                                             │
│      10 operators = 45 channels                                             │
│      20 operators = 190 channels                                            │
│                                                                             │
│    Compare to satellite-level:                                              │
│      100 satellites = 4,950 channels (if full mesh)                         │
│      1000 satellites = 499,500 channels                                     │
│                                                                             │
│  HUB-AND-SPOKE (large federations):                                         │
│  ──────────────────────────────────                                         │
│                                                                             │
│                    ┌─────────┐                                              │
│                    │ Gateway │                                              │
│                    │  (Hub)  │                                              │
│                    └────┬────┘                                              │
│           ┌─────────────┼─────────────┐                                     │
│           │             │             │                                     │
│      ┌────▼────┐   ┌────▼────┐   ┌────▼────┐                               │
│      │  Op_X   │   │  Op_Y   │   │  Op_Z   │                               │
│      └─────────┘   └─────────┘   └─────────┘                               │
│                                                                             │
│    N operators = N channels (all to hub)                                    │
│    Max 2 hops for any payment                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Why Satellite Channels Don't Work

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WHY SATELLITE-TO-SATELLITE CHANNELS FAIL                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ATTEMPTED DESIGN (doesn't work):                                           │
│  ────────────────────────────────                                           │
│    Sat_A ◄──channel──► Sat_B ◄──channel──► Sat_C                           │
│                                                                             │
│    For multi-hop payment A → B → C:                                         │
│      1. A sends HTLC to B during A↔B ISL window                             │
│      2. B stores HTLC, waits for B↔C ISL window                             │
│      3. B forwards HTLC to C during B↔C window                              │
│      4. C reveals preimage to B during B↔C window                           │
│      5. B reveals preimage to A during A↔B window                           │
│                                                                             │
│  PROBLEM 1: Timing                                                          │
│  ─────────────────────                                                      │
│    ISL windows: 2-15 minutes, every ~90 minutes (LEO)                       │
│    3-hop payment needs 6 sequential ISL events                              │
│    Worst case: 6 × 90 min = 9 hours                                         │
│                                                                             │
│  PROBLEM 2: HTLC Timeouts                                                   │
│  ────────────────────────                                                   │
│    Each hop needs timeout buffer (e.g., 4 hours)                            │
│    3-hop payment: 12+ hours total timeout                                   │
│    Capital locked for entire duration                                       │
│                                                                             │
│  PROBLEM 3: Failure Recovery                                                │
│  ──────────────────────────                                                 │
│    If B↔C fails after A→B succeeds:                                         │
│      - B holds HTLC, waiting for timeout                                    │
│      - A's funds locked until B's timeout + A's timeout                     │
│      - Could be 24+ hours                                                   │
│                                                                             │
│  SOLUTION: Move payment logic to operators                                  │
│  ────────────────────────────────────────────                               │
│    Operators are always online → standard Lightning works                   │
│    Multi-hop payment: milliseconds, not hours                               │
│    Satellites just execute tasks                                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 DEPRECATED: Satellite Channel Topologies

The following satellite-level channel topologies were considered but rejected
due to ISL connectivity constraints. They are preserved here for reference.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              DEPRECATED: SATELLITE-LEVEL TOPOLOGY OPTIONS                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  OPTION A: MESH TOPOLOGY (REJECTED)                                         │
│  ──────────────────────────────────                                         │
│    Every satellite has channels with neighbors:                             │
│                                                                             │
│         A ←────► B ←────► C                                                 │
│         │       │       │                                                 │
│         ▼       ▼       ▼                                                 │
│         D ←────► E ←────► F                                                 │
│                                                                             │
│    Multi-hop payments route through mesh.                                   │
│    Requires liquidity management across many channels.                      │
│                                                                             │
│  OPTION B: STAR TOPOLOGY (per operator)                                     │
│  ───────────────────────────────────────                                    │
│    Each operator's satellites channel through hub:                          │
│                                                                             │
│         A ──┐                                                               │
│             │                                                               │
│         B ──┼──► HUB_X ◄────► HUB_Y ◄──┬── D                               │
│             │                          │                                    │
│         C ──┘                          └── E                                │
│                                                                             │
│    Simpler liquidity. Cross-operator via hub-to-hub channels.               │
│                                                                             │
│  OPTION C: DYNAMIC CHANNELS                                                 │
│  ──────────────────────────                                                 │
│    Channels opened on-demand based on orbital proximity:                    │
│                                                                             │
│         When A and B have ISL window:                                       │
│           - Open channel (or use existing)                                  │
│           - Transact while in range                                         │
│           - Keep open for next pass or settle                               │
│                                                                             │
│    Adapts to orbital mechanics. More complex state management.              │
│                                                                             │
│  RECOMMENDATION: Start with Option A (mesh) for simplicity,                 │
│  evolve to Option C as protocol matures.                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.5 Operator Channel Payment Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OPERATOR CHANNEL PAYMENT FLOW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SCENARIO: Customer wants task executed by Op_Z's satellite,                │
│            routed through Op_X's and Op_Y's satellites.                     │
│                                                                             │
│  TASK ROUTE (space):     Sat_B (Op_X) → Sat_C (Op_Y) → Sat_D (Op_Z)        │
│  PAYMENT ROUTE (ground): Gateway → Op_X → Op_Y → Op_Z                       │
│                                                                             │
│  PHASE 1: PAYMENT SETUP (ground, milliseconds)                              │
│  ─────────────────────────────────────────────                              │
│                                                                             │
│    Customer ──[Lightning HTLC H]──► Gateway                                 │
│                                                                             │
│    Gateway routes payment via operator channels:                            │
│                                                                             │
│      Gateway ──[HTLC 5100 sat]──► Op_X                                      │
│               Op_X ──[HTLC 5050 sat]──► Op_Y                                │
│                      Op_Y ──[HTLC 5000 sat]──► Op_Z                         │
│                                                                             │
│    All operators are online. Standard Lightning routing.                    │
│    Complete in <1 second.                                                   │
│                                                                             │
│  PHASE 2: TASK EXECUTION (space, minutes to hours)                          │
│  ─────────────────────────────────────────────────                          │
│                                                                             │
│    Op_X uploads task to Sat_B during ground pass                            │
│                                                                             │
│    Sat_B ──[ISL]──► Sat_C ──[ISL]──► Sat_D                                  │
│           (store-and-forward, ISL windows may be hours apart)               │
│                                                                             │
│    Sat_D executes task, delivers output to Op_Z's ground station            │
│                                                                             │
│  PHASE 3: SETTLEMENT (ground, milliseconds)                                 │
│  ──────────────────────────────────────────                                 │
│                                                                             │
│    Op_Z verifies delivery, reveals preimage R                               │
│                                                                             │
│      Op_Z claims from Op_Y: reveals R, gets 5000 sat                        │
│      Op_Y claims from Op_X: reveals R, gets 50 sat (forwarding fee)         │
│      Op_X claims from Gateway: reveals R, gets 50 sat (forwarding fee)      │
│      Gateway claims from Customer: reveals R                                │
│                                                                             │
│    All channel updates. No on-chain transaction.                            │
│    Complete in <1 second once R is revealed.                                │
│                                                                             │
│  TIMELINE:                                                                  │
│  ─────────                                                                  │
│    T+0:      Customer pays, payment routes through operators (<1 sec)       │
│    T+1s:     Op_X uploads task to Sat_B                                     │
│    T+5min:   Sat_B → Sat_C (ISL window)                                     │
│    T+95min:  Sat_C → Sat_D (next ISL window)                                │
│    T+100min: Sat_D executes, downlinks to Op_Z                              │
│    T+100min: Op_Z reveals R, all operators settle (<1 sec)                  │
│                                                                             │
│    TOTAL: ~100 minutes (dominated by task execution, not payment)           │
│    PAYMENT OVERHEAD: <2 seconds total                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.6 Adaptor Signature Binding (PTLC Version)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ATOMIC TASK-PAYMENT BINDING                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  For trustless settlement, payment is bound to task completion              │
│  using adaptor signatures (PTLCs instead of HTLCs).                         │
│                                                                             │
│  SETUP:                                                                     │
│  ──────                                                                     │
│    Op_Z pre-commits nonce R_last for delivery acknowledgment                │
│    Gateway computes adaptor point: T = R_last + e·P_last                    │
│                                                                             │
│    Payment routes with adaptor-locked PTLCs:                                │
│      Gateway ──[PTLC T, 5100 sat]──► Op_X                                   │
│               Op_X ──[PTLC T, 5050 sat]──► Op_Y                             │
│                      Op_Y ──[PTLC T, 5000 sat]──► Op_Z                      │
│                                                                             │
│    All PTLCs locked to SAME adaptor point T.                                │
│    T can only be unlocked by Op_Z signing delivery acknowledgment.          │
│                                                                             │
│  EXECUTION:                                                                 │
│  ──────────                                                                 │
│    Task executes via satellites (same as before)                            │
│    Op_Z receives task output at ground station                              │
│                                                                             │
│  SETTLEMENT:                                                                │
│  ───────────                                                                │
│    Op_Z signs delivery ack: s_last = k_last + e·x_last                      │
│    This IS the adaptor secret: t = s_last                                   │
│                                                                             │
│    Op_Z completes their PTLC with Op_Y:                                     │
│      Reveals t, claims 5000 sat                                             │
│                                                                             │
│    Op_Y extracts t from completed signature, claims from Op_X               │
│    Op_X extracts t, claims from Gateway                                     │
│    Gateway extracts t, claims from Customer                                 │
│                                                                             │
│  ATOMICITY:                                                                 │
│  ──────────                                                                 │
│    Either:                                                                  │
│      Op_Z signs delivery ack → t revealed → everyone gets paid              │
│    Or:                                                                      │
│      Op_Z doesn't sign (task failed) → timeout → everyone refunded          │
│                                                                             │
│    No partial states. All-or-nothing.                                       │
│                                                                             │
│  WHY THIS WORKS:                                                            │
│  ───────────────                                                            │
│    Operators are online → can coordinate adaptor signatures in real-time    │
│    Satellites don't participate in payment → no ISL timing constraints      │
│    Same cryptography as PTLC-FALLBACK.md, just in channels not on-chain     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.7 Comparison: On-Chain vs Operator Channels

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SETTLEMENT METHOD COMPARISON                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ASPECT              │ ON-CHAIN (PROPOSAL_PTLC) │ OPERATOR CHANNELS        │
│  ────────────────────┼──────────────────────────┼──────────────────────────│
│  On-chain tx/task    │ Yes (Tx_1)               │ No                       │
│  Setup time          │ ~2 sec (mempool)         │ <1 sec                   │
│  Settlement time     │ ~10-60 min (confirm)     │ <1 sec                   │
│  Fees per task       │ ~$1+ (on-chain)          │ ~0.01 sat (channel)      │
│  Capital efficiency  │ Per-task UTXO            │ Reusable channel         │
│  Atomicity           │ Yes (same T)             │ Yes (same T)             │
│  Trustless           │ Yes                      │ Yes                      │
│  Task start          │ After mempool            │ Immediately              │
│                                                                             │
│  RECOMMENDED USE:                                                           │
│  ─────────────────                                                          │
│    ON-CHAIN:                                                                │
│      - First transaction with new operator (no channel yet)                 │
│      - Very high value tasks (extra security)                               │
│      - Operators without channel relationship                               │
│                                                                             │
│    OPERATOR CHANNELS:                                                       │
│      - Routine tasks between federated operators                            │
│      - High frequency operations                                            │
│      - Cost-sensitive applications                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.8 Autonomous Satellite-to-Satellite Payments

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              AUTONOMOUS SATELLITE PAYMENTS (DIRECT 1-HOP)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  While multi-hop satellite channels don't work, DIRECT (1-hop) channels    │
│  between satellites work fine for autonomous payments.                      │
│                                                                             │
│  WHY DIRECT WORKS:                                                          │
│  ─────────────────                                                          │
│    Multi-hop: A → B → C requires coordinating 3 parties across ISL windows │
│    Direct:    A → B requires only 2 parties in same ISL window             │
│                                                                             │
│    Two satellites in ISL contact can exchange signatures in ~100-200ms.    │
│    This is a simple channel state update, not multi-hop routing.           │
│                                                                             │
│  USE CASES:                                                                 │
│  ──────────                                                                 │
│    □ Bandwidth purchase: Sat_A pays Sat_B for ISL relay time               │
│    □ Compute offload: Sat_A pays Sat_B for processing task                 │
│    □ Data storage: Sat_A pays Sat_B to cache data until ground contact     │
│    □ Sensor sharing: Sat_A pays Sat_B for access to sensor data            │
│    □ Collision avoidance: Sat_A pays Sat_B to maneuver                     │
│    □ Ephemeris sharing: Sat_A pays Sat_B for precise orbital data          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.1 Channel Setup (Ground Contact)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              SATELLITE CHANNEL SETUP                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Operators coordinate channel opening during ground contact:                │
│                                                                             │
│  1. OPERATOR COORDINATION:                                                  │
│     Op_X and Op_Y agree to open channel between Sat_A and Sat_B             │
│     Negotiate: capacity, initial balance, fee rates                         │
│                                                                             │
│  2. FUNDING TRANSACTION:                                                    │
│     Operators create and sign 2-of-2 MuSig2 funding tx:                     │
│       Input: Op_X UTXO (25,000 sats) + Op_Y UTXO (25,000 sats)              │
│       Output: MuSig2(P_SatA, P_SatB) = 50,000 sats                          │
│                                                                             │
│     Broadcast to Bitcoin network, wait for confirmation.                    │
│                                                                             │
│  3. CHANNEL STATE UPLOAD:                                                   │
│     During ground pass, upload to each satellite:                           │
│       □ Funding outpoint (txid:vout)                                        │
│       □ Counterparty's public key                                           │
│       □ Initial state (A: 25,000 | B: 25,000)                               │
│       □ Nonce pool for future signatures                                    │
│       □ Fee rate parameters                                                 │
│                                                                             │
│  4. CHANNEL READY:                                                          │
│     Both satellites have channel state.                                     │
│     Can transact autonomously during any future ISL window.                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.2 Autonomous Payment Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              AUTONOMOUS PAYMENT DURING ISL WINDOW                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Sat_A and Sat_B have ISL contact. A wants to pay B 1,000 sats.            │
│                                                                             │
│  CURRENT STATE:                                                             │
│    State #5: A has 25,000 | B has 25,000                                    │
│                                                                             │
│  PAYMENT PROTOCOL (LN-Symmetry):                                            │
│  ───────────────────────────────                                            │
│                                                                             │
│    A ────[1. update_propose]────────────────────────► B                    │
│           {state: 6, balance_a: 24000, balance_b: 26000}                    │
│                                                                             │
│    A ◄───[2. update_accept + partial_sig]──────────── B                    │
│           {nonce_b, partial_sig_b}                                          │
│                                                                             │
│    A ────[3. update_complete + partial_sig]─────────► B                    │
│           {nonce_a, partial_sig_a}                                          │
│                                                                             │
│    Both satellites now have State #6 with valid MuSig2 signature.           │
│                                                                             │
│  NEW STATE:                                                                 │
│    State #6: A has 24,000 | B has 26,000                                    │
│                                                                             │
│  TIMING:                                                                    │
│    Round 1: ~50ms (ISL latency + processing)                                │
│    Round 2: ~50ms                                                           │
│    Round 3: ~50ms                                                           │
│    Total: ~150ms                                                            │
│                                                                             │
│  NO GROUND CONTACT NEEDED. Fully autonomous.                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.3 Conditional Payments (Adaptor Signatures)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              CONDITIONAL AUTONOMOUS PAYMENTS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  For "pay only if service provided" semantics, use adaptor signatures:      │
│                                                                             │
│  SCENARIO: A pays B for relay service                                       │
│  ─────────────────────────────────────                                      │
│                                                                             │
│    1. B generates secret z, provides adaptor point T = z·G                  │
│                                                                             │
│    2. A creates adaptor-locked payment:                                     │
│       "B gets 1,000 sats IF B reveals z"                                    │
│                                                                             │
│    3. B provides relay service                                              │
│                                                                             │
│    4. B reveals z to claim payment                                          │
│       A extracts z from completed signature                                 │
│       (z may be useful for A, e.g., decryption key for relayed data)        │
│                                                                             │
│  PROTOCOL:                                                                  │
│  ─────────                                                                  │
│    A ────[1. "I want relay service"]──────────────────► B                  │
│                                                                             │
│    A ◄───[2. adaptor_point T, service_terms]─────────── B                  │
│                                                                             │
│    A ────[3. adaptor_locked_payment(T, 1000 sats)]────► B                  │
│           (A signs state update locked to T)                                │
│                                                                             │
│    A ◄───[4. relay_service_provided]─────────────────── B                  │
│           (B actually relays A's data)                                      │
│                                                                             │
│    A ◄───[5. reveal z, claim payment]────────────────── B                  │
│           (B completes adaptor signature, A extracts z)                     │
│                                                                             │
│  ATOMICITY:                                                                 │
│    B only gets paid if B reveals z.                                         │
│    If B doesn't provide service, B won't reveal z, payment times out.       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.4 Channel Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              SATELLITE CHANNEL MANAGEMENT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  BALANCE DRIFT:                                                             │
│  ──────────────                                                             │
│    Channels may become unbalanced over time:                                │
│      Initial: A has 25,000 | B has 25,000                                   │
│      After many payments: A has 5,000 | B has 45,000                        │
│                                                                             │
│    A can no longer pay B (insufficient balance).                            │
│                                                                             │
│  REBALANCING OPTIONS (during ground contact):                               │
│  ─────────────────────────────────────────────                              │
│    1. Splice-in: Add funds to A's side on-chain                             │
│    2. Splice-out: Remove funds from B's side on-chain                       │
│    3. Close and reopen with new balance                                     │
│    4. Circular rebalance via operator channels                              │
│                                                                             │
│  NONCE POOL MANAGEMENT:                                                     │
│  ──────────────────────                                                     │
│    Each payment consumes one nonce from pre-generated pool.                 │
│    Satellites must track nonce consumption.                                 │
│                                                                             │
│    Pool exhaustion triggers:                                                │
│      □ Refuse new payments until ground contact                             │
│      □ Emergency nonce derivation (less secure)                             │
│                                                                             │
│    Sizing: 1000 nonces = 1000 payments between ground contacts              │
│    Storage: ~32KB per channel (32 bytes × 1000)                             │
│                                                                             │
│  CHANNEL CLOSURE:                                                           │
│  ────────────────                                                           │
│    Cooperative (both online): Single tx, immediate settlement               │
│    Unilateral (one offline): Broadcast latest state, wait for timelock      │
│                                                                             │
│    LN-Symmetry advantage: Old state broadcast is recoverable.               │
│    Counterparty just publishes newer state. No fund loss.                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.5 Satellite Channel Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              SATELLITE CHANNEL TOPOLOGY                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Which satellite pairs should have channels?                                │
│                                                                             │
│  CRITERIA:                                                                  │
│  ─────────                                                                  │
│    □ Frequent ISL contact (same orbital plane, nearby planes)               │
│    □ Expected autonomous transaction volume                                 │
│    □ Operational need (relay paths, sensor sharing)                         │
│                                                                             │
│  SAME-PLANE CHANNELS:                                                       │
│  ────────────────────                                                       │
│    Satellites in same orbital plane have frequent contact.                  │
│    Ring topology: Each sat channels with +1 and -1 neighbor.                │
│                                                                             │
│       Sat_1 ◄──► Sat_2 ◄──► Sat_3 ◄──► ... ◄──► Sat_N ◄──► Sat_1           │
│                                                                             │
│    N satellites = N channels per plane                                      │
│                                                                             │
│  CROSS-PLANE CHANNELS:                                                      │
│  ─────────────────────                                                      │
│    Satellites in adjacent planes have periodic contact.                     │
│    Selective channels based on traffic patterns.                            │
│                                                                             │
│  EXAMPLE (Walker constellation, 5 planes × 10 sats):                        │
│    Same-plane: 5 × 10 = 50 channels                                         │
│    Cross-plane: ~20 selective channels                                      │
│    Total: ~70 satellite channels                                            │
│                                                                             │
│  SCALING:                                                                   │
│  ────────                                                                   │
│    Satellite channels: O(N) with ring + selective cross-plane               │
│    NOT O(N²) - only channel frequently-contacting pairs                     │
│                                                                             │
│  CHANNEL CAPACITY SIZING:                                                   │
│  ────────────────────────                                                   │
│    Estimate autonomous payment volume between ground contacts.              │
│    Typical LEO: 4-8 ground contacts per day                                 │
│    If 100 payments/day at 500 sats average = 50,000 sats/day                │
│    Channel capacity: 100,000 sats provides 2x buffer                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.6 Complete Payment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              COMPLETE PAYMENT ARCHITECTURE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TWO-LAYER CHANNEL SYSTEM:                                                  │
│  ─────────────────────────                                                  │
│                                                                             │
│  LAYER 1: OPERATOR CHANNELS (Ground)                                        │
│  ─────────────────────────────────────                                      │
│    Purpose: Customer task payments, cross-operator settlement               │
│    Topology: Operator mesh (N operators = N×(N-1)/2 channels)               │
│    Routing: Multi-hop Lightning (operators always online)                   │
│    Settlement: Instant (<1 second)                                          │
│                                                                             │
│    Gateway ◄──► Op_X ◄──► Op_Y ◄──► Op_Z                                   │
│                                                                             │
│  LAYER 2: SATELLITE CHANNELS (Space)                                        │
│  ─────────────────────────────────────                                      │
│    Purpose: Autonomous satellite-to-satellite payments                      │
│    Topology: Ring per plane + selective cross-plane                         │
│    Routing: Direct only (1-hop, no multi-hop)                               │
│    Settlement: During ISL window (~150ms)                                   │
│                                                                             │
│    Sat_A ◄──► Sat_B ◄──► Sat_C   (same plane)                              │
│      │                     │                                                │
│      └────────◄──►─────────┘     (cross-plane)                              │
│                                                                             │
│  INTERACTION BETWEEN LAYERS:                                                │
│  ───────────────────────────                                                │
│    □ Operators fund satellite channels during ground contact                │
│    □ Satellite earnings accumulate in channel balance                       │
│    □ Operators extract earnings during channel rebalance/close              │
│    □ Cross-operator satellite channels settled via operator channels        │
│                                                                             │
│  EXAMPLE FLOW:                                                              │
│  ─────────────                                                              │
│    1. Op_X's Sat_A has channel with Op_Y's Sat_B                           │
│    2. Sat_A pays Sat_B 1,000 sats for relay (autonomous, in space)          │
│    3. Sat_B's balance increases, Sat_A's decreases                          │
│    4. During ground contact, Op_Y sees Sat_B earned 1,000 sats              │
│    5. Op_X owes Op_Y 1,000 sats (settled via operator channel)              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 2.8.7 Satellite Channel Requirements

```
┌─────────────────────────────────────────────────────────────────────────────┐
│              SATELLITE REQUIREMENTS FOR AUTONOMOUS PAYMENTS                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STORAGE:                                                                   │
│  ────────                                                                   │
│    Per channel:                                                             │
│      □ Channel parameters: ~200 bytes                                       │
│      □ Current state: ~500 bytes                                            │
│      □ Previous state (for disputes): ~500 bytes                            │
│      □ Nonce pool: ~32 KB (1000 nonces)                                     │
│      Total: ~35 KB per channel                                              │
│                                                                             │
│    10 channels: ~350 KB                                                     │
│    Fits easily in CubeSat flash storage.                                    │
│                                                                             │
│  COMPUTATION:                                                               │
│  ────────────                                                               │
│    Per payment:                                                             │
│      □ MuSig2 partial signature: ~50ms on LEON3-FT                          │
│      □ State verification: ~10ms                                            │
│      □ Nonce management: ~5ms                                               │
│      Total: ~65ms computation                                               │
│                                                                             │
│  COMMUNICATION:                                                             │
│  ──────────────                                                             │
│    Per payment:                                                             │
│      □ 3 protocol messages                                                  │
│      □ ~200 bytes per message                                               │
│      □ ~600 bytes total                                                     │
│                                                                             │
│  POWER:                                                                     │
│  ──────                                                                     │
│    Signature operations: ~100mW for ~100ms = 10mJ per payment               │
│    Negligible compared to ISL radio power.                                  │
│                                                                             │
│  SOFTWARE:                                                                  │
│  ─────────                                                                  │
│    □ secp256k1 library (libsecp256k1 or equivalent)                         │
│    □ MuSig2 implementation                                                  │
│    □ Channel state machine                                                  │
│    □ Nonce pool manager                                                     │
│    □ ISL protocol integration                                               │
│                                                                             │
│  FLIGHT HERITAGE:                                                           │
│  ────────────────                                                           │
│    Similar complexity to existing CubeSat crypto payloads.                  │
│    No exotic hardware required.                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. LN-Symmetry (Eltoo) Overview

### 3.1 Why LN-Symmetry for Satellites

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LN-SYMMETRY ADVANTAGES FOR SATELLITES                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  TRADITIONAL LIGHTNING (LN-PENALTY):                                        │
│  ───────────────────────────────────                                        │
│    - Old states are "toxic waste" (can be used to steal)                    │
│    - Requires watchtowers to monitor for cheating                           │
│    - Penalty transactions must be stored and broadcast quickly              │
│    - Asymmetric closing (designated broadcaster)                            │
│                                                                             │
│  PROBLEM FOR SATELLITES:                                                    │
│    - Satellites are offline from ground for hours/days                      │
│    - Can't watch blockchain for old state broadcasts                        │
│    - Limited storage for penalty transaction history                        │
│    - Ground contact windows don't align with attack timing                  │
│                                                                             │
│  LN-SYMMETRY SOLUTION:                                                      │
│  ─────────────────────                                                      │
│    ✓ No toxic waste: Old states can't steal funds                           │
│    ✓ Latest state always wins (via state numbers)                           │
│    ✓ Either party can publish latest state                                  │
│    ✓ Watchtower only needs latest state, not full history                   │
│    ✓ Symmetric: whoever has ground contact first can settle                 │
│    ✓ Simpler: fewer transactions, less storage                              │
│                                                                             │
│  PERFECT FOR SATELLITES:                                                    │
│    - Satellites store only latest state                                     │
│    - Operators act as watchtowers (minimal data needed)                     │
│    - Either satellite or operator can settle                                │
│    - No race conditions for penalty transactions                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 LN-Symmetry Transaction Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LN-SYMMETRY TRANSACTION STRUCTURE                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PREREQUISITE: SIGHASH_ANYPREVOUT (BIP 118)                                 │
│  ──────────────────────────────────────────                                 │
│    This protocol assumes BIP 118 (SIGHASH_ANYPREVOUT) is activated.         │
│    APO enables signatures that can bind to any UTXO with matching script,   │
│    which is the core mechanism enabling LN-Symmetry's rebinding property.   │
│                                                                             │
│  FUNDING TRANSACTION:                                                       │
│  ────────────────────                                                       │
│    Created during ground contact, opens the channel.                        │
│                                                                             │
│    Inputs:                                                                  │
│      [0] Operator_A funding UTXO                                            │
│      [1] Operator_B funding UTXO (or single funder)                         │
│                                                                             │
│    Outputs:                                                                 │
│      [0] Channel output (Taproot P2TR):                                     │
│          Internal key: MuSig2(Sat_A, Sat_B)  (for cooperative close)        │
│          Script path:  <1> OP_CHECKSEQUENCEVERIFY OP_DROP                   │
│                        <P_update> OP_CHECKSIG                               │
│          Value: channel_capacity                                            │
│                                                                             │
│          P_update is the aggregate key for update signatures.               │
│          CSV of 1 block prevents update in same block as funding.           │
│                                                                             │
│  UPDATE TRANSACTIONS:                                                       │
│  ────────────────────                                                       │
│    Each state N has a corresponding Update_N transaction.                   │
│    Update transactions use SIGHASH_ANYPREVOUTANYSCRIPT signatures.          │
│                                                                             │
│    Update_N:                                                                │
│      nVersion: 2                                                            │
│      nLockTime: 0                                                           │
│                                                                             │
│      Input:                                                                 │
│        prevout: ANY (APO signature binds by script, not outpoint)           │
│        nSequence: 0x0040_0000 | N   (CSV-enabled, encodes state number)     │
│        witness: <apo_signature> <update_script> <control_block>             │
│                                                                             │
│      Output:                                                                │
│        [0] Trigger output (Taproot P2TR):                                   │
│            Internal key: MuSig2(Sat_A, Sat_B)  (for update or settle)       │
│            Script tree:                                                     │
│              Leaf 0 (Update path):                                          │
│                <1> OP_CHECKSEQUENCEVERIFY OP_DROP                           │
│                <P_update> OP_CHECKSIG                                       │
│              Leaf 1 (Settlement path):                                      │
│                <settle_delay> OP_CHECKSEQUENCEVERIFY OP_DROP                │
│                <P_settle> OP_CHECKSIG                                       │
│            Value: channel_capacity (minus fees)                             │
│                                                                             │
│    STATE NUMBER ENCODING:                                                   │
│      nSequence lower 22 bits encode state number N.                         │
│      Higher state numbers can spend lower state outputs via CSV.            │
│      Update_N+1 has nSequence > Update_N, satisfying CSV check.             │
│                                                                             │
│  SETTLEMENT TRANSACTION:                                                    │
│  ────────────────────────                                                   │
│    Finalizes the channel after settle_delay blocks.                         │
│                                                                             │
│    Settlement_N:                                                            │
│      nVersion: 2                                                            │
│      nLockTime: 0                                                           │
│                                                                             │
│      Input:                                                                 │
│        prevout: Update_N trigger output                                     │
│        nSequence: settle_delay (e.g., 144 blocks = ~1 day)                  │
│        witness: <settle_signature> <settle_script> <control_block>          │
│                                                                             │
│      Outputs:                                                               │
│        [0] Sat_A balance: A_sats to P2TR(Sat_A)                             │
│        [1] Sat_B balance: B_sats to P2TR(Sat_B)                             │
│        [2+] PTLC outputs (if any pending - see Section 4.3)                 │
│                                                                             │
│  REBINDING PROPERTY (APO):                                                  │
│  ─────────────────────────                                                  │
│    SIGHASH_ANYPREVOUT signatures do NOT commit to the input outpoint.       │
│    This enables rebinding:                                                  │
│                                                                             │
│    Scenario: Update_3 broadcast, but Update_7 is latest state               │
│                                                                             │
│      1. Malicious party broadcasts Update_3                                 │
│      2. Update_3 confirms, creates trigger output                           │
│      3. Honest party has Update_7 with APO signature                        │
│      4. Update_7 can spend Update_3's trigger output because:               │
│         - APO signature matches the script (same P_update key)              │
│         - nSequence(7) > nSequence(3), satisfying CSV                       │
│      5. Update_7 replaces Update_3, latest state wins                       │
│                                                                             │
│    Result: No penalty mechanism needed. Just publish latest state.          │
│            Watchtowers only need latest Update_N, not full history.         │
│                                                                             │
│  COOPERATIVE CLOSE (KEY PATH):                                              │
│  ─────────────────────────────                                              │
│    Preferred settlement method when both parties cooperate:                 │
│      - Skip update/settlement transactions entirely                         │
│      - Spend funding output directly via MuSig2 key path                    │
│      - Single transaction, immediate finality                               │
│      - Most private (no script reveal)                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 State Updates via ISL

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL UPDATE PROTOCOL (via ISL)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Sat_A wants to pay Sat_B 1000 sats:                                        │
│                                                                             │
│  Current state N: A=50,000  B=50,000                                        │
│  New state N+1:   A=49,000  B=51,000                                        │
│                                                                             │
│  PROTOCOL:                                                                  │
│  ─────────                                                                  │
│                                                                             │
│    Sat_A                              Sat_B                                 │
│      │                                  │                                   │
│      │  1. Propose update               │                                   │
│      │  {state: N+1, A: 49000, B: 51000}│                                   │
│      │─────────────────────────────────►│                                   │
│      │                                  │                                   │
│      │                   2. Verify proposed state                           │
│      │                      Check: state_num = N+1                          │
│      │                      Check: A+B = capacity                           │
│      │                                  │                                   │
│      │  3. Partial signature            │                                   │
│      │  {sig_B_update, sig_B_settle}    │                                   │
│      │◄─────────────────────────────────│                                   │
│      │                                  │                                   │
│      │  4. Verify B's signatures        │                                   │
│      │     Complete Update_N+1          │                                   │
│      │     Complete Settlement_N+1      │                                   │
│      │                                  │                                   │
│      │  5. Partial signature            │                                   │
│      │  {sig_A_update, sig_A_settle}    │                                   │
│      │─────────────────────────────────►│                                   │
│      │                                  │                                   │
│      │                   6. Verify A's signatures                           │
│      │                      Complete Update_N+1                             │
│      │                      Complete Settlement_N+1                         │
│      │                      Store new state                                 │
│      │                                  │                                   │
│      │  7. ACK                          │                                   │
│      │◄─────────────────────────────────│                                   │
│      │                                  │                                   │
│      │  8. Store new state              │                                   │
│      │     Discard state N              │                                   │
│      │                                  │                                   │
│                                                                             │
│  RESULT: Both satellites have Update_N+1 and Settlement_N+1.                │
│          Either can unilaterally close with latest state.                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.4 MuSig2 Nonce Management

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MUSIG2 NONCE MANAGEMENT FOR SATELLITES                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  MuSig2 requires fresh nonces for each signature. Satellites face unique    │
│  constraints that require careful nonce management.                         │
│                                                                             │
│  NONCE LIFECYCLE:                                                           │
│  ────────────────                                                           │
│    1. Generate nonce pair: (k, R) where R = k·G                             │
│    2. Exchange public nonces R_A, R_B with peer                             │
│    3. Compute aggregate nonce: R = R_A + R_B                                │
│    4. Sign with private nonce k                                             │
│    5. Nonce is consumed - NEVER REUSE                                       │
│                                                                             │
│  NONCE REUSE IS CATASTROPHIC:                                               │
│  ───────────────────────────                                                │
│    If the same nonce k is used for two different messages:                  │
│      s_1 = k + e_1·x                                                        │
│      s_2 = k + e_2·x                                                        │
│      => x = (s_1 - s_2) / (e_1 - e_2)                                       │
│    Private key is immediately recoverable. All funds lost.                  │
│                                                                             │
│  PRE-GENERATION STRATEGY:                                                   │
│  ────────────────────────                                                   │
│    During ground contact, satellites pre-generate nonce pools:              │
│                                                                             │
│    Per channel:                                                             │
│      - Generate N nonce pairs (k_i, R_i)                                    │
│      - Store in monotonic index: nonce_pool[channel_id][i]                  │
│      - Exchange public nonces with peer via ground relay                    │
│      - Track next_nonce_index per channel                                   │
│                                                                             │
│    Pool sizing:                                                             │
│      N = expected_updates_per_orbit × orbits_between_contacts × safety      │
│      Example: 100 updates/orbit × 15 orbits × 2 = 3000 nonces               │
│      Storage: 3000 × 64 bytes = ~192 KB per channel                         │
│                                                                             │
│  NONCE CONSUMPTION PROTOCOL:                                                │
│  ───────────────────────────                                                │
│    State update N uses nonce at index N:                                    │
│      nonce_index = state_number mod pool_size                               │
│                                                                             │
│    CRITICAL: Before signing state N:                                        │
│      1. Verify nonce[N] has not been used                                   │
│      2. Mark nonce[N] as consumed BEFORE signing                            │
│      3. Persist consumption record to non-volatile storage                  │
│      4. Only then proceed with signature                                    │
│                                                                             │
│    This order prevents nonce reuse even if satellite crashes mid-update.    │
│                                                                             │
│  STATE ROLLBACK PROTECTION:                                                 │
│  ──────────────────────────                                                 │
│    Satellite state rollback (e.g., from backup) could cause nonce reuse.    │
│                                                                             │
│    Mitigations:                                                             │
│      1. Never restore from backup without operator intervention             │
│      2. On any state uncertainty, force channel close via ground            │
│      3. Store nonce consumption bitmap separately from channel state        │
│      4. Use monotonic hardware counter if available                         │
│                                                                             │
│  NONCE EXHAUSTION HANDLING:                                                 │
│  ──────────────────────────                                                 │
│    If nonce pool approaches exhaustion before ground contact:               │
│                                                                             │
│    Warning threshold: 10% remaining                                         │
│      - Satellite stops initiating new payments                              │
│      - Only responds to incoming PTLC fulfills/fails                        │
│      - Signals "low nonce" to peers                                         │
│                                                                             │
│    Critical threshold: 1% remaining                                         │
│      - Satellite refuses all new channel updates                            │
│      - Attempts emergency ground contact if possible                        │
│      - Existing PTLCs can still be resolved (reserved nonces)               │
│                                                                             │
│    Reserve pool: Set aside nonces for PTLC resolution                       │
│      reserve_size = max_pending_ptlcs × 2 (fulfill + potential retry)       │
│                                                                             │
│  NONCE EXCHANGE DURING GROUND CONTACT:                                      │
│  ──────────────────────────────────────                                     │
│    1. Operator_A queries Sat_A for remaining nonce count                    │
│    2. Sat_A generates new nonce batch, sends public nonces to Operator_A    │
│    3. Operator_A relays to Operator_B (or uses direct operator channel)     │
│    4. Operator_B uploads peer nonces to Sat_B                               │
│    5. Both satellites now have fresh nonce pools                            │
│                                                                             │
│  DETERMINISTIC NONCE DERIVATION (OPTIONAL):                                 │
│  ──────────────────────────────────────────                                 │
│    Alternative to pre-generation using RFC 6979-style derivation:           │
│                                                                             │
│    k = HKDF(k_root, "nonce" || channel_id || state_number || aux_rand)      │
│                                                                             │
│    Advantages:                                                              │
│      - No nonce storage needed                                              │
│      - Deterministic recovery                                               │
│                                                                             │
│    Disadvantages:                                                           │
│      - Requires state_number to be strictly monotonic                       │
│      - State rollback still catastrophic                                    │
│      - aux_rand must be truly random per derivation                         │
│                                                                             │
│    Recommendation: Use pre-generation for implementation simplicity         │
│    and clearer security properties.                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. PTLC Multi-Hop Payments

### 4.1 PTLC vs HTLC in Channels

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PTLC ADVANTAGES IN CHANNELS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  HTLC (Hash Time-Locked Contract):                                          │
│    - Locked to hash H = SHA256(preimage)                                    │
│    - Revealed preimage unlocks all hops                                     │
│    - Same hash visible across all hops (correlation attack)                 │
│                                                                             │
│  PTLC (Point Time-Locked Contract):                                         │
│    - Locked to point T (adaptor signature)                                  │
│    - Revealed scalar t unlocks                                              │
│    - Different adaptor points per hop (no correlation)                      │
│    - Scriptless scripts: smaller, more private                              │
│                                                                             │
│  FOR SATELLITE CHANNELS:                                                    │
│    PTLCs provide:                                                           │
│      ✓ Better privacy (no hash correlation across hops)                     │
│      ✓ Smaller transactions (scriptless scripts)                            │
│      ✓ Consistent with on-chain PTLC model                                  │
│      ✓ Atomic multi-hop payments via adaptor signatures                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Multi-Hop PTLC Payment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTI-HOP PTLC PAYMENT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Route: A ──► B ──► C (A pays C via B)                                      │
│                                                                             │
│  ADAPTOR POINT CONSTRUCTION:                                                │
│  ───────────────────────────                                                │
│    C generates: secret z, point Z = z·G                                     │
│    B's adaptor point: T_B = Z + tweak_B·G                                   │
│    A's adaptor point: T_A = T_B + tweak_A·G                                 │
│                                                                             │
│    Relationship: t_A = t_B + tweak_A                                        │
│                  t_B = z + tweak_B                                          │
│                                                                             │
│  PAYMENT FLOW:                                                              │
│  ─────────────                                                              │
│                                                                             │
│    1. A creates PTLC to B locked to T_A                                     │
│       Channel A↔B: A's balance reduced, B has conditional claim             │
│                                                                             │
│    2. B creates PTLC to C locked to T_B                                     │
│       Channel B↔C: B's balance reduced, C has conditional claim             │
│                                                                             │
│    3. C reveals z to claim PTLC from B                                      │
│       B learns t_B = z + tweak_B                                            │
│       Channel B↔C settled: C +amount                                        │
│                                                                             │
│    4. B uses t_B to compute t_A = t_B + tweak_A                             │
│       B claims PTLC from A                                                  │
│       Channel A↔B settled: B +amount                                        │
│                                                                             │
│  RESULT:                                                                    │
│    A: -amount                                                               │
│    B: net zero (forwarding fee if any)                                      │
│    C: +amount                                                               │
│                                                                             │
│  ATOMICITY:                                                                 │
│    - Either all hops complete or none                                       │
│    - If C doesn't reveal z, PTLCs timeout and refund                        │
│    - No partial completion risk                                             │
│                                                                             │
│  TWO PAYMENT TYPES ON SAME CHANNEL INFRASTRUCTURE:                          │
│  ─────────────────────────────────────────────────                          │
│    Payment channels support TWO distinct payment types, differentiated      │
│    by WHO initiates and WHETHER delivery proof is needed:                   │
│                                                                             │
│    TYPE 1: TASK PAYMENTS (Gateway-Initiated)                                │
│    ─────────────────────────────────────────                                │
│      Initiator: Gateway (on behalf of customer)                             │
│      Adaptor point: T = R_last + e·P_last (signature-as-secret)             │
│      Adaptor secret: t = s_last (last operator's delivery acknowledgment)   │
│      Delivery proof: YES (t proves delivery was acknowledged)               │
│      Atomicity: All-or-nothing (all hops use same T)                        │
│                                                                             │
│      Flow:                                                                  │
│        1. Gateway computes T from last operator's commitment                │
│        2. Gateway initiates channel PTLC chain through satellites           │
│        3. Task executes, last operator signs delivery (s_last)              │
│        4. t = s_last released, all PTLCs claim with same t                  │
│        5. Gateway claims customer HTLC with t as preimage                   │
│                                                                             │
│    TYPE 2: AUTONOMOUS PAYMENTS (Satellite-Initiated)                        │
│    ──────────────────────────────────────────────────                       │
│      Initiator: Satellite (requesting service from another satellite)       │
│      Adaptor point: T = z·G (receiver generates secret z)                   │
│      Adaptor secret: t = z (receiver's secret)                              │
│      Delivery proof: NO (just payment for service)                          │
│      Atomicity: Per-payment (receiver controls revelation)                  │
│                                                                             │
│      Flow:                                                                  │
│        1. Sat A requests service from Sat B                                 │
│        2. Sat B generates z, provides T = z·G                               │
│        3. Sat A creates channel PTLC locked to T                            │
│        4. Sat B provides service                                            │
│        5. Sat B reveals z, claims PTLC                                      │
│        6. Channel state updated (instant settlement)                        │
│                                                                             │
│  ADAPTOR POINT COMPARISON:                                                  │
│  ─────────────────────────                                                  │
│    ┌──────────────────┬─────────────────────────┬─────────────────────┐    │
│    │ Aspect           │ Task Payments           │ Autonomous          │    │
│    ├──────────────────┼─────────────────────────┼─────────────────────┤    │
│    │ Adaptor point    │ T = R_last + e·P_last   │ T = z·G             │    │
│    │ Secret source    │ Last operator ack       │ Receiver generates  │    │
│    │ Delivery proof   │ Yes (t = signature)     │ No                  │    │
│    │ Initiator        │ Gateway                 │ Satellite           │    │
│    │ Atomicity        │ All hops same T         │ Per-hop T           │    │
│    │ Multi-hop        │ Same t unlocks all      │ Standard forwarding │    │
│    └──────────────────┴─────────────────────────┴─────────────────────┘    │
│                                                                             │
│  COEXISTENCE:                                                               │
│  ────────────                                                               │
│    Both payment types use the SAME channel infrastructure:                  │
│      □ Same LN-Symmetry state management                                    │
│      □ Same PTLC state machine                                              │
│      □ Same adaptor signature convention (receiver creates)                 │
│      □ Same HSM operations                                                  │
│                                                                             │
│    Channels can carry task payments AND autonomous payments                 │
│    interleaved, without conflict.                                           │
│                                                                             │
│  UNIFIED ADAPTOR CONVENTION (same as PTLC-FALLBACK.md):                     │
│  ──────────────────────────────────────────────────────                     │
│    □ Receiver creates adaptor signature using own key                       │
│    □ Script: <P_receiver> OP_CHECKSIG                                       │
│    □ Complete adaptor sig: s = s' + t                                       │
│    □ Extract t from signature: t = s - s'                                   │
│    □ Same HSM operations for both payment types                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 PTLC State Machine in LN-Symmetry Channels

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PTLC STATE IN LN-SYMMETRY                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Channel state includes pending PTLCs:                                      │
│                                                                             │
│  State_N:                                                                   │
│    A_balance: 40,000 sats                                                   │
│    B_balance: 50,000 sats                                                   │
│    pending_ptlcs: [                                                         │
│      {                                                                      │
│        ptlc_id: 1,                                                          │
│        direction: A→B,                                                      │
│        amount: 10,000,                                                      │
│        adaptor_point: T,                                                    │
│        timeout_height: 800144   (absolute block height)                     │
│      }                                                                      │
│    ]                                                                        │
│                                                                             │
│  CHANNEL CAPACITY CONSTRAINT:                                               │
│  ────────────────────────────                                               │
│    A_balance + B_balance + Σ(pending_ptlc.amount) = channel_capacity        │
│                                                                             │
│    When A offers PTLC to B:                                                 │
│      A_balance decreases by amount                                          │
│      PTLC added to pending (amount held in escrow)                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 PTLC State Transitions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PTLC STATE TRANSITIONS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STATE DIAGRAM:                                                             │
│  ──────────────                                                             │
│                                                                             │
│              ┌──────────────┐                                               │
│              │   OFFERED    │                                               │
│              │  (in state)  │                                               │
│              └──────┬───────┘                                               │
│                     │                                                       │
│         ┌──────────┬┴┬──────────┐                                           │
│         ▼          │ │          ▼                                           │
│    ┌─────────┐     │ │     ┌─────────┐                                      │
│    │ FULFILL │     │ │     │  FAIL   │                                      │
│    │(reveal t)│    │ │     │(timeout)│                                      │
│    └────┬────┘     │ │     └────┬────┘                                      │
│         │          │ │          │                                           │
│         ▼          │ │          ▼                                           │
│    ┌─────────┐     │ │     ┌─────────┐                                      │
│    │B_balance│     │ │     │A_balance│                                      │
│    │ += amt  │     │ │     │ += amt  │                                      │
│    └─────────┘     │ │     └─────────┘                                      │
│                    │ │                                                      │
│                    │ │                                                      │
│           ┌───────┘ └───────┐                                               │
│           ▼                 ▼                                               │
│      ┌─────────┐       ┌─────────┐                                          │
│      │ON-CHAIN │       │ON-CHAIN │                                          │
│      │ FULFILL │       │ TIMEOUT │                                          │
│      └─────────┘       └─────────┘                                          │
│                                                                             │
│  TRANSITION: ADD PTLC (off-chain)                                           │
│  ────────────────────────────────                                           │
│    Preconditions:                                                           │
│      - A_balance >= amount + reserve                                        │
│      - pending_ptlcs.count < MAX_PTLCS (e.g., 30)                           │
│      - timeout_height > current_height + min_timeout                        │
│                                                                             │
│    State change:                                                            │
│      A_balance -= amount                                                    │
│      pending_ptlcs.push({ptlc_id, A→B, amount, T, timeout_height})          │
│                                                                             │
│  TRANSITION: FULFILL PTLC (off-chain)                                       │
│  ─────────────────────────────────────                                      │
│    Preconditions:                                                           │
│      - B possesses adaptor secret t such that t·G = T                       │
│      - PTLC exists in pending_ptlcs                                         │
│                                                                             │
│    State change:                                                            │
│      B_balance += amount                                                    │
│      pending_ptlcs.remove(ptlc_id)                                          │
│      B sends t to A (for upstream claim in multi-hop)                       │
│                                                                             │
│  TRANSITION: FAIL PTLC (off-chain, cooperative timeout)                     │
│  ──────────────────────────────────────────────────────                     │
│    Preconditions:                                                           │
│      - Both parties agree to cancel                                         │
│      - OR timeout_height reached and B didn't fulfill                       │
│                                                                             │
│    State change:                                                            │
│      A_balance += amount                                                    │
│      pending_ptlcs.remove(ptlc_id)                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.5 PTLC Output Structure (On-Chain Settlement)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PTLC OUTPUT IN SETTLEMENT TX                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  When channel closes with pending PTLCs, Settlement_N includes PTLC         │
│  outputs for on-chain resolution.                                           │
│                                                                             │
│  SETTLEMENT_N WITH PENDING PTLC:                                            │
│  ────────────────────────────────                                           │
│    Outputs:                                                                 │
│      [0] A_balance: 40,000 sats → P2TR(Sat_A)                               │
│      [1] B_balance: 50,000 sats → P2TR(Sat_B)                               │
│      [2] PTLC output: 10,000 sats → P2TR(PTLC script)                       │
│                                                                             │
│  PTLC OUTPUT SCRIPT (Taproot):                                              │
│  ─────────────────────────────                                              │
│    Internal key: MuSig2(Sat_A, Sat_B)  (cooperative resolution)             │
│                                                                             │
│    Script tree:                                                             │
│      Leaf 0 (Claim path - B claims):                                        │
│        <P_B> OP_CHECKSIG                                                    │
│                                                                             │
│      Leaf 1 (Timeout path - A reclaims after timeout):                      │
│        <timeout_height> OP_CHECKLOCKTIMEVERIFY OP_DROP                      │
│        <P_A> OP_CHECKSIG                                                    │
│                                                                             │
│  ADAPTOR SIGNATURE MECHANISM:                                               │
│  ────────────────────────────                                               │
│    The claim path uses B's key directly. The adaptor mechanism works        │
│    entirely off-chain - it does NOT appear in the on-chain script.          │
│                                                                             │
│    Setup (when PTLC created, A offers PTLC to B):                           │
│      1. B provides adaptor point T = t·G to A                               │
│         (In multi-hop, T is derived from downstream; see Section 4.2)       │
│      2. Both parties agree on claim_tx template:                            │
│         - Input: PTLC output from Settlement_N                              │
│         - Output: B's address                                               │
│      3. B creates adaptor signature for claim_tx using B's key:             │
│         - Choose nonce k, compute R = k·G                                   │
│         - Compute adaptor nonce: R' = R + T                                 │
│         - Compute challenge e = H(R' || P_B || claim_tx)                    │
│         - Compute adaptor scalar s' = k + e·x_B                             │
│         - Adaptor signature: (R, s')                                        │
│      4. B sends adaptor signature (R, s') to A                              │
│      5. A verifies adaptor is valid:                                        │
│         - Compute R' = R + T                                                │
│         - Compute e = H(R' || P_B || claim_tx)                              │
│         - Verify: s'·G = R + e·P_B                                          │
│         - If valid: completed sig (R', s'+t) will verify for P_B            │
│      6. A stores adaptor signature for later t extraction                   │
│                                                                             │
│    Claim (B knows adaptor secret t):                                        │
│      1. B computes complete signature: s = s' + t                           │
│      2. B computes complete nonce point: R' = R + T                         │
│      3. Final signature (R', s) is valid Schnorr sig for P_B                │
│         Verify: s·G = R' + e·P_B                                            │
│                     = R + T + e·P_B                                         │
│                     = k·G + t·G + e·x_B·G                                   │
│                     = (k + t + e·x_B)·G = (s' + t)·G ✓                      │
│      4. B broadcasts claim_tx with signature (R', s)                        │
│      5. A observes claim_tx on-chain, extracts t:                           │
│         - A has s' (from step 4), s (from blockchain), R, R' (computed)     │
│         - t = s - s'                                                        │
│         - Verify: t·G = T ✓                                                 │
│                                                                             │
│    Timeout (B doesn't claim):                                               │
│      1. A waits for timeout_height                                          │
│      2. A signs timeout_tx with own key P_A via script leaf 1               │
│      3. A broadcasts, reclaims PTLC amount                                  │
│                                                                             │
│    KEY INSIGHT: The on-chain script is simple (just CHECKSIG).              │
│    The adaptor mechanism is purely cryptographic, not scripted.             │
│    B signs with their own key; the adaptor proves t-knowledge to A.         │
│    The signature reveals t, enabling multi-hop atomicity.                   │
│                                                                             │
│    WHY B CREATES THE ADAPTOR:                                               │
│      - B controls the claim path (P_B in script)                            │
│      - B signs to claim their own funds                                     │
│      - Adaptor signature is B's commitment to reveal t when claiming        │
│      - A can verify the adaptor without knowing t                           │
│      - A extracts t by comparing adaptor (s') to completed sig (s)          │
│                                                                             │
│  ADAPTOR SIGNATURE DATA STORED:                                             │
│  ──────────────────────────────                                             │
│    For each PTLC in pending state, channel state must include:              │
│      - ptlc_id: unique identifier (8 bytes)                                 │
│      - direction: A→B or B→A (1 byte)                                       │
│      - amount: satoshis (8 bytes)                                           │
│      - adaptor_point: T (32 bytes)                                          │
│      - adaptor_nonce: R from receiver's adaptor sig (32 bytes)              │
│      - adaptor_scalar: s' from receiver's adaptor sig (32 bytes)            │
│      - claim_tx: serialized claim transaction template (~100 bytes)         │
│      - timeout_height: absolute block height (4 bytes)                      │
│                                                                             │
│    Both satellites store this data for on-chain resolution.                 │
│    The offerer (A) needs the adaptor to extract t after claim.              │
│                                                                             │
│  MAX IN-FLIGHT PTLCS:                                                       │
│  ────────────────────                                                       │
│    Limit: 30 pending PTLCs per channel                                      │
│                                                                             │
│    Rationale:                                                               │
│      - Each PTLC adds ~50 vbytes to Settlement tx                           │
│      - 30 PTLCs = ~1500 vbytes additional                                   │
│      - Keeps Settlement tx under standard limits                            │
│      - Limits witness size for claim transactions                           │
│                                                                             │
│    If limit reached:                                                        │
│      - New PTLC offers rejected                                             │
│      - Must resolve existing PTLCs first                                    │
│      - Prevents griefing via PTLC spam                                      │
│                                                                             │
│  RESERVE REQUIREMENT:                                                       │
│  ────────────────────                                                       │
│    Each party must maintain minimum reserve:                                │
│      reserve = base_reserve + (num_pending_ptlcs × per_ptlc_reserve)        │
│                                                                             │
│    Example:                                                                 │
│      base_reserve = 1,000 sats                                              │
│      per_ptlc_reserve = 330 sats (dust limit)                               │
│      5 pending PTLCs: reserve = 1,000 + 5×330 = 2,650 sats                  │
│                                                                             │
│    Ensures funds available for:                                             │
│      - On-chain fees if unilateral close                                    │
│      - PTLC claim/timeout transactions                                      │
│                                                                             │
│  DUST LIMIT AND MINIMUM PTLC:                                               │
│  ────────────────────────────                                               │
│    PTLCs must be economically viable if settled on-chain.                   │
│                                                                             │
│    Dust threshold (Bitcoin consensus):                                      │
│      - P2TR output: 330 sats (at 3 sat/vbyte min relay fee)                 │
│      - Output below dust is non-standard, won't propagate                   │
│                                                                             │
│    Minimum PTLC amount:                                                     │
│      min_ptlc = dust_threshold + claim_tx_fee                               │
│                                                                             │
│      Where:                                                                 │
│        dust_threshold = 330 sats                                            │
│        claim_tx_fee = claim_tx_vbytes × fee_rate                            │
│        claim_tx_vbytes ≈ 110 vbytes (P2TR input + output)                   │
│                                                                             │
│      At 10 sat/vbyte: min_ptlc = 330 + 1100 = 1,430 sats                    │
│      Recommended minimum: 1,500 sats (provides margin)                      │
│                                                                             │
│    Economic viability check:                                                │
│      Before accepting PTLC:                                                 │
│        if amount < min_ptlc:                                                │
│          reject with BELOW_MINIMUM error (0x0005)                           │
│                                                                             │
│    Aggregation strategy for small payments:                                 │
│      - Buffer small payments off-chain                                      │
│      - Settle aggregated amount periodically                                │
│      - Reduces on-chain footprint for dust-level payments                   │
│                                                                             │
│    Fee rate assumptions:                                                    │
│      - min_ptlc calculation uses conservative fee estimate                  │
│      - During high-fee periods, effective minimum may be higher             │
│      - Operators update min_ptlc policy during ground contact               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.6 PTLC Timeout Handling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PTLC TIMEOUT SCENARIOS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SCENARIO 1: Timeout while channel open (off-chain)                         │
│  ──────────────────────────────────────────────────                         │
│    Current height reaches timeout_height, B hasn't fulfilled.               │
│                                                                             │
│    Protocol:                                                                │
│      1. A proposes update removing PTLC, crediting A_balance                │
│      2. B should accept (PTLC is expired anyway)                            │
│      3. State N+1 created without PTLC                                      │
│                                                                             │
│    If B doesn't respond:                                                    │
│      - A can force-close with current state                                 │
│      - PTLC goes on-chain, A claims via timeout after CLTV                  │
│                                                                             │
│  SCENARIO 2: Timeout during ISL gap                                         │
│  ─────────────────────────────────                                          │
│    PTLC timeout expires while satellites have no ISL contact.               │
│                                                                             │
│    Impact:                                                                  │
│      - Cannot resolve off-chain (no communication)                          │
│      - If channel closes, on-chain timeout resolution                       │
│      - Multi-hop: upstream PTLC must have earlier timeout                   │
│                                                                             │
│    Mitigation:                                                              │
│      - Set timeout with ISL gap buffer (see Section 6.2)                    │
│      - timeout = execution_time + isl_gap + safety_margin                   │
│                                                                             │
│  SCENARIO 3: Force close with pending PTLC                                  │
│  ─────────────────────────────────────────                                  │
│    Either party broadcasts Update_N, Settlement_N with pending PTLC.        │
│                                                                             │
│    On-chain state:                                                          │
│      1. Update_N confirms                                                   │
│      2. Wait settle_delay                                                   │
│      3. Settlement_N confirms with PTLC output                              │
│                                                                             │
│    PTLC resolution (B has secret):                                          │
│      4a. B broadcasts claim tx with completed adaptor sig                   │
│      4a. B receives amount, t revealed on-chain                             │
│                                                                             │
│    PTLC resolution (timeout):                                               │
│      4b. Wait for timeout_height                                            │
│      4b. A broadcasts timeout tx                                            │
│      4b. A reclaims amount                                                  │
│                                                                             │
│  MULTI-HOP TIMEOUT COORDINATION:                                            │
│  ────────────────────────────────                                           │
│    For route A → B → C:                                                     │
│      timeout_AB > timeout_BC + claim_buffer                                 │
│                                                                             │
│    claim_buffer accounts for:                                               │
│      - B learning t from C (off-chain or on-chain)                          │
│      - B's claim transaction confirmation                                   │
│      - Safety margin for reorgs                                             │
│                                                                             │
│    Recommended: claim_buffer = 36 blocks (~6 hours)                         │
│                                                                             │
│    Example:                                                                 │
│      timeout_BC = height + 144 blocks (~1 day)                              │
│      timeout_AB = height + 180 blocks (~1.25 days)                          │
│      B has 36-block window to claim from A after learning t from C          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Channel Lifecycle

### 5.1 Channel Opening (Ground Contact)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL OPENING                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PARTICIPANTS:                                                              │
│    - Operator_A (funds and manages Sat_A)                                   │
│    - Operator_B (funds and manages Sat_B)                                   │
│    - Sat_A and Sat_B (will hold channel state)                              │
│                                                                             │
│  PROCESS:                                                                   │
│  ────────                                                                   │
│                                                                             │
│  1. NEGOTIATION (operators, ground-based):                                  │
│     Operator_A ◄──────► Operator_B                                          │
│       - Agree on channel capacity                                           │
│       - Agree on initial balance split                                      │
│       - Exchange satellite pubkeys                                          │
│                                                                             │
│  2. FUNDING TRANSACTION (operators create):                                 │
│     Inputs: Operator_A UTXO, Operator_B UTXO                                │
│     Output: 2-of-2 MuSig(Sat_A, Sat_B) channel output                       │
│                                                                             │
│  3. INITIAL STATE (operators create, satellites store):                     │
│     Update_0: spends funding output                                         │
│     Settlement_0: A=initial_A, B=initial_B                                  │
│                                                                             │
│  4. UPLOAD TO SATELLITES:                                                   │
│     Operator_A → Sat_A: channel state, peer info, routes                    │
│     Operator_B → Sat_B: channel state, peer info, routes                    │
│                                                                             │
│  5. BROADCAST FUNDING TX:                                                   │
│     Operators broadcast funding tx                                          │
│     Wait for confirmations                                                  │
│                                                                             │
│  6. CHANNEL ACTIVE:                                                         │
│     Satellites can now transact via ISL                                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Normal Operation (In Space)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NORMAL OPERATION                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites operate autonomously, updating channel states via ISL.          │
│                                                                             │
│  PAYMENT TYPES:                                                             │
│  ──────────────                                                             │
│                                                                             │
│  Direct payment (A pays B directly):                                        │
│    - A and B update their shared channel                                    │
│    - Single state update                                                    │
│                                                                             │
│  Multi-hop payment (A pays C via B):                                        │
│    - A→B: PTLC added to channel state                                       │
│    - B→C: PTLC added to channel state                                       │
│    - C reveals secret, chains resolve                                       │
│    - Two channel updates                                                    │
│                                                                             │
│  SERVICE PAYMENTS:                                                          │
│  ─────────────────                                                          │
│                                                                             │
│    Sat_A requests service from Sat_B:                                       │
│      - Data relay                                                           │
│      - Computation                                                          │
│      - Storage                                                              │
│      - Observation                                                          │
│                                                                             │
│    Payment flow:                                                            │
│      1. A requests service, offers payment                                  │
│      2. B performs service                                                  │
│      3. A verifies service (or uses PTLC for atomicity)                     │
│      4. Channel update: A -payment, B +payment                              │
│                                                                             │
│  STATE MANAGEMENT:                                                          │
│  ─────────────────                                                          │
│    Satellites store:                                                        │
│      - Latest channel state for each peer                                   │
│      - Signed Update_N and Settlement_N                                     │
│      - Can discard older states (LN-Symmetry property)                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Settlement (Ground Contact)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL SETTLEMENT                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  COOPERATIVE CLOSE (preferred):                                             │
│  ──────────────────────────────                                             │
│    During ground contact, operators agree to close:                         │
│                                                                             │
│    1. Query satellites for latest state                                     │
│    2. Verify states match (A and B report same state_N)                     │
│    3. Create closing transaction:                                           │
│       Input: Funding output                                                 │
│       Outputs: Final balances to operator addresses                         │
│    4. Both operators sign                                                   │
│    5. Broadcast                                                             │
│                                                                             │
│    Benefits:                                                                │
│      - Single transaction (no update + settlement)                          │
│      - Immediate availability of funds                                      │
│      - No CSV delay                                                         │
│                                                                             │
│  CROSS-OPERATOR COORDINATION FOR CLOSE:                                     │
│  ──────────────────────────────────────                                     │
│    For channels between different operators (Operator_A ↔ Operator_B):      │
│                                                                             │
│    Challenge: Operators may not have simultaneous ground contact with       │
│    their satellites, and must coordinate out-of-band.                       │
│                                                                             │
│    Protocol:                                                                │
│                                                                             │
│    1. INITIATION (Operator_A wants to close):                               │
│       Operator_A → Operator_B: CloseRequest                                 │
│       {                                                                     │
│         "channel_id": "<channel_id>",                                       │
│         "proposed_close_time": "2024-01-16T12:00:00Z",                      │
│         "sat_a_reported_state": N,                                          │
│         "sat_a_balance": 45000,                                             │
│         "sat_b_balance": 55000,                                             │
│         "operator_a_signature": "<sig>"                                     │
│       }                                                                     │
│                                                                             │
│    2. VERIFICATION (Operator_B checks):                                     │
│       - Query Sat_B for its state (during next ground contact)              │
│       - Verify state matches or determine correct state                     │
│       - If mismatch: follow State Disagreement Resolution (Section 5.4)     │
│                                                                             │
│    3. AGREEMENT (states match):                                             │
│       Operator_B → Operator_A: CloseAccept                                  │
│       {                                                                     │
│         "channel_id": "<channel_id>",                                       │
│         "agreed_state": N,                                                  │
│         "closing_tx": "<unsigned_closing_tx>",                              │
│         "operator_b_signature": "<partial_musig_sig>"                       │
│       }                                                                     │
│                                                                             │
│    4. COMPLETION:                                                           │
│       - Operator_A adds signature, broadcasts closing_tx                    │
│       - Both operators update their records                                 │
│       - Satellites notified of channel closure (optional)                   │
│                                                                             │
│    Asynchronous timing:                                                     │
│      - Close process may span multiple ground contact windows               │
│      - Operators maintain close request state between contacts              │
│      - Timeout: If no response within 72 hours, initiate unilateral close   │
│                                                                             │
│    Communication channel:                                                   │
│      - Operators use dedicated operator-to-operator protocol                │
│      - Can be email, API, or blockchain-based messaging                     │
│      - Messages signed with operator keys for authentication                │
│                                                                             │
│  UNILATERAL CLOSE (fallback):                                               │
│  ─────────────────────────────                                              │
│    If cooperation not possible:                                             │
│                                                                             │
│    1. Broadcast Update_N (latest state)                                     │
│    2. Wait for CSV delay                                                    │
│    3. Broadcast Settlement_N                                                │
│    4. Funds distributed per settlement outputs                              │
│                                                                             │
│    Used when:                                                               │
│      - Other party unresponsive                                             │
│      - Dispute about state                                                  │
│      - Emergency (satellite failing)                                        │
│                                                                             │
│  CHANNEL REBALANCING (keep open):                                           │
│  ─────────────────────────────────                                          │
│    Instead of closing:                                                      │
│                                                                             │
│    1. Check channel balance distribution                                    │
│    2. If imbalanced, add funds or splice                                    │
│    3. Reload routes if network topology changed                             │
│    4. Channel remains open for continued use                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.4 State Disagreement Resolution

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    STATE DISAGREEMENT RESOLUTION                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  During ground contact, operators may discover satellites report            │
│  different state numbers. This section defines resolution procedures.       │
│                                                                             │
│  DETECTION:                                                                 │
│  ──────────                                                                 │
│    Operator_A queries Sat_A: reports state N                                │
│    Operator_B queries Sat_B: reports state M                                │
│    If N ≠ M: state disagreement detected                                    │
│                                                                             │
│  CASE 1: ONE STATE IS HIGHER (N > M)                                        │
│  ────────────────────────────────────                                       │
│    Most common case: one satellite has a more recent state.                 │
│                                                                             │
│    Cause:                                                                   │
│      - ISL connection lost during update protocol                           │
│      - Sat_B crashed before storing state N                                 │
│      - Message loss on final ACK                                            │
│                                                                             │
│    Resolution:                                                              │
│      1. Sat_A has Update_N with both signatures (valid)                     │
│      2. Use Sat_A's state N as authoritative                                │
│      3. Option A: Sync Sat_B to state N during ground contact               │
│         - Operator_B uploads state N to Sat_B                               │
│         - Requires cross-operator coordination                              │
│      4. Option B: Force close using state N                                 │
│         - Broadcast Update_N, Settlement_N                                  │
│         - Clean resolution, channel can be reopened                         │
│                                                                             │
│    Security note: Higher state wins due to LN-Symmetry properties.          │
│    If Sat_A broadcasts Update_N and Sat_B tries Update_M (M < N),           │
│    Update_N will replace Update_M via CSV mechanism.                        │
│                                                                             │
│  CASE 2: BOTH HAVE SAME STATE NUMBER, DIFFERENT CONTENT                     │
│  ───────────────────────────────────────────────────────                    │
│    Critical error: should not occur in correct implementation.              │
│                                                                             │
│    Cause:                                                                   │
│      - Software bug                                                         │
│      - State corruption                                                     │
│      - Byzantine behavior (unlikely in cooperative setup)                   │
│                                                                             │
│    Detection:                                                               │
│      - Operators compare Update_N transaction hashes                        │
│      - If hashes differ for same N: critical disagreement                   │
│                                                                             │
│    Resolution:                                                              │
│      1. HALT all channel operations                                         │
│      2. Both operators broadcast their Update_N                             │
│      3. Only one will confirm (first seen by miners)                        │
│      4. Wait for CSV, broadcast corresponding Settlement_N                  │
│      5. PTLC outputs resolved on-chain                                      │
│      6. Investigate root cause before reopening channel                     │
│                                                                             │
│    Post-mortem required: This indicates implementation error.               │
│                                                                             │
│  CASE 3: SATELLITE REPORTS INVALID/CORRUPTED STATE                          │
│  ──────────────────────────────────────────────────                         │
│    Satellite returns malformed or unverifiable state.                       │
│                                                                             │
│    Detection:                                                               │
│      - Signature verification fails                                         │
│      - State data fails sanity checks                                       │
│      - Satellite reports error/exception                                    │
│                                                                             │
│    Resolution:                                                              │
│      1. Operator retrieves state from watchtower backup                     │
│      2. If watchtower has valid state: use for settlement                   │
│      3. If no valid state available:                                        │
│         - Contact other operator for their satellite's view                 │
│         - Use higher valid state number                                     │
│      4. Force close with best available state                               │
│                                                                             │
│  CROSS-OPERATOR COORDINATION PROTOCOL:                                      │
│  ──────────────────────────────────────                                     │
│    When disagreement detected, operators must communicate:                  │
│                                                                             │
│    1. Exchange state reports:                                               │
│       {                                                                     │
│         "channel_id": "<channel_id>",                                       │
│         "reported_state": N,                                                │
│         "update_tx_hash": "<hash>",                                         │
│         "settlement_tx_hash": "<hash>",                                     │
│         "operator_signature": "<sig>"                                       │
│       }                                                                     │
│                                                                             │
│    2. Compare and agree on authoritative state                              │
│    3. Decide: sync and continue OR force close                              │
│    4. Execute agreed resolution                                             │
│                                                                             │
│    Communication channel: Operator-to-operator protocol                     │
│    (out of band from satellite communication)                               │
│                                                                             │
│  PREVENTION:                                                                │
│  ───────────                                                                │
│    Best practices to minimize state disagreement:                           │
│                                                                             │
│    1. Reliable state persistence on satellites                              │
│       - Write-ahead logging before signing                                  │
│       - fsync before ACK                                                    │
│                                                                             │
│    2. Update protocol completion tracking                                   │
│       - Don't discard old state until ACK received                          │
│       - Timeout and retry if ACK not received                               │
│                                                                             │
│    3. Regular state sync during ground contact                              │
│       - Compare states even when not closing                                │
│       - Early detection of drift                                            │
│                                                                             │
│    4. Watchtower always has latest state                                    │
│       - Update watchtower on every ground contact                           │
│       - Provides authoritative backup                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Routing

### 6.1 Pre-Loaded Route Tables

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PRE-LOADED ROUTING                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites cannot discover routes while offline.                           │
│  Operators pre-compute and load routing tables during ground contact.       │
│                                                                             │
│  ROUTE TABLE STRUCTURE:                                                     │
│  ──────────────────────                                                     │
│    For Sat_A:                                                               │
│    {                                                                        │
│      "routes": [                                                            │
│        {                                                                    │
│          "destination": "Sat_C",                                            │
│          "path": ["Sat_B", "Sat_C"],                                        │
│          "total_fees": 100,                                                 │
│          "min_capacity": 50000,                                             │
│          "expiry_blocks": 288                                               │
│        },                                                                   │
│        {                                                                    │
│          "destination": "Sat_D",                                            │
│          "path": ["Sat_B", "Sat_C", "Sat_D"],                               │
│          "total_fees": 150,                                                 │
│          "min_capacity": 30000,                                             │
│          "expiry_blocks": 432                                               │
│        }                                                                    │
│      ]                                                                      │
│    }                                                                        │
│                                                                             │
│  ROUTE COMPUTATION (ground-based):                                          │
│  ─────────────────────────────────                                          │
│    Operators collaboratively compute routes:                                │
│      1. Share channel graph (capacities, fees)                              │
│      2. Compute shortest/cheapest paths                                     │
│      3. Account for ISL availability windows                                │
│      4. Generate route tables for each satellite                            │
│      5. Upload during ground contact                                        │
│                                                                             │
│  ROUTE STALENESS:                                                           │
│  ────────────────                                                           │
│    Routes can become stale if:                                              │
│      - Channel liquidity shifts                                             │
│      - Channels close unexpectedly                                          │
│      - Satellites go offline                                                │
│                                                                             │
│    Mitigation:                                                              │
│      - Conservative capacity estimates                                      │
│      - Multiple fallback routes                                             │
│      - Frequent route table updates                                         │
│      - Error feedback propagation                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 ISL-Aware Routing

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ISL-AWARE ROUTING                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Inter-Satellite Links are not always available.                            │
│  Routes must account for orbital mechanics.                                 │
│                                                                             │
│  ROUTE WITH ISL WINDOWS:                                                    │
│  ────────────────────────                                                   │
│    {                                                                        │
│      "destination": "Sat_D",                                                │
│      "hops": [                                                              │
│        {                                                                    │
│          "from": "Sat_A",                                                   │
│          "to": "Sat_B",                                                     │
│          "isl_available": "2024-01-15T10:00-10:45"                          │
│        },                                                                   │
│        {                                                                    │
│          "from": "Sat_B",                                                   │
│          "to": "Sat_C",                                                     │
│          "isl_available": "2024-01-15T10:30-11:15"                          │
│        },                                                                   │
│        {                                                                    │
│          "from": "Sat_C",                                                   │
│          "to": "Sat_D",                                                     │
│          "isl_available": "2024-01-15T11:00-11:30"                          │
│        }                                                                    │
│      ]                                                                      │
│    }                                                                        │
│                                                                             │
│  STORE-AND-FORWARD PAYMENTS:                                                │
│  ───────────────────────────                                                │
│    If ISL windows don't overlap perfectly:                                  │
│      - A sends PTLC update to B during A↔B window                           │
│      - B stores pending PTLC                                                │
│      - B forwards to C during B↔C window                                    │
│      - Payment completes asynchronously                                     │
│                                                                             │
│    Timeout must account for:                                                │
│      - Worst-case ISL window gaps                                           │
│      - Full round-trip for PTLC resolution                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Forwarding Fees

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FORWARDING FEE MECHANISM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Multi-hop payments require incentives for forwarding nodes.                │
│  Fees compensate satellites for liquidity lockup and operational costs.     │
│                                                                             │
│  FEE STRUCTURE:                                                             │
│  ──────────────                                                             │
│    Each forwarding hop charges:                                             │
│      fee = base_fee + (amount × fee_rate)                                   │
│                                                                             │
│    Components:                                                              │
│      base_fee:  Fixed fee per forwarded PTLC (e.g., 1 sat)                  │
│      fee_rate:  Proportional fee in parts-per-million (e.g., 100 ppm)       │
│                                                                             │
│    Example (forwarding 10,000 sats):                                        │
│      base_fee = 1 sat                                                       │
│      fee_rate = 100 ppm (0.01%)                                             │
│      fee = 1 + (10000 × 100 / 1000000) = 1 + 1 = 2 sats                     │
│                                                                             │
│  FEE POLICY PUBLICATION:                                                    │
│  ───────────────────────                                                    │
│    Operators publish fee schedules during ground contact:                   │
│                                                                             │
│    {                                                                        │
│      "satellite_id": "Sat_B",                                               │
│      "fee_policy": {                                                        │
│        "base_fee_sat": 1,                                                   │
│        "fee_rate_ppm": 100,                                                 │
│        "min_forwarding_amount": 1000,                                       │
│        "max_forwarding_amount": 1000000                                     │
│      },                                                                     │
│      "effective_from": "2024-01-15T00:00:00Z",                              │
│      "signature": "<operator_signature>"                                    │
│    }                                                                        │
│                                                                             │
│    Fee policies are signed by operators to prevent manipulation.            │
│                                                                             │
│  FEE CALCULATION IN ROUTES:                                                 │
│  ──────────────────────────                                                 │
│    Route tables include pre-computed fees:                                  │
│                                                                             │
│    {                                                                        │
│      "destination": "Sat_D",                                                │
│      "path": ["Sat_B", "Sat_C", "Sat_D"],                                   │
│      "fees_per_hop": [                                                      │
│        {"hop": "A→B", "base": 1, "rate_ppm": 100},                          │
│        {"hop": "B→C", "base": 1, "rate_ppm": 150},                          │
│        {"hop": "C→D", "base": 2, "rate_ppm": 50}                            │
│      ],                                                                     │
│      "total_base_fee": 4,                                                   │
│      "total_rate_ppm": 300                                                  │
│    }                                                                        │
│                                                                             │
│  ONION-STYLE FEE HANDLING:                                                  │
│  ─────────────────────────                                                  │
│    Fees are included in payment amounts at each hop:                        │
│                                                                             │
│    Route: A → B → C (A pays 10,000 sats to C)                               │
│                                                                             │
│    Fee calculation (backward from destination):                             │
│      C receives: 10,000 sats                                                │
│      B→C PTLC:   10,000 + fee_BC = 10,000 + 2 = 10,002 sats                 │
│      A→B PTLC:   10,002 + fee_AB = 10,002 + 2 = 10,004 sats                 │
│                                                                             │
│    A sends 10,004 sats total:                                               │
│      - B keeps 2 sats (fee_AB)                                              │
│      - C keeps 2 sats (fee_BC)                                              │
│      - D receives 10,000 sats                                               │
│                                                                             │
│  FEE SIPHONING PREVENTION:                                                  │
│  ─────────────────────────                                                  │
│    Attack: Malicious node claims higher fee than published                  │
│                                                                             │
│    Prevention:                                                              │
│      1. Fee policies are operator-signed and verifiable                     │
│      2. Route tables contain expected fees per hop                          │
│      3. Forwarding nodes must accept amount within policy                   │
│      4. If fee mismatch detected, PTLC is failed with error                 │
│                                                                             │
│    Verification at each hop:                                                │
│      incoming_amount >= outgoing_amount + expected_fee                      │
│      If violated, fail PTLC with FEE_INSUFFICIENT error                     │
│                                                                             │
│  OPERATOR FEE REVENUE:                                                      │
│  ─────────────────────                                                      │
│    Forwarding fees accumulate in channel balances.                          │
│    Operators collect fees during settlement/rebalancing.                    │
│                                                                             │
│    Revenue flow:                                                            │
│      1. Sat_B forwards payments, earns fees in channel balances             │
│      2. During ground contact, Operator_B observes accumulated fees         │
│      3. Channel close/splice distributes fees to operator                   │
│                                                                             │
│  DYNAMIC FEE ADJUSTMENT:                                                    │
│  ───────────────────────                                                    │
│    Operators may update fees based on:                                      │
│      - Channel liquidity (higher fees when imbalanced)                      │
│      - Network congestion                                                   │
│      - Operational costs                                                    │
│                                                                             │
│    New fee policies uploaded during ground contact take effect              │
│    when route tables are refreshed across the network.                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 PTLC Timeout Budget Calculation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TIMEOUT BUDGET FOR ISL WINDOWS                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PROBLEM:                                                                   │
│  ────────                                                                   │
│    Multi-hop PTLC payments through satellite network face unique timing     │
│    challenges due to ISL availability windows. Standard Lightning timeout   │
│    decrements (e.g., 40 blocks per hop) may be insufficient.                │
│                                                                             │
│  ISL TIMING VARIABLES:                                                      │
│  ─────────────────────                                                      │
│    t_isl_gap(i,j)     = Time gap between ISL windows for hop i→j            │
│    t_isl_duration(i,j) = Duration of ISL window between i and j             │
│    t_orbit           = Orbital period (LEO: ~90-100 minutes)                │
│    t_processing      = On-satellite processing time (~1-10 seconds)         │
│    t_propagation     = Signal propagation time (~1-50 ms)                   │
│                                                                             │
│  TIMEOUT BUDGET COMPONENTS:                                                 │
│  ──────────────────────────                                                 │
│    For route: A → B → C → D                                                 │
│                                                                             │
│    Forward path (payment setup):                                            │
│      t_forward = Σ [t_isl_gap(i,i+1) + t_processing + t_propagation]        │
│                                                                             │
│    Backward path (secret revelation):                                       │
│      t_backward = Σ [t_isl_gap(i+1,i) + t_processing + t_propagation]       │
│                                                                             │
│    Note: Forward and backward ISL gaps may differ due to orbital geometry.  │
│          In LEO, same-plane satellites may have symmetric gaps.             │
│          Cross-plane satellites may have asymmetric gaps.                   │
│                                                                             │
│  WORST-CASE ISL GAP:                                                        │
│  ───────────────────                                                        │
│    Same orbital plane: t_isl_gap ≤ t_orbit (~100 minutes)                   │
│    Adjacent planes: t_isl_gap ≤ 2 × t_orbit (~200 minutes)                  │
│    Distant planes: t_isl_gap ≤ 12 hours (worst case for some geometries)    │
│                                                                             │
│    Recommendation: Use ephemeris data to compute actual gaps per route.     │
│                                                                             │
│  TIMEOUT FORMULA:                                                           │
│  ────────────────                                                           │
│    For hop i (counting from destination):                                   │
│                                                                             │
│      timeout(0) = t_forward_remaining(0) + t_claim_buffer                   │
│      timeout(i) = timeout(i-1) + t_isl_gap_back(i) + t_claim_buffer         │
│                                                                             │
│    Where:                                                                   │
│      t_forward_remaining(i) = remaining ISL gaps from hop i to destination  │
│      t_claim_buffer = time needed to claim (on-chain or off-chain)          │
│                                                                             │
│    Example (3-hop route A→B→C→D, same orbital plane):                       │
│                                                                             │
│      ISL gaps:                                                              │
│        A↔B: 30 minutes gap, next window in 30 min                           │
│        B↔C: 45 minutes gap, next window in 45 min                           │
│        C↔D: 20 minutes gap, next window in 20 min                           │
│                                                                             │
│      Timeout calculation:                                                   │
│        timeout_CD = 20 min (forward) + 20 min (back) + 30 min (buffer)      │
│                   = 70 minutes = ~7 blocks                                  │
│                                                                             │
│        timeout_BC = 45 + 45 + 70 + 30 = 190 minutes = ~19 blocks            │
│                                                                             │
│        timeout_AB = 30 + 30 + 190 + 30 = 280 minutes = ~28 blocks           │
│                                                                             │
│      In blocks (10 min/block):                                              │
│        timeout_CD: height + 7                                               │
│        timeout_BC: height + 19                                              │
│        timeout_AB: height + 28                                              │
│                                                                             │
│  SAFETY MARGINS:                                                            │
│  ───────────────                                                            │
│    Add safety margins for:                                                  │
│      - Unexpected ISL interruptions (weather, attitude maneuvers)           │
│      - Processing delays on resource-constrained satellites                 │
│      - On-chain confirmation variability                                    │
│      - Block time variance                                                  │
│                                                                             │
│    Recommended safety multiplier: 1.5x computed timeout                     │
│                                                                             │
│  CLOCK DRIFT AND SYNCHRONIZATION:                                           │
│  ─────────────────────────────────                                          │
│    Satellites use onboard clocks to track timeout expiration.               │
│    Clock drift can cause early/late timeout detection.                      │
│                                                                             │
│    Clock sources (in preference order):                                     │
│      1. GPS time (when GPS receiver available and has lock)                 │
│      2. Ground-synchronized time (updated during contact)                   │
│      3. Onboard RTC with drift compensation                                 │
│                                                                             │
│    Expected drift rates:                                                    │
│      - GPS-disciplined: < 1 μs drift                                        │
│      - Temperature-compensated crystal: ~1-5 ppm (~5-25 sec/day)            │
│      - Basic crystal oscillator: ~20-100 ppm (~2-9 min/day)                 │
│                                                                             │
│    Mitigation:                                                              │
│      1. Resync clocks during every ground contact                           │
│      2. Add drift margin to timeouts:                                       │
│         drift_margin = max_drift_rate × time_since_sync                     │
│         Example: 50 ppm × 24 hours = 4.3 seconds margin                     │
│      3. Use block height as authoritative time source when possible         │
│      4. Exchange timestamps during ISL contact to detect drift              │
│                                                                             │
│    Block height awareness:                                                  │
│      - Satellites receive block height updates during ground contact        │
│      - Block height is used for PTLC timeout_height comparisons             │
│      - Between contacts, estimate height: last_height + elapsed/600         │
│      - Conservative: assume slower blocks when checking expiry              │
│                                                                             │
│  ISL ANOMALY HANDLING:                                                      │
│  ─────────────────────                                                      │
│    ISL windows can be disrupted by:                                         │
│      - Solar storms (increased noise, link budget degradation)              │
│      - Attitude control maneuvers (antenna pointing loss)                   │
│      - Debris avoidance maneuvers                                           │
│      - Equipment failures                                                   │
│                                                                             │
│    Detection:                                                               │
│      - Expected ISL window doesn't establish                                │
│      - Link quality below threshold                                         │
│      - No response to ping within window                                    │
│                                                                             │
│    Response for pending PTLCs:                                              │
│      1. Check if alternate route exists with sufficient timeout             │
│      2. If no alternate: hold PTLC, retry on next ISL window                │
│      3. If timeout imminent: fail PTLC upstream before local expiry         │
│      4. Track anomaly for route table feedback to ground                    │
│                                                                             │
│    Grace period:                                                            │
│      - Don't immediately fail on missed window                              │
│      - Allow 1 orbital period for recovery                                  │
│      - Fail only if next window also missed or timeout critical             │
│                                                                             │
│  GPS UNAVAILABILITY:                                                        │
│  ───────────────────                                                        │
│    GPS may be unavailable due to:                                           │
│      - Orbital geometry (poor satellite visibility)                         │
│      - Solar interference during equinox                                    │
│      - Receiver malfunction                                                 │
│                                                                             │
│    Fallback timing:                                                         │
│      1. Continue using last GPS-synced time + drift compensation            │
│      2. Widen timeout safety margins during GPS outage                      │
│      3. Flag channels as "reduced timing confidence"                        │
│      4. Avoid initiating new long-timeout payments                          │
│      5. Prioritize resolving existing PTLCs over new ones                   │
│                                                                             │
│  STORE-AND-FORWARD CONSTRAINT:                                              │
│  ─────────────────────────────                                              │
│    CRITICAL: Do NOT forward PTLC if insufficient timeout remains.           │
│                                                                             │
│    Before forwarding at hop i:                                              │
│      remaining_timeout = timeout(i) - current_height                        │
│      required_time = t_forward_remaining(i) + t_back(i) + t_claim_buffer    │
│                                                                             │
│      If remaining_timeout < required_time:                                  │
│        FAIL the PTLC (return to sender)                                     │
│        Do NOT forward (risks being stuck with unfunded outbound PTLC)       │
│                                                                             │
│  ROUTE TABLE ANNOTATION:                                                    │
│  ───────────────────────                                                    │
│    Pre-loaded routes should include computed timeouts:                      │
│                                                                             │
│    {                                                                        │
│      "destination": "Sat_D",                                                │
│      "path": ["Sat_B", "Sat_C", "Sat_D"],                                   │
│      "timeouts": {                                                          │
│        "AB": 28,    // blocks from payment start                            │
│        "BC": 19,                                                            │
│        "CD": 7                                                              │
│      },                                                                     │
│      "computed_at": "2024-01-15T00:00:00Z",                                 │
│      "valid_until": "2024-01-16T00:00:00Z"  // ~1 day validity              │
│    }                                                                        │
│                                                                             │
│    Routes expire because ISL geometry changes with orbital progression.     │
│                                                                             │
│  LONG-HAUL ROUTES:                                                          │
│  ─────────────────                                                          │
│    For routes with many hops or large ISL gaps:                             │
│      - Total timeout may exceed 24+ hours                                   │
│      - Consider breaking into sub-routes with intermediate settlement       │
│      - Use hub satellites with frequent ground contact as waypoints         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Watchtower Service

### 7.1 Ground-Based Watchtowers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WATCHTOWER SERVICE                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites can't watch the blockchain while offline.                       │
│  Operators provide watchtower service for their satellites.                 │
│                                                                             │
│  LN-SYMMETRY WATCHTOWER (simple):                                           │
│  ─────────────────────────────────                                          │
│    Watchtower only needs:                                                   │
│      - Latest Update_N transaction                                          │
│      - Latest Settlement_N transaction                                      │
│                                                                             │
│    Watchtower monitors for:                                                 │
│      - Any Update_M broadcast (M < N)                                       │
│                                                                             │
│    Response:                                                                │
│      - Broadcast Update_N (replaces old state)                              │
│      - Wait for CSV, broadcast Settlement_N                                 │
│                                                                             │
│  NO TOXIC WASTE:                                                            │
│  ───────────────                                                            │
│    Unlike LN-Penalty, watchtower doesn't need:                              │
│      - Full state history                                                   │
│      - Penalty transactions for each old state                              │
│      - Quick response time (just needs to beat CSV delay)                   │
│                                                                             │
│  WATCHTOWER UPDATE PROTOCOL:                                                │
│  ───────────────────────────                                                │
│    During each ground contact:                                              │
│      1. Satellite reports latest state_N                                    │
│      2. Satellite sends Update_N, Settlement_N to watchtower                │
│      3. Watchtower stores (replaces previous)                               │
│      4. Minimal storage: O(channels) not O(updates)                         │
│                                                                             │
│  CROSS-OPERATOR WATCHTOWERS:                                                │
│  ───────────────────────────                                                │
│    For channels between different operators:                                │
│      - Each operator watches for their satellite                            │
│      - Either watchtower can respond to old state                           │
│      - Redundancy improves security                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Integration with Task Payments

### 8.1 Relationship to On-Chain PTLC Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TWO PAYMENT SYSTEMS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  SYSTEM 1: ON-CHAIN PTLCs (PTLC-FALLBACK.md)                                │
│  ───────────────────────────────────────────                                │
│    Purpose: Gateway-coordinated task payments                               │
│    Flow: Customer → Gateway → PTLC chain → Operators                        │
│    Settlement: On-chain (Tx_1 with PTLC outputs)                            │
│    Coordination: Gateway orchestrates everything                            │
│                                                                             │
│  SYSTEM 2: PAYMENT CHANNELS (this document)                                 │
│  ──────────────────────────────────────────                                 │
│    Purpose: Autonomous inter-satellite payments                             │
│    Flow: Satellite ↔ Satellite (via channels)                               │
│    Settlement: Off-chain (channel updates), periodic on-chain               │
│    Coordination: Pre-loaded routes, autonomous operation                    │
│                                                                             │
│  HOW THEY INTERACT:                                                         │
│  ──────────────────                                                         │
│                                                                             │
│    Option A: Separate systems                                               │
│      - Task payments always use on-chain PTLCs                              │
│      - Channels only for autonomous satellite services                      │
│      - Clean separation, simpler                                            │
│                                                                             │
│    Option B: Channels for task payments too                                 │
│      - Gateway has channels into satellite network                          │
│      - Task payments flow through channels                                  │
│      - Better privacy, lower fees, instant                                  │
│      - More complex coordination                                            │
│                                                                             │
│    Option C: Hybrid                                                         │
│      - Small/frequent task payments via channels                            │
│      - Large/infrequent task payments via on-chain                          │
│      - Economic optimization                                                │
│                                                                             │
│  RECOMMENDATION: Start with Option A, evolve to Option C                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Channel Funding from Task Revenue

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FUNDING FLOW                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Task revenue can fund satellite channels:                                  │
│                                                                             │
│    1. Customer pays for task (on-chain PTLC or Lightning)                   │
│    2. Operators receive task revenue                                        │
│    3. Operators allocate portion to satellite channel funding               │
│    4. Channels opened/topped up during ground contact                       │
│    5. Satellites use channel funds for autonomous operations                │
│                                                                             │
│  CHANNEL CAPACITY PLANNING:                                                 │
│  ──────────────────────────                                                 │
│    Operators estimate:                                                      │
│      - Expected autonomous payment volume                                   │
│      - Time between ground contacts                                         │
│      - Routing requirements (liquidity for forwarding)                      │
│                                                                             │
│    Fund channels accordingly:                                               │
│      - Direct channels: expected payment volume + buffer                    │
│      - Routing channels: forwarding volume estimate + buffer                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.3 Task-Payment Routing Coupling

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FUNDAMENTAL CONSTRAINT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Payment MUST follow task routing.                                          │
│                                                                             │
│  Why:                                                                       │
│    - Relay satellites incur costs (bandwidth, storage, opportunity)         │
│    - They must be compensated for forwarding tasks                          │
│    - Forwarding fees are collected via the payment path                     │
│                                                                             │
│  Implication:                                                               │
│    If task routes:  Customer → Relay_B → Relay_C → Executor                 │
│    Then payment routes: Customer → Relay_B → Relay_C → Executor             │
│                                                                             │
│  This means:                                                                │
│    ✗ Cannot pay executor directly while routing task through relays         │
│    ✗ Cannot use different paths for task vs payment                         │
│    ✓ Every satellite in task path earns forwarding fee                      │
│    ✓ Payment atomicity ensures "no relay, no fee"                           │
│                                                                             │
│  CHANNEL REQUIREMENT:                                                       │
│  ────────────────────                                                       │
│    For any task route [S₀, S₁, S₂, ..., Sₙ], channels must exist:          │
│      S₀ ↔ S₁, S₁ ↔ S₂, ..., Sₙ₋₁ ↔ Sₙ                                      │
│                                                                             │
│    Task routes are CONSTRAINED by channel topology.                         │
│    You cannot route a task through satellites without payment channels.     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.4 Channel Provisioning Strategies

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PROVISIONING STRATEGY OPTIONS                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STRATEGY 1: ISL-COMPLETE MESH                                              │
│  ─────────────────────────────                                              │
│    Create a channel for every possible ISL pair.                            │
│                                                                             │
│    If satellites A and B can ever have ISL contact, create A ↔ B channel.   │
│                                                                             │
│    Pros:                                                                    │
│      + Maximum routing flexibility                                          │
│      + Any task route is payable                                            │
│      + Simplest route selection (just find any path)                        │
│                                                                             │
│    Cons:                                                                    │
│      - Capital intensive: O(N²) channels worst case                         │
│      - Liquidity spread thin across many channels                           │
│      - Many channels may be rarely used                                     │
│                                                                             │
│    Channel count for ISL-complete mesh:                                     │
│      Same-plane (P satellites): P channels (ring topology)                  │
│      Cross-plane (P planes × S sats): ~P×S×4 (each sat sees ~4 neighbors)   │
│      Total for Walker constellation: O(N × average_ISL_degree)              │
│                                                                             │
│    Example (Starlink-like, 72 planes × 22 sats = 1584 satellites):          │
│      Average ISL degree: ~4 (2 intra-plane + 2 inter-plane)                 │
│      Channels: ~3,168 (each channel counted once)                           │
│      At 100,000 sats capacity each: 316.8M sats capital (~$200K at $0.0006) │
│                                                                             │
│  STRATEGY 2: ORBITAL-HUB TOPOLOGY                                           │
│  ────────────────────────────────                                           │
│    Designate hub satellites per orbital plane or region.                    │
│    Non-hub satellites only channel with their hub(s).                       │
│                                                                             │
│         Sat_1 ──┐                                                           │
│                 │                                                           │
│         Sat_2 ──┼──► HUB_A ◄────────► HUB_B ◄──┼── Sat_4                   │
│                 │        (plane 1)       (plane 2)  │                       │
│         Sat_3 ──┘                                   └── Sat_5               │
│                                                                             │
│    Pros:                                                                    │
│      + Minimal channels: O(N) instead of O(N²)                              │
│      + Concentrated liquidity in hub channels                               │
│      + Hub satellites can be optimized for routing                          │
│                                                                             │
│    Cons:                                                                    │
│      - Hub is single point of failure                                       │
│      - All payments route through hub (latency, fees)                       │
│      - Hub liquidity limits throughput                                      │
│                                                                             │
│    Channel count:                                                           │
│      Per plane: (S-1) channels to hub                                       │
│      Hub-to-hub: P-1 channels (ring of hubs)                                │
│      Total: P × (S-1) + (P-1) ≈ N                                           │
│                                                                             │
│    Example (72 planes × 22 sats, 1 hub per plane):                          │
│      Spoke channels: 72 × 21 = 1,512                                        │
│      Hub-hub channels: 71                                                   │
│      Total: 1,583 channels (vs 3,168 for mesh)                              │
│      Capital: ~$100K (half of mesh)                                         │
│                                                                             │
│  STRATEGY 3: DEMAND-DRIVEN PROVISIONING                                     │
│  ───────────────────────────────────────                                    │
│    Open channels based on observed or predicted task routing demand.        │
│                                                                             │
│    Process:                                                                 │
│      1. Operators analyze historical task patterns                          │
│      2. Identify high-traffic satellite pairs                               │
│      3. Provision channels for top N% of routes                             │
│      4. Route remaining tasks through existing channels (longer paths)      │
│                                                                             │
│    Pros:                                                                    │
│      + Capital efficient: only fund used routes                             │
│      + Adapts to actual demand                                              │
│      + Can add channels incrementally                                       │
│                                                                             │
│    Cons:                                                                    │
│      - Cold start problem (no history initially)                            │
│      - May miss rare but important routes                                   │
│      - Requires demand forecasting                                          │
│                                                                             │
│  STRATEGY 4: DYNAMIC CHANNEL OPENING                                        │
│  ─────────────────────────────────────                                      │
│    Open channels on-demand when task requires new route.                    │
│                                                                             │
│    Process:                                                                 │
│      1. Task arrives requiring route A → B → C                              │
│      2. Check if A ↔ B and B ↔ C channels exist                             │
│      3. If not, queue task until next ground contact                        │
│      4. Open required channels during ground contact                        │
│      5. Execute task on subsequent orbit                                    │
│                                                                             │
│    Pros:                                                                    │
│      + Perfect capital efficiency                                           │
│      + No wasted liquidity                                                  │
│                                                                             │
│    Cons:                                                                    │
│      - High latency (must wait for ground contact)                          │
│      - On-chain fees for each new channel                                   │
│      - Not suitable for time-sensitive tasks                                │
│                                                                             │
│  RECOMMENDATION:                                                            │
│  ───────────────                                                            │
│    Phase 1 (testbed): Strategy 1 (ISL-complete) - maximize flexibility      │
│    Phase 2 (scale): Strategy 2 (hub) + Strategy 3 (demand-driven)           │
│    Phase 3 (mature): Add Strategy 4 (dynamic) for edge cases                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.5 Liquidity Planning

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LIQUIDITY PLANNING                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Each channel requires capital locked on both sides.                        │
│  Planning must account for payment directionality and volume.               │
│                                                                             │
│  DIRECTIONAL BALANCE:                                                       │
│  ────────────────────                                                       │
│    Channel A ↔ B with 100,000 sats total capacity:                          │
│                                                                             │
│    Initial: A has 50,000 | B has 50,000                                     │
│                                                                             │
│    After A pays B 30,000:                                                   │
│             A has 20,000 | B has 80,000                                     │
│                                                                             │
│    Now A can only send 20,000 more to B (until rebalanced)                  │
│                                                                             │
│  CAPACITY REQUIREMENTS:                                                     │
│  ──────────────────────                                                     │
│    For a satellite pair (A, B), estimate:                                   │
│                                                                             │
│      V_AB = Expected payment volume A → B per rebalancing period            │
│      V_BA = Expected payment volume B → A per rebalancing period            │
│      F_AB = Expected forwarding volume through A → B                        │
│      F_BA = Expected forwarding volume through B → A                        │
│                                                                             │
│    Required channel capacity:                                               │
│      C_total ≥ max(V_AB + F_AB, V_BA + F_BA) × safety_margin                │
│                                                                             │
│    Initial balance allocation:                                              │
│      C_A = (V_AB + F_AB) / (V_AB + F_AB + V_BA + F_BA) × C_total            │
│      C_B = C_total - C_A                                                    │
│                                                                             │
│  EXAMPLE CALCULATION:                                                       │
│  ────────────────────                                                       │
│    Satellite pair in same orbital plane:                                    │
│      - 10 tasks/day routed A → B, average 5,000 sats each                   │
│      - 8 tasks/day routed B → A, average 6,000 sats each                    │
│      - 20 tasks/day forwarded through (A→B direction)                       │
│      - 15 tasks/day forwarded through (B→A direction)                       │
│      - Rebalancing period: 7 days                                           │
│      - Safety margin: 1.5×                                                  │
│                                                                             │
│    V_AB = 10 × 5,000 × 7 = 350,000 sats                                     │
│    V_BA = 8 × 6,000 × 7 = 336,000 sats                                      │
│    F_AB = 20 × 5,000 × 7 = 700,000 sats (forwarding, estimate)              │
│    F_BA = 15 × 5,000 × 7 = 525,000 sats                                     │
│                                                                             │
│    C_total ≥ max(1,050,000, 861,000) × 1.5 = 1,575,000 sats                 │
│                                                                             │
│    Initial allocation:                                                      │
│      C_A = 1,050,000 / 1,911,000 × 1,575,000 ≈ 865,000 sats                 │
│      C_B = 1,575,000 - 865,000 = 710,000 sats                               │
│                                                                             │
│  REBALANCING:                                                               │
│  ────────────                                                               │
│    Channels become unbalanced as payments flow.                             │
│    Rebalancing options during ground contact:                               │
│                                                                             │
│      1. Circular rebalancing: A→B→C→A payment                               │
│      2. Submarine swaps: On-chain ↔ channel swap                            │
│      3. Channel splice: Add/remove funds on-chain                           │
│      4. Close and reopen: Last resort, high on-chain cost                   │
│                                                                             │
│    Rebalancing triggers:                                                    │
│      - Channel balance < 20% on either side                                 │
│      - Predicted imbalance before next ground contact                       │
│      - Operator-initiated redistribution                                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.6 Route Selection Algorithm

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ROUTE SELECTION                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Task routing is CONSTRAINED by channel topology.                           │
│  Route selection must consider both ISL availability AND channel state.     │
│                                                                             │
│  INPUTS:                                                                    │
│  ───────                                                                    │
│    - Source satellite (task originator or relay)                            │
│    - Destination satellite (executor)                                       │
│    - Payment amount                                                         │
│    - ISL contact schedule                                                   │
│    - Channel graph (topology + balances + fees)                             │
│    - PTLC timeout budget                                                    │
│                                                                             │
│  ALGORITHM:                                                                 │
│  ──────────                                                                 │
│    1. Build candidate paths:                                                │
│       - Start with ISL-reachable paths (orbital mechanics)                  │
│       - Filter to paths with channels at each hop                           │
│       - Filter to paths with sufficient balance at each hop                 │
│                                                                             │
│    2. Score each candidate:                                                 │
│       score = w₁ × (1/total_fees)                                           │
│             + w₂ × (1/hop_count)                                            │
│             + w₃ × (1/total_latency)                                        │
│             + w₄ × min_balance_margin                                       │
│                                                                             │
│    3. Select highest-scoring path within timeout budget                     │
│                                                                             │
│  PSEUDOCODE:                                                                │
│  ───────────                                                                │
│    def select_route(src, dst, amount, timeout_budget):                      │
│        # Get ISL-reachable paths                                            │
│        isl_paths = compute_isl_paths(src, dst, schedule)                    │
│                                                                             │
│        candidates = []                                                      │
│        for path in isl_paths:                                               │
│            # Check channel exists and has balance                           │
│            if not has_channels(path):                                       │
│                continue                                                     │
│            if not has_balance(path, amount):                                │
│                continue                                                     │
│            if timeout_required(path) > timeout_budget:                      │
│                continue                                                     │
│                                                                             │
│            candidates.append({                                              │
│                'path': path,                                                │
│                'fees': sum_fees(path, amount),                              │
│                'latency': sum_latency(path),                                │
│                'min_margin': min_balance_margin(path, amount)               │
│            })                                                               │
│                                                                             │
│        if not candidates:                                                   │
│            return RouteError("No viable route")                             │
│                                                                             │
│        return max(candidates, key=score)                                    │
│                                                                             │
│  FAILURE HANDLING:                                                          │
│  ─────────────────                                                          │
│    If no route found:                                                       │
│      1. Return error to task originator                                     │
│      2. Log routing failure for demand analysis                             │
│      3. Operator may provision new channel in future                        │
│                                                                             │
│    If payment fails mid-route:                                              │
│      1. PTLC times out, funds return to sender                              │
│      2. Failure reason propagated back                                      │
│      3. Route marked as unreliable, retry with alternative                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.7 Scaling Analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SCALING ANALYSIS                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  How does capital requirement scale with constellation size?                │
│                                                                             │
│  ASSUMPTIONS:                                                               │
│  ────────────                                                               │
│    - Average channel capacity: 100,000 sats (~$60 at $60K/BTC)              │
│    - Average task payment: 5,000 sats (~$3)                                 │
│    - Average forwarding fee: 1 sat + 100 ppm = ~1.5 sats                    │
│                                                                             │
│  SCENARIO 1: 10-SATELLITE TESTBED (Single operator)                         │
│  ─────────────────────────────────────────────────────                      │
│    Topology: Ring (each sat channels with 2 neighbors)                      │
│    Channels: 10                                                             │
│    Capital: 10 × 100,000 = 1,000,000 sats (~$600)                           │
│    Max hops: 5 (half the ring)                                              │
│                                                                             │
│  SCENARIO 2: 100-SATELLITE CONSTELLATION (Single operator)                  │
│  ─────────────────────────────────────────────────────────                  │
│    Topology: 5 planes × 20 sats, hub per plane                              │
│    Spoke channels: 5 × 19 = 95                                              │
│    Hub-hub channels: 4 (ring of hubs)                                       │
│    Total channels: 99                                                       │
│    Capital: 99 × 100,000 = 9,900,000 sats (~$6,000)                         │
│    Max hops: 4 (spoke → hub → hub → spoke)                                  │
│                                                                             │
│  SCENARIO 3: 1000-SATELLITE MEGA-CONSTELLATION (Multi-operator)             │
│  ──────────────────────────────────────────────────────────────             │
│    Topology: Hierarchical (10 operators × 100 sats each)                    │
│    Intra-operator: 99 channels × 10 = 990                                   │
│    Inter-operator hubs: 45 (full mesh of 10 hubs)                           │
│    Total channels: 1,035                                                    │
│    Capital: 1,035 × 100,000 = 103,500,000 sats (~$62,000)                   │
│    Max hops: 6 (spoke → hub → inter-hub → hub → spoke)                      │
│                                                                             │
│  CAPITAL EFFICIENCY:                                                        │
│  ───────────────────                                                        │
│    Metric: Capital per satellite                                            │
│                                                                             │
│    | Constellation | Satellites | Capital | Per-Sat |                       │
│    |---------------|------------|---------|---------|                       │
│    | Testbed       | 10         | $600    | $60     |                       │
│    | Medium        | 100        | $6,000  | $60     |                       │
│    | Mega          | 1000       | $62,000 | $62     |                       │
│                                                                             │
│    With hub topology, capital scales ~O(N), not O(N²).                      │
│    Per-satellite cost remains roughly constant.                             │
│                                                                             │
│  THROUGHPUT LIMITS:                                                         │
│  ──────────────────                                                         │
│    Hub channels become bottleneck at scale.                                 │
│                                                                             │
│    Hub capacity: 100,000 sats                                               │
│    Average payment: 5,000 sats                                              │
│    Payments before rebalance: 20 (in one direction)                         │
│                                                                             │
│    For 100-sat constellation with 1 hub:                                    │
│      If all 99 spokes send to hub: 20 payments each = 1,980 total           │
│      Before hub channels exhaust in each direction                          │
│                                                                             │
│    Mitigation:                                                              │
│      - Larger hub channel capacities                                        │
│      - Multiple hubs per region                                             │
│      - Direct channels for high-traffic pairs                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.8 Channel Graph Synchronization

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL GRAPH SYNCHRONIZATION                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Each satellite needs current view of channel topology for routing.         │
│  Unlike terrestrial Lightning, satellites cannot gossip continuously.       │
│                                                                             │
│  SYNCHRONIZATION APPROACH:                                                  │
│  ─────────────────────────                                                  │
│    1. Ground-based graph aggregation:                                       │
│       - Operators share channel updates during ground contact               │
│       - Centralized service aggregates into global graph                    │
│       - Graph snapshot computed periodically                                │
│                                                                             │
│    2. Snapshot upload to satellites:                                        │
│       - During ground contact, upload compressed graph snapshot             │
│       - Include: channels, capacities, fees, recent failures                │
│       - Exclude: exact balances (privacy)                                   │
│                                                                             │
│    3. In-space updates (optional):                                          │
│       - Satellites exchange graph diffs during ISL                          │
│       - Only for channels they've directly observed                         │
│       - Propagate failure information                                       │
│                                                                             │
│  GRAPH SNAPSHOT FORMAT:                                                     │
│  ──────────────────────                                                     │
│    {                                                                        │
│      "version": 42,                                                         │
│      "timestamp": "2024-01-15T12:00:00Z",                                   │
│      "channels": [                                                          │
│        {                                                                    │
│          "id": "chan_001",                                                  │
│          "node_a": "sat_A",                                                 │
│          "node_b": "sat_B",                                                 │
│          "capacity_sat": 100000,                                            │
│          "a_fee_base": 1,                                                   │
│          "a_fee_ppm": 100,                                                  │
│          "b_fee_base": 1,                                                   │
│          "b_fee_ppm": 150,                                                  │
│          "a_balance_bucket": "HIGH",  // HIGH/MED/LOW, not exact            │
│          "b_balance_bucket": "MED"                                          │
│        },                                                                   │
│        ...                                                                  │
│      ],                                                                     │
│      "disabled_channels": ["chan_007", "chan_023"],                         │
│      "signature": "<operator_multisig>"                                     │
│    }                                                                        │
│                                                                             │
│  BALANCE BUCKETS:                                                           │
│  ────────────────                                                           │
│    Exact balances are private. Use buckets for routing hints:               │
│      HIGH: >70% of capacity on this side                                    │
│      MED:  30-70% of capacity                                               │
│      LOW:  <30% of capacity                                                 │
│                                                                             │
│    Routing prefers MED→MED or HIGH→LOW to avoid failures.                   │
│                                                                             │
│  STALENESS HANDLING:                                                        │
│  ───────────────────                                                        │
│    Graph may be hours/days old. Mitigation:                                 │
│      - Conservative balance estimates                                       │
│      - Multiple route alternatives                                          │
│      - Probe payments before large transfers                                │
│      - Failure feedback updates local view                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Security Considerations

### 9.1 Threat Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    THREAT MODEL                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  THREAT: Old state broadcast                                                │
│  ─────────────────────────────                                              │
│    Attack: Counterparty broadcasts old favorable state                      │
│    Mitigation: LN-Symmetry allows latest state to replace old               │
│    Watchtower: Operator monitors and responds                               │
│                                                                             │
│  THREAT: Satellite key compromise                                           │
│  ─────────────────────────────────                                          │
│    Attack: Attacker gets satellite's channel keys                           │
│    Impact: Can sign channel updates, steal funds                            │
│    Mitigation: HSM/secure enclave, limited channel capacity                 │
│                                                                             │
│  THREAT: ISL interception                                                   │
│  ─────────────────────────                                                  │
│    Attack: Intercept channel update messages                                │
│    Impact: Learn payment amounts/timing                                     │
│    Mitigation: Encrypted ISL, authenticated messages                        │
│                                                                             │
│  THREAT: Route manipulation                                                 │
│  ────────────────────────────                                               │
│    Attack: Provide false route tables during ground contact                 │
│    Impact: Payments fail or route through malicious nodes                   │
│    Mitigation: Operator verification, route signing                         │
│                                                                             │
│  THREAT: Griefing (PTLC lockup)                                             │
│  ──────────────────────────────                                             │
│    Attack: Start multi-hop PTLC, never complete                             │
│    Impact: Liquidity locked until timeout                                   │
│    Mitigation: Reasonable timeouts, reputation, fees                        │
│                                                                             │
│  THREAT: Store-and-forward griefing                                         │
│  ──────────────────────────────────                                         │
│    Attack: Sender initiates PTLC, forwarding node holds during ISL gap,     │
│            downstream node refuses to forward or goes offline               │
│    Impact: Forwarding node's liquidity locked for extended period           │
│                                                                             │
│    Specific to satellites:                                                  │
│      - ISL gaps mean B can't quickly discover C is unresponsive             │
│      - Long timeouts required for ISL gaps amplify lockup duration          │
│      - B may be unable to fail upstream until next A↔B window               │
│                                                                             │
│    Mitigations:                                                             │
│                                                                             │
│      1. Proactive forwarding check:                                         │
│         Before accepting PTLC, verify downstream satellite is expected      │
│         to be reachable within reasonable time. Reject if next ISL          │
│         window with downstream is too far in future.                        │
│                                                                             │
│      2. Per-peer PTLC limits:                                               │
│         max_pending_ptlcs_per_peer = 5  (configurable)                      │
│         Limits exposure to any single upstream sender.                      │
│                                                                             │
│      3. Forwarding fee as griefing cost:                                    │
│         Even failed PTLCs consume forwarder resources.                      │
│         Consider "hold fee" for PTLCs held beyond threshold time.           │
│         hold_fee = base_hold_fee × (hold_time / reference_time)             │
│                                                                             │
│      4. Reputation tracking:                                                │
│         Track PTLC success rate per source satellite.                       │
│         {                                                                   │
│           "peer_id": "Sat_A",                                               │
│           "ptlcs_forwarded": 100,                                           │
│           "ptlcs_succeeded": 95,                                            │
│           "ptlcs_failed_timeout": 3,                                        │
│           "ptlcs_failed_downstream": 2,                                     │
│           "avg_hold_time_ms": 45000                                         │
│         }                                                                   │
│         Deprioritize or reject PTLCs from low-reputation peers.             │
│                                                                             │
│      5. Timeout budget enforcement:                                         │
│         Strict enforcement of store-and-forward constraint.                 │
│         Never forward if timeout budget insufficient.                       │
│         Fail fast rather than hold and potentially lose funds.              │
│                                                                             │
│      6. Channel reserve increase:                                           │
│         Increase reserve requirement when forwarding to peers               │
│         with poor reputation or during ISL uncertainty periods.             │
│                                                                             │
│  THREAT: Watchtower failure                                                 │
│  ────────────────────────────                                               │
│    Attack: Compromise watchtower, broadcast old state                       │
│    Impact: If watchtower doesn't respond, funds at risk                     │
│    Mitigation: Multiple watchtowers, cross-operator watching                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Implementation Considerations

### 10.1 Satellite Requirements

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SATELLITE REQUIREMENTS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  STORAGE:                                                                   │
│    Per channel:                                                             │
│      - Latest Update_N: ~200 bytes                                          │
│      - Latest Settlement_N: ~200 bytes                                      │
│      - Channel metadata: ~100 bytes                                         │
│      - Pending PTLCs: ~100 bytes each                                       │
│                                                                             │
│    With 10 channels, 5 pending PTLCs each: ~10 KB                           │
│    Route tables: ~10-50 KB (depends on network size)                        │
│                                                                             │
│  COMPUTATION:                                                               │
│    - Schnorr signature verification: ~1ms                                   │
│    - MuSig2 partial signing: ~2ms                                           │
│    - Adaptor signature operations: ~2ms                                     │
│    - State update: ~10ms total                                              │
│                                                                             │
│  COMMUNICATION:                                                             │
│    - Channel update message: ~500 bytes                                     │
│    - PTLC add message: ~300 bytes                                           │
│    - Route lookup: local (pre-loaded)                                       │
│                                                                             │
│  COMPATIBLE WITH EMBEDDED SYSTEMS:                                          │
│    - Minimal storage requirements                                           │
│    - Efficient cryptographic operations                                     │
│    - No blockchain sync needed                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Protocol Messages

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CHANNEL PROTOCOL MESSAGES                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  CHANNEL_UPDATE:                                                            │
│    {                                                                        │
│      type: "channel_update",                                                │
│      channel_id: <32 bytes>,                                                │
│      state_number: <uint64>,                                                │
│      balances: { a: <sats>, b: <sats> },                                    │
│      pending_ptlcs: [ ... ],                                                │
│      signature: <64 bytes, partial MuSig>                                   │
│    }                                                                        │
│                                                                             │
│  CHANNEL_UPDATE_ACK:                                                        │
│    {                                                                        │
│      type: "channel_update_ack",                                            │
│      channel_id: <32 bytes>,                                                │
│      state_number: <uint64>,                                                │
│      signature: <64 bytes, partial MuSig>                                   │
│    }                                                                        │
│                                                                             │
│  PTLC_ADD:                                                                  │
│    {                                                                        │
│      type: "ptlc_add",                                                      │
│      channel_id: <32 bytes>,                                                │
│      ptlc_id: <uint64>,                                                     │
│      amount: <sats>,                                                        │
│      adaptor_point: <32 bytes>,                                             │
│      timeout_blocks: <uint32>,                                              │
│      onion_packet: <optional, for multi-hop>                                │
│    }                                                                        │
│                                                                             │
│  PTLC_FULFILL:                                                              │
│    {                                                                        │
│      type: "ptlc_fulfill",                                                  │
│      channel_id: <32 bytes>,                                                │
│      ptlc_id: <uint64>,                                                     │
│      adaptor_secret: <32 bytes>                                             │
│    }                                                                        │
│                                                                             │
│  PTLC_FAIL:                                                                 │
│    {                                                                        │
│      type: "ptlc_fail",                                                     │
│      channel_id: <32 bytes>,                                                │
│      ptlc_id: <uint64>,                                                     │
│      error_code: <uint16>,                                                  │
│      failure_source: <optional, 32 bytes - satellite that generated error> │
│    }                                                                        │
│                                                                             │
│  ERROR CODES:                                                               │
│  ────────────                                                               │
│    Channel errors (0x00xx):                                                 │
│      0x0001  INVALID_CHANNEL        Channel ID not recognized               │
│      0x0002  CHANNEL_DISABLED       Channel temporarily disabled            │
│      0x0003  CHANNEL_CLOSING        Channel in closing state                │
│      0x0004  INSUFFICIENT_BALANCE   Sender balance too low                  │
│      0x0005  BELOW_MINIMUM          Amount below minimum PTLC               │
│      0x0006  ABOVE_MAXIMUM          Amount exceeds max in-flight            │
│      0x0007  TOO_MANY_PTLCS         Max pending PTLCs reached               │
│      0x0008  RESERVE_VIOLATION      Would violate reserve requirement       │
│                                                                             │
│    Routing errors (0x01xx):                                                 │
│      0x0100  UNKNOWN_NEXT_PEER      Next hop not in route table             │
│      0x0101  ISL_UNAVAILABLE        No ISL window to next hop               │
│      0x0102  DOWNSTREAM_TIMEOUT     Timeout too short for forward path      │
│      0x0103  ROUTE_EXPIRED          Route table entry expired               │
│      0x0104  NO_ROUTE               No route to destination                 │
│                                                                             │
│    Payment errors (0x02xx):                                                 │
│      0x0200  INVALID_AMOUNT         Amount mismatch in forwarding           │
│      0x0201  FEE_INSUFFICIENT       Forwarding fee too low                  │
│      0x0202  INVALID_ADAPTOR        Adaptor point validation failed         │
│      0x0203  TIMEOUT_EXPIRED        PTLC timeout reached                    │
│      0x0204  PTLC_UNKNOWN           PTLC ID not found                       │
│                                                                             │
│    Temporary errors (0x03xx):                                               │
│      0x0300  TEMPORARY_FAILURE      Try again later                         │
│      0x0301  LOW_NONCES             Nonce pool near exhaustion              │
│      0x0302  PROCESSING_ERROR       Internal processing failure             │
│      0x0303  RATE_LIMITED           Too many requests from peer             │
│                                                                             │
│    Final errors (0x04xx):                                                   │
│      0x0400  PERMANENT_FAILURE      Do not retry                            │
│      0x0401  PEER_OFFLINE           Downstream peer unresponsive            │
│      0x0402  REJECTED_BY_DEST       Final destination rejected              │
│                                                                             │
│  ERROR PROPAGATION:                                                         │
│  ──────────────────                                                         │
│    Multi-hop payments propagate errors upstream:                            │
│      - Forwarding node receives error from downstream                       │
│      - Wraps in own PTLC_FAIL, sets failure_source                          │
│      - Sender can identify failing hop for route pruning                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.3 Key Hierarchy (Shared with On-Chain PTLC)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    KEY HIERARCHY FOR CHANNELS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  UNIFIED INFRASTRUCTURE: See PTLC-FALLBACK.md Section 14 for the complete   │
│  unified key hierarchy, nonce pool, and HSM interface shared between        │
│  on-chain PTLCs (Phase 1) and payment channels (Phase 2).                   │
│                                                                             │
│  This section documents channel-specific key derivations that extend        │
│  the unified hierarchy.                                                     │
│                                                                             │
│  ROOT KEY (same as PTLC-FALLBACK.md):                                       │
│  ─────────────────────────────────────                                      │
│    k_root = generated at manufacture, stored in HSM                         │
│    Never exported, used only for derivation                                 │
│                                                                             │
│  CHANNEL-SPECIFIC DERIVED KEYS:                                             │
│  ──────────────────────────────                                             │
│                                                                             │
│    DERIVATION FORMAT:                                                       │
│      All derivations use length-prefixed fields to prevent collision:       │
│      field = <1-byte length> || <field bytes>                               │
│                                                                             │
│      For fixed-size fields (32-byte IDs), length prefix is omitted.         │
│      For variable-length strings, 1-byte length prefix is required.         │
│                                                                             │
│    Channel identity key (per peer):                                         │
│      info = "channel_id" || <32-byte satellite_id> || <32-byte peer_id>     │
│      k_channel_id = HKDF(k_root, info)                                      │
│      P_channel_id = k_channel_id · G                                        │
│      Used for: Channel funding output MuSig2 aggregation                    │
│                                                                             │
│    Channel update key:                                                      │
│      info = "channel_update" || <32-byte satellite_id> || <32-byte chan_id> │
│      k_update = HKDF(k_root, info)                                          │
│      P_update = k_update · G                                                │
│      Used for: Signing Update transactions (with SIGHASH_ANYPREVOUT)        │
│                                                                             │
│    Channel settlement key:                                                  │
│      info = "channel_settle" || <32-byte satellite_id> || <32-byte chan_id> │
│      k_settle = HKDF(k_root, info)                                          │
│      P_settle = k_settle · G                                                │
│      Used for: Signing Settlement transactions                              │
│                                                                             │
│    PTLC adaptor key (per PTLC):                                             │
│      info = "ptlc" || <32-byte sat_id> || <32-byte chan_id> || <8-byte id>  │
│      k_ptlc = HKDF(k_root, info)                                            │
│      Used for: Creating/verifying adaptor signatures for channel PTLCs      │
│                                                                             │
│    COLLISION PREVENTION:                                                    │
│      - satellite_id: 32 bytes (SHA256 of satellite public key)              │
│      - peer_id: 32 bytes (SHA256 of peer satellite public key)              │
│      - channel_id: 32 bytes (SHA256 of funding outpoint)                    │
│      - ptlc_id: 8 bytes (uint64, big-endian)                                │
│                                                                             │
│      Fixed-width fields eliminate ambiguity in concatenation.               │
│      Different key types use different string prefixes.                     │
│                                                                             │
│  RELATIONSHIP TO ON-CHAIN PTLC KEYS:                                        │
│  ────────────────────────────────────                                       │
│    On-chain PTLC model (PTLC-FALLBACK.md):                                  │
│      k_payment = HKDF(k_root, "payment" || satellite_id || version)         │
│      Used for: On-chain PTLC claims, ack signatures                         │
│                                                                             │
│    Channel model (this document):                                           │
│      k_channel_* = HKDF(k_root, "channel_*" || ...)                         │
│      Used for: Off-chain channel operations                                 │
│                                                                             │
│    DISTINCTION: Different derivation paths ensure keys cannot be confused.  │
│    Compromising one key type doesn't compromise the other.                  │
│                                                                             │
│  KEY ROTATION:                                                              │
│  ─────────────                                                              │
│    Channel keys can be rotated by:                                          │
│      1. Cooperative close of existing channel                               │
│      2. Re-open with new channel_id (generates new keys)                    │
│                                                                             │
│    This is simpler than on-chain key rotation because channels              │
│    have natural lifecycle boundaries.                                       │
│                                                                             │
│  OPERATOR RECOVERY:                                                         │
│  ──────────────────                                                         │
│    Same recovery mechanism as PTLC-FALLBACK.md:                             │
│      - Funds sent to recovery-enabled addresses                             │
│      - Operator can recover after 6-month CLTV if satellite fails           │
│      - Channel settlement outputs use same recovery structure               │
│                                                                             │
│  HSM REQUIREMENTS:                                                          │
│  ─────────────────                                                          │
│    Satellite HSM must support:                                              │
│      - Schnorr signatures (BIP 340)                                         │
│      - MuSig2 partial signatures (BIP 327)                                  │
│      - SIGHASH_ANYPREVOUT signatures (BIP 118)                              │
│      - Adaptor signature creation and completion                            │
│      - Secure key derivation (HKDF)                                         │
│                                                                             │
│    All channel operations use keys derived from k_root.                     │
│    HSM never exports k_root or derived private keys.                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.4 Version Negotiation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PROTOCOL VERSION NEGOTIATION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites may run different protocol versions. Version negotiation        │
│  ensures compatibility before channel operations.                           │
│                                                                             │
│  VERSION FORMAT:                                                            │
│  ───────────────                                                            │
│    version = major.minor.patch                                              │
│                                                                             │
│    major: Incompatible protocol changes                                     │
│    minor: Backward-compatible feature additions                             │
│    patch: Bug fixes, no protocol impact                                     │
│                                                                             │
│    Example: 1.2.3                                                           │
│                                                                             │
│  NEGOTIATION DURING CHANNEL SETUP:                                          │
│  ──────────────────────────────────                                         │
│    Operators negotiate version during ground-based channel opening:         │
│                                                                             │
│    1. Operator_A announces supported versions:                              │
│       {                                                                     │
│         "satellite_id": "Sat_A",                                            │
│         "supported_versions": ["1.0", "1.1", "1.2"],                        │
│         "preferred_version": "1.2",                                         │
│         "min_version": "1.0"                                                │
│       }                                                                     │
│                                                                             │
│    2. Operator_B responds with selected version:                            │
│       {                                                                     │
│         "satellite_id": "Sat_B",                                            │
│         "supported_versions": ["1.1", "1.2"],                               │
│         "selected_version": "1.2"                                           │
│       }                                                                     │
│                                                                             │
│    3. Channel configured with negotiated version                            │
│                                                                             │
│  FEATURE FLAGS:                                                             │
│  ──────────────                                                             │
│    Optional features within a version can be negotiated:                    │
│                                                                             │
│    {                                                                        │
│      "features": {                                                          │
│        "hold_fees": true,       // Support for hold fee mechanism           │
│        "reputation": true,      // Reputation tracking                      │
│        "alt_routes": false,     // Alternative route support                │
│        "aggregation": true      // Payment aggregation                      │
│      }                                                                      │
│    }                                                                        │
│                                                                             │
│    Channel uses intersection of both satellites' feature sets.              │
│                                                                             │
│  VERSION UPGRADE:                                                           │
│  ────────────────                                                           │
│    Satellites can be upgraded during ground contact:                        │
│                                                                             │
│    1. New firmware uploaded with new protocol version                       │
│    2. Existing channels continue at old version                             │
│    3. New channels can use new version                                      │
│    4. Optional: Migrate channels to new version via close/reopen            │
│                                                                             │
│  INCOMPATIBILITY HANDLING:                                                  │
│  ─────────────────────────                                                  │
│    If satellites have no compatible version:                                │
│      - Channel cannot be opened                                             │
│      - Operators must upgrade at least one satellite                        │
│      - Existing channels remain operational at original version             │
│                                                                             │
│  MESSAGE VERSION HEADER:                                                    │
│  ───────────────────────                                                    │
│    All protocol messages include version for validation:                    │
│                                                                             │
│    {                                                                        │
│      "protocol_version": "1.2",                                             │
│      "type": "channel_update",                                              │
│      ...                                                                    │
│    }                                                                        │
│                                                                             │
│    If version mismatch: reject message with PROTOCOL_VERSION error          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.5 Failure Recovery

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SATELLITE FAILURE RECOVERY                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Satellites may fail during channel operations. This section defines        │
│  recovery procedures for various failure scenarios.                         │
│                                                                             │
│  FAILURE TYPES:                                                             │
│  ──────────────                                                             │
│    1. Transient: Satellite reboots, recovers state from storage             │
│    2. Storage corruption: State data corrupted or lost                      │
│    3. Total loss: Satellite destroyed or permanently offline                │
│    4. Partial failure: Some subsystems operational                          │
│                                                                             │
│  SCENARIO 1: REBOOT DURING UPDATE                                           │
│  ─────────────────────────────────                                          │
│    Satellite crashes mid-update protocol (after signing, before ACK).       │
│                                                                             │
│    On recovery:                                                             │
│      1. Check persistent state for incomplete updates                       │
│      2. If new state signed but not ACK'd:                                  │
│         - Both old and new states may be valid                              │
│         - Peer may or may not have completed                                │
│      3. On next ISL contact with peer:                                      │
│         - Exchange state numbers                                            │
│         - Agree on authoritative state (higher number wins)                 │
│      4. Continue from agreed state                                          │
│                                                                             │
│    Critical: Never reuse nonces. Check nonce consumption bitmap on boot.    │
│                                                                             │
│  SCENARIO 2: STORAGE CORRUPTION                                             │
│  ──────────────────────────────                                             │
│    Satellite detects corrupted channel state.                               │
│                                                                             │
│    Detection:                                                               │
│      - Checksum/signature verification fails                                │
│      - State data inconsistent (balances don't sum to capacity)             │
│      - State number regresses unexpectedly                                  │
│                                                                             │
│    Recovery:                                                                │
│      1. Mark channel as CORRUPTED, disable updates                          │
│      2. Signal to ground on next contact: "channel state corrupted"         │
│      3. Operator retrieves state from watchtower backup                     │
│      4. Options:                                                            │
│         a. Upload watchtower state to satellite, resume                     │
│         b. Force close using watchtower state                               │
│         c. Coordinate with peer operator for resolution                     │
│                                                                             │
│    Prevention:                                                              │
│      - Redundant state storage (primary + backup)                           │
│      - ECC-protected memory                                                 │
│      - Periodic integrity verification                                      │
│                                                                             │
│  SCENARIO 3: SATELLITE TOTAL LOSS                                           │
│  ────────────────────────────────                                           │
│    Satellite is destroyed or permanently unreachable.                       │
│                                                                             │
│    Discovery:                                                               │
│      - Multiple missed ground contacts                                      │
│      - Telemetry indicates failure                                          │
│      - No response on any communication channel                             │
│                                                                             │
│    Recovery procedure:                                                      │
│      1. Operator declares satellite lost                                    │
│      2. For each channel with lost satellite:                               │
│         a. Retrieve latest state from watchtower                            │
│         b. Broadcast Update_N, wait CSV, broadcast Settlement_N             │
│         c. Resolve any pending PTLCs on-chain                               │
│      3. Notify peer operators of channel closures                           │
│      4. Update route tables to remove lost satellite                        │
│                                                                             │
│    Operator fund recovery:                                                  │
│      - Settlement outputs include operator recovery path                    │
│      - Operator can claim after 6-month CLTV (see PTLC-FALLBACK.md)         │
│      - Prevents total loss of channel funds                                 │
│                                                                             │
│  SCENARIO 4: FAILURE DURING PTLC                                            │
│  ─────────────────────────────────                                          │
│    Satellite fails with pending PTLCs in-flight.                            │
│                                                                             │
│    Impact:                                                                  │
│      - Pending PTLCs cannot be resolved off-chain                           │
│      - Upstream PTLCs may timeout while waiting                             │
│      - Liquidity locked across multiple channels                            │
│                                                                             │
│    Recovery:                                                                │
│      1. On satellite recovery:                                              │
│         - Resume PTLC resolution via ISL                                    │
│         - Prioritize PTLCs near timeout                                     │
│      2. If satellite unrecoverable:                                         │
│         - Force close all affected channels                                 │
│         - PTLCs resolve on-chain via claim/timeout                          │
│         - Upstream nodes learn t from blockchain or timeout                 │
│                                                                             │
│    Multi-hop impact:                                                        │
│      - Intermediate failure may block entire payment path                   │
│      - Timeout decrements provide time for recovery attempts                │
│      - Worst case: all PTLCs in path timeout, sender refunded               │
│                                                                             │
│  SCENARIO 5: PARTIAL FAILURE                                                │
│  ──────────────────────────                                                 │
│    Some satellite subsystems fail (e.g., ISL antenna, HSM).                 │
│                                                                             │
│    ISL failure:                                                             │
│      - Cannot update channels via ISL                                       │
│      - Can still communicate via ground relay                               │
│      - Operator proxies messages between satellites                         │
│      - Slower but functional for critical operations                        │
│                                                                             │
│    HSM failure:                                                             │
│      - Cannot sign new states                                               │
│      - Existing states remain valid                                         │
│      - Force close all channels using last signed state                     │
│      - Satellite effectively becomes read-only for payments                 │
│                                                                             │
│  RECOVERY COORDINATION PROTOCOL:                                            │
│  ────────────────────────────────                                           │
│    When failure detected:                                                   │
│                                                                             │
│    1. Operator broadcasts SATELLITE_FAILURE notice to peers:                │
│       {                                                                     │
│         "satellite_id": "Sat_A",                                            │
│         "failure_type": "total_loss | partial | recovering",                │
│         "affected_channels": ["<chan_id_1>", "<chan_id_2>"],                │
│         "estimated_recovery": "<timestamp or null>",                        │
│         "action_requested": "wait | close_cooperative | close_unilateral"   │
│       }                                                                     │
│                                                                             │
│    2. Peer operators acknowledge and take appropriate action                │
│    3. Route tables updated to reflect failure                               │
│    4. When recovered, broadcast SATELLITE_RECOVERED notice                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Future Extensions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FUTURE EXTENSIONS                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  DYNAMIC CHANNEL MANAGEMENT:                                                │
│    - Open channels on-demand via ISL                                        │
│    - Splice in/out without closing                                          │
│    - Automatic rebalancing                                                  │
│                                                                             │
│  CROSS-LAYER INTEGRATION:                                                   │
│    - Task payments via channels (not on-chain)                              │
│    - Gateway channels into satellite network                                │
│    - Unified payment routing                                                │
│                                                                             │
│  DECENTRALIZED ROUTING:                                                     │
│    - Satellites share route info via ISL                                    │
│    - Gossip-style route discovery                                           │
│    - Less dependence on ground-computed routes                              │
│                                                                             │
│  SUBMARINE SWAPS:                                                           │
│    - Swap between on-chain and channel funds                                │
│    - Emergency liquidity                                                    │
│    - Cross-system atomic swaps                                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. Comparison: On-Chain PTLCs vs Payment Channels

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COMPARISON                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  FUNDAMENTAL CHARACTERISTICS:                                               │
│  ────────────────────────────                                               │
│  ┌────────────────────┬─────────────────────┬─────────────────────────────┐│
│  │ Aspect             │ On-Chain PTLCs      │ Payment Channels            ││
│  ├────────────────────┼─────────────────────┼─────────────────────────────┤│
│  │ Settlement         │ On-chain            │ Off-chain (mostly)          ││
│  │ Speed              │ ~10-60 min confirm  │ Instant                     ││
│  │ Fees               │ Per-transaction     │ Per-channel (amortized)     ││
│  │ Privacy            │ Visible on-chain    │ Only open/close visible     ││
│  │ Offline operation  │ Limited             │ Full (pre-loaded routes)    ││
│  │ Liquidity          │ Per-task            │ Pre-committed               ││
│  │ Complexity         │ Simpler             │ More complex                ││
│  │ Best for           │ Large, infrequent   │ Small, frequent             ││
│  │ Dependencies       │ None                │ BIP 118                     ││
│  └────────────────────┴─────────────────────┴─────────────────────────────┘│
│                                                                             │
│  PAYMENT TYPE SUPPORT (Two Orthogonal Dimensions):                          │
│  ─────────────────────────────────────────────────                          │
│                                                                             │
│    Funding mechanism and payment initiator are ORTHOGONAL concerns:         │
│                                                                             │
│    ┌─────────────────────┬─────────────────────┬─────────────────────────┐ │
│    │                     │ TASK PAYMENTS       │ AUTONOMOUS PAYMENTS     │ │
│    │                     │ (Gateway-Initiated) │ (Satellite-Initiated)   │ │
│    ├─────────────────────┼─────────────────────┼─────────────────────────┤ │
│    │ ON-CHAIN PTLCs      │ Natural fit         │ Possible but awkward    │ │
│    │ (Phase 1)           │ Gateway coordinates │ Requires pre-funded     │ │
│    │                     │ Fresh UTXO per task │ UTXOs, delayed settle   │ │
│    ├─────────────────────┼─────────────────────┼─────────────────────────┤ │
│    │ PAYMENT CHANNELS    │ Natural fit         │ Natural fit             │ │
│    │ (Phase 2)           │ Task via channels   │ Instant settlement      │ │
│    │                     │ Same delivery proof │ No ground coordination  │ │
│    └─────────────────────┴─────────────────────┴─────────────────────────┘ │
│                                                                             │
│  WHY AUTONOMOUS ON-CHAIN IS AWKWARD:                                        │
│  ───────────────────────────────────                                        │
│    □ Satellites need pre-funded UTXOs (can't create without ground)         │
│    □ Each autonomous payment needs ~10-60 min confirmation                  │
│    □ Creates on-chain clutter for small payments                            │
│    □ Single-use UTXOs make multi-payment flows cumbersome                   │
│    □ Gateway must pre-fund satellites during ground contact                 │
│                                                                             │
│  WHY CHANNELS EXCEL AT BOTH:                                                │
│  ──────────────────────────                                                 │
│    □ Pre-committed liquidity available instantly                            │
│    □ Off-chain updates (no confirmation delay)                              │
│    □ Same channel serves task AND autonomous payments                       │
│    □ Batteries-included for satellite autonomy                              │
│    □ Gateway-initiated task payments work unchanged                         │
│                                                                             │
│  RECOMMENDATION:                                                            │
│  ───────────────                                                            │
│    Two-phase deployment:                                                    │
│      Phase 1: On-chain PTLCs (today, primarily gateway-initiated tasks)     │
│      Phase 2: Payment channels (when BIP 118 activates)                     │
│                                                                             │
│    Phase 2 enables:                                                         │
│      □ Task payments routed through channels (faster, cheaper)              │
│      □ Autonomous payments become practical                                 │
│      □ Inter-satellite economy without ground coordination                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. Upgrade Path from On-Chain PTLCs

This document describes Phase 2 of the satellite payment system. For a smooth upgrade from Phase 1 (on-chain PTLCs), see PTLC-FALLBACK.md Section 14-15 for the unified infrastructure and upgrade path documentation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RELATIONSHIP TO PTLC-FALLBACK.md                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PHASE 1 (PTLC-FALLBACK.md): On-Chain PTLCs                                 │
│  ───────────────────────────────────────────                                │
│    Status: Implementable today                                              │
│    Dependencies: None (uses existing Bitcoin features)                      │
│    Payment types:                                                           │
│      □ Task payments (gateway-initiated) - natural fit                      │
│      □ Autonomous payments - possible but awkward                           │
│                                                                             │
│    Satellites operate with:                                                 │
│      □ Fresh UTXO per task                                                  │
│      □ Satellite creates adaptor sig (unified convention)                   │
│      □ On-chain settlement per task                                         │
│                                                                             │
│  PHASE 2 (this document): Payment Channels                                  │
│  ─────────────────────────────────────────                                  │
│    Status: Requires BIP 118 (SIGHASH_ANYPREVOUT)                            │
│    Dependencies: Soft fork activation                                       │
│    Payment types:                                                           │
│      □ Task payments (gateway-initiated) - natural fit                      │
│      □ Autonomous payments (satellite-initiated) - natural fit              │
│                                                                             │
│    Satellites upgrade to add:                                               │
│      □ LN-Symmetry channel state management                                 │
│      □ MuSig2 for channel funding                                           │
│      □ Off-chain PTLC updates                                               │
│                                                                             │
│  WHAT STAYS THE SAME:                                                       │
│  ─────────────────────                                                      │
│    □ Unified adaptor convention (receiver creates)                          │
│    □ Script: <P_receiver> OP_CHECKSIG                                       │
│    □ HSM adaptor operations (create, complete, extract)                     │
│    □ Nonce pool management                                                  │
│    □ Key derivation hierarchy                                               │
│    □ Signature-as-secret for task payment delivery proof                    │
│    □ Receiver-generates-secret for autonomous payments                      │
│                                                                             │
│  WHAT GETS ADDED:                                                           │
│  ─────────────────                                                          │
│    □ MuSig2 operations in HSM                                               │
│    □ SIGHASH_ANYPREVOUT signatures                                          │
│    □ Channel state management                                               │
│    □ Optional privacy tweaks (T_i = T_base + tweak_i·G)                     │
│                                                                             │
│  UPGRADE PROCESS:                                                           │
│  ────────────────                                                           │
│    1. Deploy Phase 1 satellites with unified infrastructure                 │
│    2. Task payments work via on-chain PTLCs                                 │
│    3. When BIP 118 activates, upgrade HSM firmware                          │
│    4. Open channels between satellites during ground contact                │
│    5. Satellites can use channels for BOTH payment types:                   │
│       - Task payments: faster, cheaper than on-chain                        │
│       - Autonomous payments: now practical (instant settlement)             │
│                                                                             │
│  UNIFIED INFRASTRUCTURE (PTLC-FALLBACK.md Section 14):                      │
│  ─────────────────────────────────────────────────────                      │
│    14.1 Unified Adaptor Signature Convention                                │
│    14.2 Unified Key Hierarchy                                               │
│    14.3 Unified Nonce Pool                                                  │
│    14.4 Unified HSM Interface                                               │
│    14.5 Unified Protocol Messages                                           │
│                                                                             │
│    Implementing these in Phase 1 ensures smooth Phase 2 upgrade.            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
