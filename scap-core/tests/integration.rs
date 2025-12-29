//! Integration tests for complete SCAP message flows

use scap_core::*;
use scap_core::crypto::derive_public_key;

fn operator_keypair() -> (Vec<u8>, Vec<u8>) {
    let privkey = hex::decode(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    ).unwrap();
    let pubkey = derive_public_key(&privkey).unwrap();
    (privkey, pubkey)
}

fn satellite_keypair() -> (Vec<u8>, Vec<u8>) {
    let privkey = hex::decode(
        "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    ).unwrap();
    let pubkey = derive_public_key(&privkey).unwrap();
    (privkey, pubkey)
}

/// Test complete flow: operator creates token → satellite executes → proof generated
#[test]
fn test_complete_task_flow() {
    let (operator_priv, operator_pub) = operator_keypair();
    let (satellite_priv, satellite_pub) = satellite_keypair();
    let now = 1705320000u64;

    // 1. Operator creates capability token for imaging task
    let token = CapabilityTokenBuilder::new(
        "OPERATOR-ALPHA".into(),
        "CUSTOMER-001".into(),
        "SENTINEL-2A".into(),
        "task-img-001".into(),
        vec!["cmd:imaging:msi".into()],
    )
    .valid_for(now, 86400) // Valid for 24 hours
    .with_constraints(Constraints {
        max_area_km2: Some(1000),
        geographic_bounds: Some(GeoBounds {
            lat_min: Some(40.0),
            lat_max: Some(45.0),
            lon_min: Some(-5.0),
            lon_max: Some(5.0),
            polygon: None,
        }),
        ..Default::default()
    })
    .sign(&operator_priv)
    .unwrap();

    // 2. Validate the token
    TokenValidator::new(&token)
        .at_time(now + 100)
        .with_issuer_key(&operator_pub)
        .validate()
        .unwrap();

    // 3. Encode token to CBOR for transmission
    let token_cbor = encode_capability_token(&token).unwrap();
    assert!(token_cbor.len() > 0);

    // 4. Create bound task request with payment
    let payment_preimage = sha256(b"secret-preimage");
    let payment_hash = sha256(&payment_preimage);

    let binding_preimage = compute_binding_hash(&token.payload.jti, &payment_hash);
    let binding_sig = sign_message(&satellite_priv, &binding_preimage).unwrap();

    let task_request = BoundTaskRequest {
        capability_token: token_cbor.clone(),
        payment_hash: payment_hash.to_vec(),
        payment_amount_msat: 10_000_000, // 10,000 sats
        htlc_timeout_blocks: 336,
        binding_sig,
    };

    // 5. Encode and decode task request
    let request_cbor = encode_task_request(&task_request).unwrap();
    let decoded_request = decode_task_request(&request_cbor).unwrap();
    assert_eq!(task_request, decoded_request);

    // 6. Satellite executes task and creates proof
    let output_data = b"MSI imaging data for region...";
    let output_hash = sha256(output_data);
    let execution_time = now + 3600;

    let proof_preimage = compute_proof_hash(
        &token.payload.jti,
        &payment_hash,
        &output_hash,
        execution_time,
    );
    let executor_sig = sign_message(&satellite_priv, &proof_preimage).unwrap();

    let proof = ExecutionProof {
        task_jti: token.payload.jti.clone(),
        payment_hash: payment_hash.to_vec(),
        output_hash: output_hash.to_vec(),
        execution_timestamp: execution_time,
        output_metadata: Some(OutputMetadata {
            content_type: Some("application/octet-stream".into()),
            size_bytes: Some(output_data.len() as u64),
            storage_location: Some("ipfs://QmXxx...".into()),
        }),
        executor_sig,
    };

    // 7. Encode and decode execution proof
    let proof_cbor = encode_execution_proof(&proof).unwrap();
    let decoded_proof = decode_execution_proof(&proof_cbor).unwrap();
    assert_eq!(proof, decoded_proof);

    // 8. Verify proof signature
    let recomputed_preimage = compute_proof_hash(
        &decoded_proof.task_jti,
        &decoded_proof.payment_hash,
        &decoded_proof.output_hash,
        decoded_proof.execution_timestamp,
    );
    let valid = verify_signature(&satellite_pub, &recomputed_preimage, &decoded_proof.executor_sig).unwrap();
    assert!(valid, "Execution proof signature should verify");
}

/// Test delegation chain: Operator → Satellite A → Satellite B
#[test]
fn test_delegation_chain() {
    let (operator_priv, operator_pub) = operator_keypair();
    let (sat_a_priv, sat_a_pub) = satellite_keypair();
    let (sat_b_priv, sat_b_pub) = {
        let priv_key = hex::decode(
            "1111111111111111111111111111111111111111111111111111111111111111"
        ).unwrap();
        let pub_key = derive_public_key(&priv_key).unwrap();
        (priv_key, pub_key)
    };
    let now = 1705320000u64;

    // 1. Operator creates root token for Satellite A
    let root_token = CapabilityTokenBuilder::new(
        "OPERATOR-ALPHA".into(),
        "SATELLITE-A".into(),
        "SATELLITE-A".into(), // Self-audience for relay capability
        "root-001".into(),
        vec!["relay:task:*".into(), "cmd:imaging:*".into()],
    )
    .valid_for(now, 86400 * 7) // Valid for 7 days
    .with_constraints(Constraints {
        max_hops: Some(3),
        ..Default::default()
    })
    .sign(&operator_priv)
    .unwrap();

    TokenValidator::new(&root_token)
        .at_time(now + 100)
        .with_issuer_key(&operator_pub)
        .validate()
        .unwrap();

    // 2. Satellite A delegates to Satellite B with reduced capabilities
    let delegated_token = CapabilityTokenBuilder::new(
        "SATELLITE-A".into(),
        "SATELLITE-B".into(),
        "TARGET-SAT".into(),
        "del-001".into(),
        vec!["cmd:imaging:msi".into()], // Reduced from cmd:imaging:*
    )
    .delegated_from(root_token.payload.jti.clone())
    .chain_depth(1)
    .valid_for(now, 3600) // Shorter validity
    .with_constraints(Constraints {
        max_area_km2: Some(500), // More restrictive
        ..Default::default()
    })
    .sign(&sat_a_priv)
    .unwrap();

    assert_eq!(delegated_token.header.typ, "SAT-CAP-DEL");
    assert_eq!(delegated_token.header.chn, Some(1));
    assert_eq!(delegated_token.payload.prf, Some("root-001".into()));

    // 3. Validate delegated token
    TokenValidator::new(&delegated_token)
        .at_time(now + 100)
        .with_issuer_key(&sat_a_pub)
        .validate()
        .unwrap();

    // 4. Verify capability attenuation
    // Root has "cmd:imaging:*", delegation has "cmd:imaging:msi"
    assert!(capability_matches("cmd:imaging:*", "cmd:imaging:msi"));
    assert!(!capability_matches("cmd:imaging:msi", "cmd:imaging:sar")); // Can't do SAR
}

/// Test token expiration and rejection
#[test]
fn test_token_lifecycle() {
    let (operator_priv, operator_pub) = operator_keypair();
    let now = 1705320000u64;

    let token = CapabilityTokenBuilder::new(
        "OPERATOR".into(),
        "SAT-1".into(),
        "SAT-2".into(),
        "lifecycle-001".into(),
        vec!["cmd:test".into()],
    )
    .valid_for(now, 3600) // Valid for 1 hour
    .sign(&operator_priv)
    .unwrap();

    // Valid within window
    TokenValidator::new(&token)
        .at_time(now + 1800)
        .with_issuer_key(&operator_pub)
        .validate()
        .unwrap();

    // Invalid before start
    let result = TokenValidator::new(&token)
        .at_time(now - 100)
        .validate();
    assert!(matches!(result, Err(ScapError::TokenNotYetValid)));

    // Invalid after expiration
    let result = TokenValidator::new(&token)
        .at_time(now + 7200)
        .validate();
    assert!(matches!(result, Err(ScapError::TokenExpired)));
}

/// Test capability matching patterns
#[test]
fn test_capability_authorization() {
    // Exact matches
    assert!(capability_matches("cmd:imaging:msi", "cmd:imaging:msi"));
    assert!(!capability_matches("cmd:imaging:msi", "cmd:imaging:sar"));

    // Wildcard at end
    assert!(capability_matches("cmd:imaging:*", "cmd:imaging:msi"));
    assert!(capability_matches("cmd:imaging:*", "cmd:imaging:sar"));
    assert!(!capability_matches("cmd:imaging:*", "cmd:propulsion:fire"));

    // Category wildcard
    assert!(capability_matches("cmd:*", "cmd:imaging:msi"));
    assert!(capability_matches("cmd:*", "cmd:propulsion:fire"));
    assert!(!capability_matches("cmd:*", "relay:task:forward"));

    // Prefix matching (less specific grants more specific)
    assert!(capability_matches("relay", "relay:task:forward"));
    assert!(capability_matches("relay:task", "relay:task:forward"));
}

/// Test CBOR size efficiency
#[test]
fn test_message_sizes() {
    let (operator_priv, _) = operator_keypair();
    let now = 1705320000u64;

    // Minimal token
    let minimal_token = CapabilityTokenBuilder::new(
        "OP".into(),
        "S1".into(),
        "S2".into(),
        "t1".into(),
        vec!["cmd:x".into()],
    )
    .valid_for(now, 3600)
    .sign(&operator_priv)
    .unwrap();

    let minimal_cbor = encode_capability_token(&minimal_token).unwrap();
    println!("Minimal token size: {} bytes", minimal_cbor.len());
    assert!(minimal_cbor.len() < 300, "Minimal token should be under 300 bytes");

    // Full token with constraints
    let full_token = CapabilityTokenBuilder::new(
        "OPERATOR-ALPHA-LONG-NAME".into(),
        "SATELLITE-CUSTOMER-001".into(),
        "SENTINEL-2A-NORAD-12345".into(),
        "task-imaging-request-001".into(),
        vec![
            "cmd:imaging:msi".into(),
            "cmd:imaging:sar".into(),
            "data:download:standard".into(),
        ],
    )
    .valid_for(now, 86400)
    .with_constraints(Constraints {
        max_area_km2: Some(10000),
        max_range_km: Some(500.0),
        max_hops: Some(3),
        geographic_bounds: Some(GeoBounds {
            lat_min: Some(30.0),
            lat_max: Some(60.0),
            lon_min: Some(-20.0),
            lon_max: Some(40.0),
            polygon: None,
        }),
        time_window: Some(TimeWindow {
            start: now,
            end: now + 86400,
        }),
        ..Default::default()
    })
    .sign(&operator_priv)
    .unwrap();

    let full_cbor = encode_capability_token(&full_token).unwrap();
    println!("Full token size: {} bytes", full_cbor.len());
    assert!(full_cbor.len() < 600, "Full token should be under 600 bytes");
}
