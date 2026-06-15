//! SCRAP (Secure Capabilities and Routed Authorization Protocol) Protocol
//!
//! Core library for SCRAP message types, signing, and verification.
//!
//! # Features
//!
//! - `std` (default): Enable standard library support
//! - Without `std`: `no_std` compatible for embedded systems
//!
//! # Example
//!
//! ```rust
//! use scrap_core::{CapabilityTokenBuilder, TokenValidator};
//! use scrap_core::crypto::derive_public_key;
//!
//! // Create and sign a capability token
//! let privkey = [0x01u8; 32]; // Use real key in practice
//! let pubkey = derive_public_key(&privkey).unwrap();
//!
//! let token = CapabilityTokenBuilder::new(
//!     "OPERATOR".into(),
//!     "SATELLITE-1".into(),
//!     "SATELLITE-2".into(),
//!     "task-001".into(),
//!     vec!["cmd:imaging:msi".into()],
//! )
//! .valid_for(1705320000, 86400)
//! .sign(&privkey)
//! .unwrap();
//!
//! // Validate the token
//! TokenValidator::new(&token)
//!     .at_time(1705320500)
//!     .with_issuer_key(&pubkey)
//!     .validate()
//!     .unwrap();
//! ```

#![cfg_attr(not(feature = "std"), no_std)]

extern crate alloc;

pub mod types;
pub mod crypto;
pub mod cbor;
pub mod token;
pub mod error;

// Re-export types
pub use types::*;

// Re-export crypto functions
pub use crypto::{
    sign_message,
    verify_signature,
    sha256,
    derive_public_key,
    compute_binding_hash,
    compute_proof_hash,
    Signer,
    KeySigner,
};

// Re-export CBOR functions
pub use cbor::{
    encode,
    decode,
    encode_protected_content,
    encode_capability_token,
    decode_capability_token,
    encode_task_request,
    decode_task_request,
    encode_execution_proof,
    decode_execution_proof,
};

// Re-export token builder and validator
pub use token::{
    CapabilityTokenBuilder,
    TokenValidator,
    validate_capability,
    capability_matches,
    parse_and_validate,
};

// Re-export error type
pub use error::ScrapError;

/// Protocol version
pub const VERSION: &str = "1.0.0";
