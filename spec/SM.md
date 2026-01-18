# SCRAP Task Routing State Machine

## Overview
This document defines the per-node, per-task state machine used by SCRAP/SISL
to provide reliable task delivery and acknowledgement over unreliable,
chaotic transports (MANET, DTN, satellite links).

## Design Goals
- Deterministic local behavior
- Multi-path fallback routing
- Cryptographically verifiable execution
- Bounded retries and authority
- Transport-agnostic operation

## Task Lifecycle State Machine

```mermaid
stateDiagram-v2
    direction LR

    [*] --> NONE
    NONE --> RECEIVED: TASK_OFFER

    state RECEIVED {
        [*] --> VALIDATING
        VALIDATING --> [*]: validate_ok
        VALIDATING --> [*]: validate_fail
    }

    RECEIVED --> FAILED: validate_fail
    RECEIVED --> VALIDATED: validate_ok

    VALIDATED --> EXECUTING: role == EXECUTOR
    VALIDATED --> IN_CUSTODY: role == RELAY

    EXECUTING --> DELIVERED: ER(DONE)
    EXECUTING --> DELIVERED: ER(ALREADY_DONE)
    EXECUTING --> DELIVERED: ER(IN_PROGRESS)
    EXECUTING --> DELIVERED: ER(REFUSED)

    note right of EXECUTING
      Idempotent execution.
      If TaskID already seen:
      return ER(ALREADY_DONE / IN_PROGRESS)
    end note

    IN_CUSTODY --> FORWARDING: select_next_hop
    FORWARDING --> WAIT_DOWNSTREAM: TASK_FORWARD sent

    WAIT_DOWNSTREAM --> WAIT_TERMINAL: CUSTODY_ACCEPT
    WAIT_DOWNSTREAM --> IN_CUSTODY: hop timeout (fallback)

    WAIT_TERMINAL --> DELIVERED: ER or DR received
    WAIT_TERMINAL --> IN_CUSTODY: terminal timeout (fallback)

    DELIVERED --> ACKING: begin ACK return
    ACKING --> ACKING: ACK timeout (fallback)
    ACKING --> COMPLETE: ACK accepted

    COMPLETE --> [*]
    FAILED --> [*]
```

## Control Loop with Capability Attenuation

```mermaid
flowchart LR
    C2["Controller / C2<br/>Global view (imperfect)<br/>Task planning + constraints"]
    CAP["Capability Construction<br/>Attenuation policy (monotone: only tighten)"]
    INTENT["Task Intent Packet<br/>Intent + CapToken<br/>RouteOptions + Timeouts"]
    PLANT["Chaotic Transport Plant<br/>(MANET / DTN / Satcom)<br/>Per-node FSMs<br/>Local enforcement"]
    ENF["Local Enforcement<br/>Validate cap, enforce budgets<br/>Optional delegation: cap2 <= cap1"]
    MEASURE["Feedback Signals<br/>Crypto receipts: CR (custody), DR (delivery), ER (execution)<br/>Timeout / failure events"]
    UPDATE["Belief Update + Replan<br/>Tune RouteOptions/timeouts<br/>Tune attenuation/budgets"]

    C2 -->|mission goals / policy| CAP
    CAP -->|u_k: cap + constraints| INTENT
    INTENT --> PLANT

    PLANT --> ENF
    ENF --> PLANT

    PLANT -->|y_k: receipts + delays| MEASURE
    MEASURE --> UPDATE
    UPDATE -->|u_k+1: updated constraints + tuning| C2
```


