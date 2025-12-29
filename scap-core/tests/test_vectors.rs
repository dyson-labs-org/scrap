//! Cross-validation against Python test vectors
//!
//! These tests verify that the Rust implementation produces identical
//! results to the Python reference implementation.

use scap_core::{sha256, sign_message, verify_signature, derive_public_key};
use scap_core::{compute_binding_hash, compute_proof_hash};
use serde::Deserialize;
use std::fs;
use std::path::Path;

#[derive(Deserialize)]
struct TestVectors {
    version: String,
    capability_token: CapabilityTokenVector,
    execution_proof: ExecutionProofVector,
    payment_binding: PaymentBindingVector,
    htlc_timeouts: Vec<HtlcTimeoutVector>,
}

#[derive(Deserialize)]
struct CapabilityTokenVector {
    keys: Keys,
    input: CapTokenInput,
    computed: CapTokenComputed,
}

#[derive(Deserialize)]
struct Keys {
    operator: Option<KeyPair>,
    executor: Option<KeyPair>,
    requester: Option<KeyPair>,
}

#[derive(Deserialize)]
struct KeyPair {
    private_key_hex: String,
    public_key_hex: String,
}

#[derive(Deserialize)]
struct CapTokenInput {
    header: serde_json::Value,
    payload: serde_json::Value,
}

#[derive(Deserialize)]
struct CapTokenComputed {
    header_cbor_hex: String,
    payload_cbor_hex: String,
    signing_input_hash_hex: String,
    signature_der_hex: String,
}

#[derive(Deserialize)]
struct ExecutionProofVector {
    keys: Keys,
    input: ExecutionProofInput,
    computed: ExecutionProofComputed,
}

#[derive(Deserialize)]
struct ExecutionProofInput {
    task_jti: String,
    payment_hash_hex: String,
    output_hash_hex: String,
    execution_timestamp: u64,
}

#[derive(Deserialize)]
struct ExecutionProofComputed {
    proof_preimage_hex: String,
    proof_hash_hex: String,
    signature_der_hex: String,
}

#[derive(Deserialize)]
struct PaymentBindingVector {
    keys: Keys,
    input: PaymentBindingInput,
    computed: PaymentBindingComputed,
}

#[derive(Deserialize)]
struct PaymentBindingInput {
    task_jti: String,
    payment_hash_hex: String,
    payment_amount_msat: u64,
    htlc_timeout_blocks: u32,
}

#[derive(Deserialize)]
struct PaymentBindingComputed {
    binding_preimage_hex: String,
    binding_hash_hex: String,
    binding_signature_der_hex: String,
}

#[derive(Deserialize)]
struct HtlcTimeoutVector {
    hops: u32,
    input: HtlcTimeoutInput,
    computed: HtlcTimeoutComputed,
}

#[derive(Deserialize)]
struct HtlcTimeoutInput {
    dispute_window_blocks: u32,
    max_contact_gap_blocks: u32,
    margin_per_hop_blocks: u32,
}

#[derive(Deserialize)]
struct HtlcTimeoutComputed {
    timeout_chain_blocks: Vec<u32>,
    customer_timeout_blocks: u32,
    customer_timeout_hours: f64,
    final_timeout_blocks: u32,
}

fn load_test_vectors() -> TestVectors {
    let paths = [
        "../test_vectors_computed.json",
        "../../test_vectors_computed.json",
    ];

    for path in &paths {
        if Path::new(path).exists() {
            let content = fs::read_to_string(path)
                .expect("Failed to read test vectors");
            return serde_json::from_str(&content)
                .expect("Failed to parse test vectors");
        }
    }

    panic!("Test vectors file not found");
}

fn strip_0x(s: &str) -> &str {
    s.strip_prefix("0x").unwrap_or(s)
}

#[test]
fn test_public_key_derivation() {
    let vectors = load_test_vectors();
    let keys = vectors.capability_token.keys.operator.unwrap();

    let privkey = hex::decode(strip_0x(&keys.private_key_hex)).unwrap();
    let expected_pubkey = hex::decode(strip_0x(&keys.public_key_hex)).unwrap();

    let derived_pubkey = derive_public_key(&privkey).unwrap();

    assert_eq!(derived_pubkey, expected_pubkey, "Public key derivation mismatch");
}

#[test]
fn test_capability_token_signing_input_hash() {
    let vectors = load_test_vectors();
    let computed = &vectors.capability_token.computed;

    let header_cbor = hex::decode(&computed.header_cbor_hex).unwrap();
    let payload_cbor = hex::decode(&computed.payload_cbor_hex).unwrap();

    let mut signing_input = Vec::new();
    signing_input.extend_from_slice(&header_cbor);
    signing_input.extend_from_slice(&payload_cbor);

    let hash = sha256(&signing_input);
    let expected_hash = hex::decode(&computed.signing_input_hash_hex).unwrap();

    assert_eq!(hash.to_vec(), expected_hash, "Signing input hash mismatch");
}

#[test]
fn test_capability_token_signature_verification() {
    let vectors = load_test_vectors();
    let keys = vectors.capability_token.keys.operator.unwrap();
    let computed = &vectors.capability_token.computed;

    let pubkey = hex::decode(strip_0x(&keys.public_key_hex)).unwrap();
    let header_cbor = hex::decode(&computed.header_cbor_hex).unwrap();
    let payload_cbor = hex::decode(&computed.payload_cbor_hex).unwrap();
    let signature = hex::decode(&computed.signature_der_hex).unwrap();

    let mut signing_input = Vec::new();
    signing_input.extend_from_slice(&header_cbor);
    signing_input.extend_from_slice(&payload_cbor);

    let valid = verify_signature(&pubkey, &signing_input, &signature).unwrap();
    assert!(valid, "Capability token signature verification failed");
}

#[test]
fn test_execution_proof_preimage() {
    let vectors = load_test_vectors();
    let input = &vectors.execution_proof.input;
    let computed = &vectors.execution_proof.computed;

    let payment_hash = hex::decode(strip_0x(&input.payment_hash_hex)).unwrap();
    let output_hash = hex::decode(strip_0x(&input.output_hash_hex)).unwrap();

    let mut preimage = Vec::new();
    preimage.extend_from_slice(input.task_jti.as_bytes());
    preimage.extend_from_slice(&payment_hash);
    preimage.extend_from_slice(&output_hash);
    preimage.extend_from_slice(&input.execution_timestamp.to_be_bytes());

    let expected_preimage = hex::decode(&computed.proof_preimage_hex).unwrap();
    assert_eq!(preimage, expected_preimage, "Execution proof preimage mismatch");

    let hash = sha256(&preimage);
    let expected_hash = hex::decode(&computed.proof_hash_hex).unwrap();
    assert_eq!(hash.to_vec(), expected_hash, "Execution proof hash mismatch");
}

#[test]
fn test_execution_proof_signature_verification() {
    let vectors = load_test_vectors();
    let keys = vectors.execution_proof.keys.executor.unwrap();
    let computed = &vectors.execution_proof.computed;

    let pubkey = hex::decode(strip_0x(&keys.public_key_hex)).unwrap();
    let preimage = hex::decode(&computed.proof_preimage_hex).unwrap();
    let signature = hex::decode(&computed.signature_der_hex).unwrap();

    let valid = verify_signature(&pubkey, &preimage, &signature).unwrap();
    assert!(valid, "Execution proof signature verification failed");
}

#[test]
fn test_payment_binding_hash() {
    let vectors = load_test_vectors();
    let input = &vectors.payment_binding.input;
    let computed = &vectors.payment_binding.computed;

    let payment_hash = hex::decode(strip_0x(&input.payment_hash_hex)).unwrap();

    let binding_hash = compute_binding_hash(&input.task_jti, &payment_hash);
    let expected_hash = hex::decode(&computed.binding_hash_hex).unwrap();

    assert_eq!(binding_hash.to_vec(), expected_hash, "Binding hash mismatch");
}

#[test]
fn test_payment_binding_signature_verification() {
    let vectors = load_test_vectors();
    let keys = vectors.payment_binding.keys.requester.unwrap();
    let computed = &vectors.payment_binding.computed;

    let pubkey = hex::decode(strip_0x(&keys.public_key_hex)).unwrap();
    let preimage = hex::decode(&computed.binding_preimage_hex).unwrap();
    let signature = hex::decode(&computed.binding_signature_der_hex).unwrap();

    let valid = verify_signature(&pubkey, &preimage, &signature).unwrap();
    assert!(valid, "Payment binding signature verification failed");
}

#[test]
fn test_htlc_timeout_calculation() {
    let vectors = load_test_vectors();

    for case in &vectors.htlc_timeouts {
        let input = &case.input;
        let computed = &case.computed;

        let final_timeout = input.dispute_window_blocks
            + input.max_contact_gap_blocks
            + input.margin_per_hop_blocks;

        let mut timeouts = vec![final_timeout];
        for _ in 1..case.hops {
            timeouts.insert(0, timeouts[0] + input.margin_per_hop_blocks);
        }

        assert_eq!(
            timeouts, computed.timeout_chain_blocks,
            "HTLC timeout chain mismatch for {} hops", case.hops
        );

        let customer_hours = (timeouts[0] as f64 * 10.0 / 60.0 * 10.0).round() / 10.0;
        assert_eq!(
            customer_hours, computed.customer_timeout_hours,
            "Customer timeout hours mismatch for {} hops", case.hops
        );
    }
}

#[test]
fn test_cross_implementation_signing() {
    let vectors = load_test_vectors();
    let keys = vectors.capability_token.keys.operator.unwrap();
    let computed = &vectors.capability_token.computed;

    let privkey = hex::decode(strip_0x(&keys.private_key_hex)).unwrap();
    let header_cbor = hex::decode(&computed.header_cbor_hex).unwrap();
    let payload_cbor = hex::decode(&computed.payload_cbor_hex).unwrap();

    let mut signing_input = Vec::new();
    signing_input.extend_from_slice(&header_cbor);
    signing_input.extend_from_slice(&payload_cbor);

    let rust_sig = sign_message(&privkey, &signing_input).unwrap();

    let pubkey = hex::decode(strip_0x(&keys.public_key_hex)).unwrap();
    let valid = verify_signature(&pubkey, &signing_input, &rust_sig).unwrap();
    assert!(valid, "Rust-generated signature should verify");

    let python_sig = hex::decode(&computed.signature_der_hex).unwrap();
    let python_valid = verify_signature(&pubkey, &signing_input, &python_sig).unwrap();
    assert!(python_valid, "Python-generated signature should verify");
}
