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

    %%========================
    %% SCRAP/SISL TASK FSM (per-node, per TaskID)
    %% Annotated with timers + variables
    %%========================

    [*] --> NONE

    NONE --> RECEIVED: TASK_OFFER(TaskID, Intent, Policy, RoutePlan)

    state RECEIVED {
        [*] --> VALIDATING
        VALIDATING: start T_validate
        VALIDATING --> [*]: validate_ok
        VALIDATING --> [*]: validate_fail
    }

    RECEIVED --> FAILED: validate_fail\n(send CUSTODY_REFUSE optional)

    RECEIVED --> VALIDATED: validate_ok\n(set role, init vars)

    %% Vars initialized at VALIDATED:
    %% D_abs: absolute deadline (or remaining budget B_rem)
    %% k_max: max concurrent copies (multi-copy escalation cap)
    %% RoutePlan: ordered list of options
    %% opt_idx: current option index
    %% cand_set: candidate next-hops for current option (IDs or capability-class)
    %% retries[opt_idx]: retries left for option
    %% T_offer(opt_idx): max wait for downstream custody accept for this option
    %% T_term(opt_idx): max wait for terminal receipt after custody accepted
    %% T_ack(opt_idx): max wait for upstream ACK progress/accept
    %% mode: single-copy or multi-copy (may change near deadline)
    %% status: {NEW, IN_PROGRESS, DONE, ALREADY_DONE, REFUSED}

    VALIDATED --> EXECUTING: role==EXECUTOR\n(start T_exec if needed)
    VALIDATED --> IN_CUSTODY: role==RELAY\n(emit CUSTODY_ACCEPT upstream)\n(start T_offer for selected option)

    %%========================
    %% EXECUTOR PATH
    %%========================
    EXECUTING: enforce idempotency cache\nif seen(TaskID) => return ER(ALREADY_DONE/IN_PROGRESS)
    EXECUTING --> DELIVERED: ER(DONE)\n(store ER; stop T_exec)
    EXECUTING --> DELIVERED: ER(ALREADY_DONE)
    EXECUTING --> DELIVERED: ER(IN_PROGRESS)  %% optional early receipt
    EXECUTING --> DELIVERED: ER(REFUSED)

    %%========================
    %% RELAY / FORWARD PATH
    %%========================
    IN_CUSTODY: choose option opt_idx\ncand_set = candidates(opt_idx)\nmode may be single/multi\nstart T_offer(opt_idx)

    IN_CUSTODY --> FORWARDING: select_next_hop(j)\n(or select K hops if mode=multi)\nattach hop_budget / deadlines
    FORWARDING --> WAIT_DOWNSTREAM: send TASK_FORWARD to j\nstart T_downstream_accept(j)=T_offer(opt_idx)

    WAIT_DOWNSTREAM: awaiting CUSTODY_ACCEPT from j

    WAIT_DOWNSTREAM --> WAIT_TERMINAL: CUSTODY_ACCEPT(from=j)\nrecord CR_j\nstop T_downstream_accept(j)\nstart T_terminal=T_term(opt_idx)

    %% Fallback trigger #1: downstream didn't accept custody in time
    WAIT_DOWNSTREAM --> IN_CUSTODY: T_downstream_accept(j) expires\nmark j failed\nretries[opt_idx]--\n(if retries==0 => opt_idx++)\nrestart T_offer(opt_idx)

    %% Terminal receipt comes back (ER/DR) or cached by idempotency
    WAIT_TERMINAL: have downstream custody\nawait terminal receipt ER/DR\nstart/continue T_terminal

    WAIT_TERMINAL --> DELIVERED: ER/DR received\nvalidate signature\nstop T_terminal\ncancel outstanding forwards

    %% Fallback trigger #2: terminal receipt didn't return in time
    WAIT_TERMINAL --> IN_CUSTODY: T_terminal expires\n(escalate if near deadline)\nmaybe switch mode=multi\nopt_idx++ or widen cand_set\nrestart T_offer(opt_idx)

    %% Global deadline / budget exhaustion (hard stop)
    VALIDATED --> FAILED: now > D_abs (or B_rem<=0)
    IN_CUSTODY --> FAILED: now > D_abs (or B_rem<=0)
    FORWARDING --> FAILED: now > D_abs (or B_rem<=0)
    WAIT_DOWNSTREAM --> FAILED: now > D_abs (or B_rem<=0)
    WAIT_TERMINAL --> FAILED: now > D_abs (or B_rem<=0)
    EXECUTING --> FAILED: now > D_abs (or B_rem<=0)

    %%========================
    %% ACK RETURN PATH
    %%========================
    DELIVERED: absorbing state for forward retries\nhave ReceiptBundle (ER/DR/Hash)\nprepare return path

    DELIVERED --> ACKING: begin_ack_return\nselect upstream candidates\nstart T_ack (per option or per hop)

    ACKING: send ACK_FORWARD upstream\n(optional: require custody accept for ACK)
    ACKING --> ACKING: T_ack expires\ntry alternate upstream hop\n(opt_idx++ or widen upstream cand_set)\nrestart T_ack
    ACKING --> COMPLETE: ACK accepted upstream\n(or best-effort if no accept required)

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

