# Distributed Task Allocation (CBBA) - Future Extension

## Status: Future / Illustrative

This document describes distributed auction mechanisms (CBBA) for constellation-wide task allocation. This is an **advanced capability** not part of the core SCRAP specification.

**Initial SCRAP deployments use pre-negotiated capability tokens without real-time auction.**

The auction mechanism documented here is illustrative of a potential future extension. It requires:
- Satellites with sufficient compute for bid optimization
- Reliable ISL connectivity for bid propagation
- Convergence time compatible with orbital dynamics

---

## 1. Motivation

For large-scale disaster response or multi-constellation coordination, dynamic task allocation may outperform pre-negotiated tokens:

| Approach | Pros | Cons |
|----------|------|------|
| **Pre-negotiated tokens** | Simple, deterministic, no ISL overhead | Requires advance planning |
| **Distributed auction** | Optimal allocation, handles uncertainty | Complex, requires convergence time |

---

## 2. Auction-Based Task Distribution

For constellation-wide task distribution, satellites use the Consensus-Based Bundle Algorithm:

```
+-----------------------------------------------------------------------------+
|                    CBBA DISTRIBUTED AUCTION                                  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  PHASE 1: BUNDLE BUILDING (Local)                                           |
|  -------------------------------                                            |
|  Each satellite greedily builds a task bundle:                              |
|                                                                             |
|    SAT-1: "Task A costs me 10 units, Task C costs 15"                       |
|    SAT-2: "Task A costs me 8 units, Task B costs 12"                        |
|    SAT-3: "Task B costs me 6 units, Task C costs 20"                        |
|                                                                             |
|                                                                             |
|  PHASE 2: CONSENSUS (Distributed)                                           |
|  --------------------------------                                           |
|  Satellites exchange bids with ISL neighbors:                               |
|                                                                             |
|    SAT-1 -> SAT-2: "I bid 10 for Task A"                                     |
|    SAT-2 -> SAT-1: "I bid 8 for Task A"  <- Lower cost wins                   |
|                                                                             |
|    SAT-1: "OK, you take A. I'll rebid on B or C."                           |
|                                                                             |
|                                                                             |
|  ITERATION: Repeat until no conflicts remain                                |
|                                                                             |
|                                                                             |
|  Properties:                                                                |
|  * Converges to conflict-free assignment                                    |
|  * Polynomial-time algorithm                                                |
|  * Tolerates partial communication graphs                                   |
|  * Decentralized execution with local information only                      |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## 3. Auction Bid Structure

```
+----------------------------------------------------------------+
|                    CROSS-OPERATOR AUCTION BID                   |
+----------------------------------------------------------------+
|  Bid Header                                                    |
|  +-- bidder_id: "ICEYE-X14-51070"                             |
|  +-- task_id: "CHARTER-2025-JAP-IMG-001"                      |
|  +-- bid_value: 8.5              # Lower is better            |
|  +-- timestamp: 1705312800                                     |
+----------------------------------------------------------------+
|  Authorization                                                 |
|  +-- capability_token: <SAT-CAP>                              |
|  |     +-- cap: ["task:bid:imaging", "task:execute:imaging"]  |
|  +-- bidder_signature: ECDSA(...)                             |
+----------------------------------------------------------------+
|  Cost Breakdown                                                |
|  +-- fuel_kg: 0.02                                            |
|  +-- time_sec: 45                                             |
|  +-- opportunity_cost: 3.2                                    |
|  +-- capability_match: 0.95                                   |
+----------------------------------------------------------------+
|  Execution Details                                             |
|  +-- earliest_execution: "2025-01-15T07:30:00Z"              |
|  +-- data_latency_hours: 1.5                                  |
|  +-- coverage_km2: 30000                                       |
+----------------------------------------------------------------+
```

---

## 4. Bid Value Semantics

The bid value encodes **cost to execute**, not willingness to pay:

```python
def compute_bid(satellite: Satellite, task: Task) -> float:
    """Lower bid = better suited to execute task"""

    # Fuel cost to slew and maneuver
    fuel_cost = estimate_fuel(satellite.position, task.target)

    # Time until satellite can begin
    time_cost = compute_access_window(satellite.orbit, task.target)

    # Opportunity cost (other tasks displaced)
    opportunity_cost = evaluate_queue_impact(satellite.task_queue, task)

    # Capability mismatch penalty
    capability_penalty = 1.0 / sensor_match(satellite.sensors, task.requirements)

    return fuel_cost + time_cost + opportunity_cost + capability_penalty
```

---

## 5. Integration with SCRAP

When auction is used, it **precedes** the standard SCRAP flow:

```
1. Customer broadcasts task request (via Starlink mesh or ground)
2. Satellites compute bids and propagate via ISL
3. CBBA converges to winner selection (~5-30 minutes)
4. Winner's operator issues capability token to customer
5. Standard SCRAP flow proceeds (token → task → payment)
```

**Auction output**: The auction determines WHO executes. SCRAP handles HOW (authorization, payment).

---

## 6. References

- Choi et al., "Consensus-Based Decentralized Auctions for Robust Task Allocation" (MIT)
- CBBA: Consensus-Based Bundle Algorithm for multi-robot task allocation
- See illustrative auction scenarios:
  - [02: Wildfire Hyperspectral](user_stories/02_wildfire_hyperspectral.md)
  - [06: Methane Detection](user_stories/06_methane_auction.md)
  - [11: Disaster Response](user_stories/11_disaster_response_multi_constellation.md)

---

## 7. Future Work

If auction mechanisms are formalized:
- Define CBBA message formats in CDDL
- Specify convergence guarantees and timeout handling
- Address Sybil resistance (fake bids from malicious actors)
- Integrate with SCRAP capability token issuance
