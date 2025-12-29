//! Error types for SCAP operations

use alloc::string::String;
use core::fmt;

/// Errors that can occur during SCAP operations
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ScapError {
    /// Invalid signature
    InvalidSignature,
    /// Signature verification failed
    VerificationFailed,
    /// Invalid public key format
    InvalidPublicKey,
    /// Invalid private key format
    InvalidPrivateKey,
    /// CBOR encoding error
    CborEncode(String),
    /// CBOR decoding error
    CborDecode(String),
    /// Token has expired
    TokenExpired,
    /// Token not yet valid (issued in future)
    TokenNotYetValid,
    /// Invalid capability format
    InvalidCapability(String),
    /// Missing required field
    MissingField(String),
    /// Constraint violation
    ConstraintViolation(String),
    /// Invalid hash length
    InvalidHashLength { expected: usize, got: usize },
}

impl fmt::Display for ScapError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidSignature => write!(f, "invalid signature format"),
            Self::VerificationFailed => write!(f, "signature verification failed"),
            Self::InvalidPublicKey => write!(f, "invalid public key format"),
            Self::InvalidPrivateKey => write!(f, "invalid private key format"),
            Self::CborEncode(msg) => write!(f, "CBOR encoding error: {}", msg),
            Self::CborDecode(msg) => write!(f, "CBOR decoding error: {}", msg),
            Self::TokenExpired => write!(f, "token has expired"),
            Self::TokenNotYetValid => write!(f, "token not yet valid"),
            Self::InvalidCapability(cap) => write!(f, "invalid capability: {}", cap),
            Self::MissingField(field) => write!(f, "missing required field: {}", field),
            Self::ConstraintViolation(msg) => write!(f, "constraint violation: {}", msg),
            Self::InvalidHashLength { expected, got } => {
                write!(f, "invalid hash length: expected {}, got {}", expected, got)
            }
        }
    }
}

#[cfg(feature = "std")]
impl std::error::Error for ScapError {}
