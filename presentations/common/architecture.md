## Architecture

### Two Layers, Two Timescales

**Authorization Layer (Space)**
- Satellites verify capability tokens
- Tasks route via ISL (store-and-forward)
- Latency: minutes to hours acceptable
- Intermittent connectivity OK

**Settlement Layer (Ground)**
- Operators coordinate via ground infrastructure
- Always-online, standard internet connectivity
- Can integrate with payment systems for commercial use

**The key separation:**
- Task routing: Satellites, via ISL
- Coordination: Operators, via ground

Satellites never need persistent ground contact. Authorization happens autonomously in space.
