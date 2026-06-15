//! Cryptographic operations for SCAP
//!
//! Provides signing and verification using secp256k1 ECDSA.

use alloc::vec::Vec;
use sha2::{Sha256, Digest};
use k256::ecdsa::{SigningKey, VerifyingKey, Signature};
use k256::ecdsa::signature::hazmat::{PrehashSigner, PrehashVerifier};
use crate::error::ScapError;

// Pure-Rust secp256k1 (k256). No global context to allocate per call, and
// SigningKey is ZeroizeOnDrop so secret material is wiped automatically.
// Signatures are RFC 6979 deterministic and low-s normalized, byte-compatible
// with libsecp256k1 — the existing cross-implementation test vectors verify.

/// Compute SHA-256 hash of data
pub fn sha256(data: &[u8]) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hasher.finalize().into()
}

/// Sign a message with a private key.
///
/// The message is hashed with SHA-256 before signing. Returns the DER-encoded
/// ECDSA signature (RFC 6979 deterministic, low-s).
pub fn sign_message(private_key: &[u8], message: &[u8]) -> Result<Vec<u8>, ScapError> {
    let signing_key = SigningKey::from_slice(private_key)
        .map_err(|_| ScapError::InvalidPrivateKey)?;

    let msg_hash = sha256(message);
    let sig: Signature = signing_key.sign_prehash(&msg_hash)
        .map_err(|_| ScapError::InvalidSignature)?;

    Ok(sig.to_der().as_bytes().to_vec())
}

/// Verify a DER-encoded signature against a public key.
///
/// The message is hashed with SHA-256 before verification.
pub fn verify_signature(
    public_key: &[u8],
    message: &[u8],
    signature: &[u8],
) -> Result<bool, ScapError> {
    let verifying_key = VerifyingKey::from_sec1_bytes(public_key)
        .map_err(|_| ScapError::InvalidPublicKey)?;

    let sig = Signature::from_der(signature)
        .map_err(|_| ScapError::InvalidSignature)?;

    let msg_hash = sha256(message);
    Ok(verifying_key.verify_prehash(&msg_hash, &sig).is_ok())
}

/// Derive the compressed (33-byte) public key from a private key.
pub fn derive_public_key(private_key: &[u8]) -> Result<Vec<u8>, ScapError> {
    let signing_key = SigningKey::from_slice(private_key)
        .map_err(|_| ScapError::InvalidPrivateKey)?;

    let verifying_key = signing_key.verifying_key();
    Ok(verifying_key.to_encoded_point(true).as_bytes().to_vec())
}

/// Compute binding hash for payment-capability binding
///
/// binding_hash = SHA256(jti || payment_hash)
pub fn compute_binding_hash(jti: &str, payment_hash: &[u8]) -> [u8; 32] {
    let mut data = Vec::with_capacity(jti.len() + payment_hash.len());
    data.extend_from_slice(jti.as_bytes());
    data.extend_from_slice(payment_hash);
    sha256(&data)
}

/// Compute proof hash for execution proof
///
/// proof_hash = SHA256(task_jti || payment_hash || output_hash || timestamp)
pub fn compute_proof_hash(
    task_jti: &str,
    payment_hash: &[u8],
    output_hash: &[u8],
    timestamp: u64,
) -> [u8; 32] {
    let mut data = Vec::with_capacity(task_jti.len() + 32 + 32 + 8);
    data.extend_from_slice(task_jti.as_bytes());
    data.extend_from_slice(payment_hash);
    data.extend_from_slice(output_hash);
    data.extend_from_slice(&timestamp.to_be_bytes());
    sha256(&data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sha256() {
        let hash = sha256(b"test");
        assert_eq!(hash.len(), 32);
        assert_eq!(
            hex::encode(hash),
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        );
    }

    #[test]
    fn test_sign_and_verify() {
        let privkey = hex::decode(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ).unwrap();

        let pubkey = derive_public_key(&privkey).unwrap();
        let message = b"test message";

        let sig = sign_message(&privkey, message).unwrap();
        let valid = verify_signature(&pubkey, message, &sig).unwrap();

        assert!(valid);
    }

    #[test]
    fn test_verify_wrong_message() {
        let privkey = hex::decode(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ).unwrap();

        let pubkey = derive_public_key(&privkey).unwrap();
        let message = b"test message";
        let wrong_message = b"wrong message";

        let sig = sign_message(&privkey, message).unwrap();
        let valid = verify_signature(&pubkey, wrong_message, &sig).unwrap();

        assert!(!valid);
    }

    #[test]
    fn test_binding_hash() {
        let jti = "test-imaging-001";
        let payment_hash = hex::decode(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        ).unwrap();

        let hash = compute_binding_hash(jti, &payment_hash);
        assert_eq!(hash.len(), 32);
    }

    #[test]
    fn test_proof_hash() {
        let task_jti = "test-imaging-001";
        let payment_hash = hex::decode(
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        ).unwrap();
        let output_hash = hex::decode(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ).unwrap();
        let timestamp = 1705321000u64;

        let hash = compute_proof_hash(task_jti, &payment_hash, &output_hash, timestamp);
        assert_eq!(hash.len(), 32);
    }
}
