# SCRAP Message Schemas

CDDL (Concise Data Definition Language, RFC 8610) schemas for SCRAP protocol messages.

## Files

| File | Description |
|------|-------------|
| `scap.cddl` | Complete CDDL schema for all message types |
| `validate_examples.py` | Generate and validate CBOR examples |
| `examples/` | Generated CBOR test messages |

## Message Types

### Core Protocol

| Type | Description | Schema Reference |
|------|-------------|------------------|
| `capability-token` | Authorization token for task execution | §2 |
| `bound-task-request` | Task + payment binding | §3 |
| `execution-proof` | Proof of completed task | §4 |
| `dispute-message` | Customer dispute with evidence | §5 |
| `task-response` | Accepted/Rejected/Completed/Failed | §6 |

### Transport

| Type | Description |
|------|-------------|
| `isl-scap-message` | ISL encapsulation wrapper |
| `lightning-wrapper` | BOLT message encapsulation |
| `heartbeat` | Keepalive with channel state |

### Auction (Optional)

| Type | Description |
|------|-------------|
| `cbba-bid` | CBBA auction bid |
| `cbba-assignment` | Task assignment result |

## Usage

### Generate Examples

```bash
# Using project venv
../demo/.venv/bin/python validate_examples.py

# View generated files
ls examples/
```

### Validate Against Schema

Requires the `cddl` tool:

```bash
# Install cddl (Rust)
cargo install cddl

# Validate all examples
python validate_examples.py --validate

# Validate single file
cddl scap.cddl validate examples/capability_token.cbor
```

### Code Generation

Generate Rust types from CDDL:

```bash
# Install cddl-codegen
cargo install cddl-codegen

# Generate Rust
cddl-codegen --input scap.cddl --output ../src/types.rs
```

## Schema Design Notes

### Binary Sizes

All messages use CBOR encoding for compact binary representation:

| Message | Typical Size |
|---------|--------------|
| Capability token | 200-400 bytes |
| Bound task request | 150-250 bytes |
| Execution proof | 150-200 bytes |
| ISL wrapper overhead | ~50 bytes |

### Extensibility

Constraints and metadata maps use `* tstr => any` to allow domain-specific extensions without schema changes.

### Signature Format

All signatures use DER-encoded ECDSA with secp256k1 (70-73 bytes typical).
