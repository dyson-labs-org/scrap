## Business Model

### The Marketplace for Satellite Services

**What Dyson Labs operates:**

1. **Task Marketplace**
   - Operators list available services (imaging, compute, downlink, relay)
   - Customers browse and request tasks
   - We match requests to available capacity

2. **Routing Service**
   - Create optimal route through satellite network
   - Handle multi-hop task chains
   - Manage capability token delegation

3. **Payment Processing**
   - Accept Lightning payments from customers
   - Create on-chain PTLCs for operators
   - Operators claim payment independently after task completion

**Revenue Model:**

| Source | Description |
|--------|-------------|
| Listing fees | Operators pay to list services |
| Transaction fees | Percentage of each task payment |
| Liquidity services | Lightning node operation |
