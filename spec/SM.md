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

    %% ========================
    %% EXECUTOR PATH
    %% ========================
    EXECUTING --> DELIVERED: ER(DONE)
    EXECUTING --> DELIVERED: ER(ALREADY_DONE)
    EXECUTING --> DELIVERED: ER(IN_PROGRESS)
    EXECUTING --> DELIVERED: ER(REFUSED)

    note right of EXECUTING
      Idempotent execution
      If TaskID already seen:
      return ER(ALREADY_DONE / IN_PROGRESS)
    end note

    %% ========================
    %% RELAY / FORWARD PATH
    %% ========================
    IN_CUSTODY --> FORWARDING: select_next_hop
    FORWARDING --> WAIT_DOWNSTREAM: TASK_FORWARD sent

    WAIT_DOWNSTREAM --> WAIT_TERMINAL: CUSTODY_ACCEPT
    WAIT_DOWNSTREAM --> IN_CUSTODY: hop timeout (fallback)

    WAIT_TERMINAL --> DELIVERED: ER or DR received
    WAIT_TERMINAL --> IN_CUSTODY: terminal timeout (fallback)

    note right of IN_CUSTODY
      Holds custody
      Enforces retries, budgets,
      and capability attenuation
    end note

    %% ========================
    %% ACK RETURN PATH
    %% ========================
    DELIVERED --> ACKING: begin ACK return
    ACKING --> ACKING: ACK timeout (fallback)
    ACKING --> COMPLETE: ACK accepted

    COMPLETE --> [*]
    FAILED --> [*]


## Control Loop with Capability Attenuation

flowchart LR
    %%========================
    %% SCRAP / SISL CONTROL LOOP (with Capability Attenuation)
    %%========================

    C2[Controller / C2\nGlobal view (imperfect)\nTask planning + constraints]
    CAP[Capability Construction\n+ Attenuation Policy\n(monotone: only tighten)]
    INTENT[Task Intent Packet\nIntent + CapToken\nRouteOptions + Timeouts]
    PLANT[Chaotic Transport Plant\n(MANET / DTN / Satcom)\n+ Per-Node FSMs\n+ Local enforcement]
    ENF[Local Enforcement\nValidate cap, enforce budgets\nOptional delegation => cap' ⪯ cap]
    MEASURE[Feedback Signals\nCryptographic Receipts:\nCR (custody), DR (delivery), ER (execution)\n+ Timeout / failure events]
    UPDATE[Belief Update + Replan\nAdjust RouteOptions/timeouts\nAdjust attenuation/budgets]

    C2 -->|mission goals / policy| CAP
    CAP -->|u_k: cap + constraints| INTENT
    INTENT --> PLANT

    PLANT --> ENF
    ENF --> PLANT

    PLANT -->|y_k: receipts & delays| MEASURE
    MEASURE --> UPDATE
    UPDATE -->|u_{k+1}: updated constraints\nand route/timeout tuning| C2

