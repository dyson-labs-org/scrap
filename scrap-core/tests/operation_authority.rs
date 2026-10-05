//! Root grant verification must never substitute signature validity for authority.
use scrap_core::authority::{verify_operation, OperationAuthority};
use scrap_core::{derive_public_key, encode_capability_token, CapabilityTokenBuilder, Constraints};

fn expected<'a>(digest: &'a str) -> OperationAuthority<'a> {
    OperationAuthority {
        issuer: "marketplace",
        subject: "account:one",
        audience: "observation-worker:v1",
        capability: "data:observations:prepare",
        grant_digest: digest,
        now: 100,
    }
}

#[test]
fn strict_root_identity_and_expiry() {
    let key = [7u8; 32];
    let public = derive_public_key(&key).unwrap();
    let digest = "a".repeat(64);
    let token = CapabilityTokenBuilder::new(
        "marketplace".into(),
        "account:one".into(),
        "observation-worker:v1".into(),
        digest.clone(),
        vec!["data:observations:prepare".into()],
    )
    .issued_at(90)
    .expires_at(110)
    .sign(&key)
    .unwrap();
    let wire = encode_capability_token(&token).unwrap();
    assert!(verify_operation(&wire, &public, &expected(&digest)).is_ok());
    for field in [
        "issuer",
        "subject",
        "audience",
        "capability",
        "digest",
        "expiry",
    ] {
        let mut e = expected(&digest);
        match field {
            "issuer" => e.issuer = "other",
            "subject" => e.subject = "account:other",
            "audience" => e.audience = "different-worker",
            "capability" => e.capability = "data:observations:retrieve",
            "digest" => e.grant_digest = "bad",
            _ => e.now = 110,
        }
        assert!(verify_operation(&wire, &public, &e).is_err(), "{field}");
    }
    let mut trailing = wire.clone();
    trailing.push(0);
    assert!(verify_operation(&trailing, &public, &expected(&digest)).is_err());
    assert!(verify_operation(
        &wire,
        &derive_public_key(&[8; 32]).unwrap(),
        &expected(&digest)
    )
    .is_err());
}

#[test]
fn rejects_delegation_constraints_and_wildcards() {
    let key = [7u8; 32];
    let public = derive_public_key(&key).unwrap();
    let digest = "a".repeat(64);
    for case in ["delegated", "constraint", "wildcard"] {
        let mut builder = CapabilityTokenBuilder::new(
            "marketplace".into(),
            "account:one".into(),
            "observation-worker:v1".into(),
            digest.clone(),
            vec![if case == "wildcard" {
                "data:*"
            } else {
                "data:observations:prepare"
            }
            .into()],
        )
        .issued_at(90)
        .expires_at(110);
        if case == "delegated" {
            builder = builder.delegated_from("parent".into()).chain_depth(1);
        }
        if case == "constraint" {
            builder = builder.with_constraints(Constraints {
                max_hops: Some(2),
                ..Default::default()
            });
        }
        let wire = encode_capability_token(&builder.sign(&key).unwrap()).unwrap();
        assert!(
            verify_operation(&wire, &public, &expected(&digest)).is_err(),
            "{case}"
        );
    }
}
