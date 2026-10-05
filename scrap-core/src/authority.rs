//! Strict online authority for an operation bound to an immutable application grant.
//!
//! This profile deliberately accepts root grants only. Current revocation, resource
//! scope and usage are checked by the application against the signed grant digest.

use crate::{decode_capability_token, verify_signature, CapabilityToken, ScrapError};
use alloc::{
    string::{String, ToString},
    vec::Vec,
};
use serde::Deserialize;

/// Expected authority is supplied by trusted application state, never by token claims.
pub struct OperationAuthority<'a> {
    pub issuer: &'a str,
    pub subject: &'a str,
    pub audience: &'a str,
    pub capability: &'a str,
    pub grant_digest: &'a str,
    pub now: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Wire {
    protected: Vec<u8>,
    signature: Vec<u8>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Header {
    alg: String,
    typ: String,
    enc: Option<String>,
    chn: Option<u32>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Payload {
    iss: String,
    sub: String,
    aud: String,
    iat: u64,
    exp: u64,
    jti: String,
    cap: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Protected {
    header: Header,
    payload: Payload,
}

fn decode_exact<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, ScrapError> {
    let mut input = bytes;
    let value = ciborium::de::from_reader(&mut input)
        .map_err(|_| ScrapError::CborDecode("invalid authority encoding".to_string()))?;
    if !input.is_empty() {
        return Err(ScrapError::CborDecode(
            "trailing authority bytes".to_string(),
        ));
    }
    Ok(value)
}

/// Verify exact signed bytes and every mandatory identity for one online operation.
///
/// The 64-character JTI is the lowercase SHA-256 digest of the application's
/// immutable grant. The caller must also check that grant's current authorization
/// and budget. No delegation, wildcard capability or unknown constraint is accepted.
pub fn verify_operation(
    bytes: &[u8],
    issuer_key: &[u8],
    expected: &OperationAuthority<'_>,
) -> Result<CapabilityToken, ScrapError> {
    if bytes.len() > 16_384 || bytes.is_empty() || issuer_key.len() != 33 {
        return Err(ScrapError::VerificationFailed);
    }
    let wire: Wire = decode_exact(bytes)?;
    if !verify_signature(issuer_key, &wire.protected, &wire.signature)? {
        return Err(ScrapError::VerificationFailed);
    }
    let content: Protected = decode_exact(&wire.protected)?;
    let p = content.payload;
    if content.header.alg != "ES256K"
        || content.header.typ != "SAT-CAP"
        || content.header.enc.as_deref().unwrap_or("CBOR") != "CBOR"
        || content.header.chn.unwrap_or(0) != 0
        || p.iss != expected.issuer
        || p.sub != expected.subject
        || p.aud != expected.audience
        || p.jti != expected.grant_digest
        || p.jti.len() != 64
        || !p
            .jti
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
        || p.cap.len() != 1
        || p.cap[0] != expected.capability
        || p.cap[0].contains('*')
        || expected.issuer.is_empty()
        || expected.subject.is_empty()
        || expected.audience.is_empty()
    {
        return Err(ScrapError::VerificationFailed);
    }
    if p.iat >= p.exp || expected.now < p.iat {
        return Err(ScrapError::TokenNotYetValid);
    }
    if expected.now >= p.exp {
        return Err(ScrapError::TokenExpired);
    }
    crate::validate_capability(expected.capability)?;
    decode_capability_token(bytes)
}
