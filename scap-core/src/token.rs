//! Capability token building, signing, and validation

use alloc::string::String;
use alloc::vec::Vec;
use crate::cbor::{encode_header, encode_payload, decode_capability_token};
use crate::crypto::{sign_message, verify_signature};
use crate::error::ScapError;
use crate::types::*;

/// Builder for creating capability tokens
pub struct CapabilityTokenBuilder {
    header: CapHeader,
    payload: CapPayload,
}

impl CapabilityTokenBuilder {
    /// Create a new builder with required fields
    pub fn new(
        issuer: String,
        subject: String,
        audience: String,
        jti: String,
        capabilities: Vec<String>,
    ) -> Self {
        Self {
            header: CapHeader::default(),
            payload: CapPayload {
                iss: issuer,
                sub: subject,
                aud: audience,
                iat: 0,
                exp: 0,
                jti,
                cap: capabilities,
                cns: None,
                prf: None,
                cmd_pub: None,
            },
        }
    }

    /// Set the issued-at timestamp
    pub fn issued_at(mut self, timestamp: Timestamp) -> Self {
        self.payload.iat = timestamp;
        self
    }

    /// Set the expiration timestamp
    pub fn expires_at(mut self, timestamp: Timestamp) -> Self {
        self.payload.exp = timestamp;
        self
    }

    /// Set validity window (issued now, expires after duration_secs)
    pub fn valid_for(mut self, now: Timestamp, duration_secs: u64) -> Self {
        self.payload.iat = now;
        self.payload.exp = now + duration_secs;
        self
    }

    /// Add constraints
    pub fn with_constraints(mut self, constraints: Constraints) -> Self {
        self.payload.cns = Some(constraints);
        self
    }

    /// Set parent token reference (for delegations)
    pub fn delegated_from(mut self, parent_jti: String) -> Self {
        self.payload.prf = Some(parent_jti);
        self.header.typ = String::from("SAT-CAP-DEL");
        self
    }

    /// Set chain depth (for delegations)
    pub fn chain_depth(mut self, depth: u32) -> Self {
        self.header.chn = Some(depth);
        self
    }

    /// Set authorized command signing key
    pub fn command_key(mut self, pubkey: Vec<u8>) -> Self {
        self.payload.cmd_pub = Some(pubkey);
        self
    }

    /// Build and sign the token
    pub fn sign(self, private_key: &[u8]) -> Result<CapabilityToken, ScapError> {
        let header_cbor = encode_header(&self.header)?;
        let payload_cbor = encode_payload(&self.payload)?;

        let mut signing_input = Vec::with_capacity(header_cbor.len() + payload_cbor.len());
        signing_input.extend_from_slice(&header_cbor);
        signing_input.extend_from_slice(&payload_cbor);

        let signature = sign_message(private_key, &signing_input)?;

        Ok(CapabilityToken {
            header: self.header,
            payload: self.payload,
            signature,
        })
    }

    /// Build without signing (for testing)
    pub fn build_unsigned(self) -> CapabilityToken {
        CapabilityToken {
            header: self.header,
            payload: self.payload,
            signature: Vec::new(),
        }
    }
}

/// Validate a capability token
pub struct TokenValidator<'a> {
    token: &'a CapabilityToken,
    current_time: Option<Timestamp>,
    issuer_pubkey: Option<&'a [u8]>,
}

impl<'a> TokenValidator<'a> {
    /// Create a new validator for a token
    pub fn new(token: &'a CapabilityToken) -> Self {
        Self {
            token,
            current_time: None,
            issuer_pubkey: None,
        }
    }

    /// Set the current time for expiration checking
    pub fn at_time(mut self, timestamp: Timestamp) -> Self {
        self.current_time = Some(timestamp);
        self
    }

    /// Set the issuer's public key for signature verification
    pub fn with_issuer_key(mut self, pubkey: &'a [u8]) -> Self {
        self.issuer_pubkey = Some(pubkey);
        self
    }

    /// Validate the token
    pub fn validate(self) -> Result<(), ScapError> {
        // Check algorithm
        if self.token.header.alg != "ES256K" {
            return Err(ScapError::InvalidCapability(
                alloc::format!("unsupported algorithm: {}", self.token.header.alg)
            ));
        }

        // Check token type
        if self.token.header.typ != "SAT-CAP" && self.token.header.typ != "SAT-CAP-DEL" {
            return Err(ScapError::InvalidCapability(
                alloc::format!("invalid token type: {}", self.token.header.typ)
            ));
        }

        // Check delegation consistency
        if self.token.header.typ == "SAT-CAP-DEL" && self.token.payload.prf.is_none() {
            return Err(ScapError::MissingField(String::from("prf (parent reference required for delegation)")));
        }

        // Check time validity
        if let Some(now) = self.current_time {
            if now < self.token.payload.iat {
                return Err(ScapError::TokenNotYetValid);
            }
            if now > self.token.payload.exp {
                return Err(ScapError::TokenExpired);
            }
        }

        // Verify signature if public key provided
        if let Some(pubkey) = self.issuer_pubkey {
            let header_cbor = encode_header(&self.token.header)?;
            let payload_cbor = encode_payload(&self.token.payload)?;

            let mut signing_input = Vec::with_capacity(header_cbor.len() + payload_cbor.len());
            signing_input.extend_from_slice(&header_cbor);
            signing_input.extend_from_slice(&payload_cbor);

            let valid = verify_signature(pubkey, &signing_input, &self.token.signature)?;
            if !valid {
                return Err(ScapError::VerificationFailed);
            }
        }

        // Validate capabilities format
        for cap in &self.token.payload.cap {
            validate_capability(cap)?;
        }

        Ok(())
    }
}

/// Validate a capability string format
/// Format: "category:action:target" (e.g., "cmd:imaging:msi")
pub fn validate_capability(cap: &str) -> Result<(), ScapError> {
    let parts: Vec<&str> = cap.split(':').collect();
    if parts.len() < 2 {
        return Err(ScapError::InvalidCapability(
            alloc::format!("capability must have at least 2 parts: {}", cap)
        ));
    }

    // Check for empty parts
    for part in &parts {
        if part.is_empty() {
            return Err(ScapError::InvalidCapability(
                alloc::format!("capability contains empty part: {}", cap)
            ));
        }
    }

    // First part must be a known category
    let valid_categories = ["cmd", "relay", "data", "query", "admin"];
    if !valid_categories.contains(&parts[0]) && parts[0] != "*" {
        return Err(ScapError::InvalidCapability(
            alloc::format!("unknown capability category: {}", parts[0])
        ));
    }

    Ok(())
}

/// Check if a capability grants a specific permission
pub fn capability_matches(granted: &str, requested: &str) -> bool {
    let granted_parts: Vec<&str> = granted.split(':').collect();
    let requested_parts: Vec<&str> = requested.split(':').collect();

    // Granted capability must be at least as specific as requested
    if granted_parts.len() > requested_parts.len() {
        return false;
    }

    for (i, granted_part) in granted_parts.iter().enumerate() {
        if *granted_part == "*" {
            // Wildcard matches everything from here
            return true;
        }
        if i >= requested_parts.len() || *granted_part != requested_parts[i] {
            return false;
        }
    }

    // Exact match or granted is a prefix
    granted_parts.len() <= requested_parts.len()
}

/// Parse a token from CBOR bytes and validate it
pub fn parse_and_validate(
    bytes: &[u8],
    issuer_pubkey: &[u8],
    current_time: Timestamp,
) -> Result<CapabilityToken, ScapError> {
    let token = decode_capability_token(bytes)?;

    TokenValidator::new(&token)
        .at_time(current_time)
        .with_issuer_key(issuer_pubkey)
        .validate()?;

    Ok(token)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto::derive_public_key;
    use alloc::vec;

    fn test_keypair() -> (Vec<u8>, Vec<u8>) {
        let privkey = hex::decode(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ).unwrap();
        let pubkey = derive_public_key(&privkey).unwrap();
        (privkey, pubkey)
    }

    #[test]
    fn test_build_and_sign_token() {
        let (privkey, pubkey) = test_keypair();
        let now = 1705320000u64;

        let token = CapabilityTokenBuilder::new(
            String::from("OPERATOR-TEST"),
            String::from("SATELLITE-1"),
            String::from("SATELLITE-2"),
            String::from("test-001"),
            vec![String::from("cmd:imaging:msi")],
        )
        .valid_for(now, 86400)
        .sign(&privkey)
        .unwrap();

        assert_eq!(token.payload.iss, "OPERATOR-TEST");
        assert_eq!(token.payload.iat, now);
        assert_eq!(token.payload.exp, now + 86400);
        assert!(!token.signature.is_empty());

        // Validate the token
        TokenValidator::new(&token)
            .at_time(now + 1000)
            .with_issuer_key(&pubkey)
            .validate()
            .unwrap();
    }

    #[test]
    fn test_token_expired() {
        let (privkey, _pubkey) = test_keypair();
        let now = 1705320000u64;

        let token = CapabilityTokenBuilder::new(
            String::from("OPERATOR"),
            String::from("SAT-1"),
            String::from("SAT-2"),
            String::from("test-001"),
            vec![String::from("cmd:imaging:msi")],
        )
        .valid_for(now, 3600)
        .sign(&privkey)
        .unwrap();

        // Check after expiration
        let result = TokenValidator::new(&token)
            .at_time(now + 7200)
            .validate();

        assert!(matches!(result, Err(ScapError::TokenExpired)));
    }

    #[test]
    fn test_token_not_yet_valid() {
        let (privkey, _pubkey) = test_keypair();
        let now = 1705320000u64;

        let token = CapabilityTokenBuilder::new(
            String::from("OPERATOR"),
            String::from("SAT-1"),
            String::from("SAT-2"),
            String::from("test-001"),
            vec![String::from("cmd:imaging:msi")],
        )
        .valid_for(now, 3600)
        .sign(&privkey)
        .unwrap();

        // Check before issued
        let result = TokenValidator::new(&token)
            .at_time(now - 100)
            .validate();

        assert!(matches!(result, Err(ScapError::TokenNotYetValid)));
    }

    #[test]
    fn test_invalid_signature() {
        let (privkey, _) = test_keypair();
        let (_, wrong_pubkey) = {
            // Use a different valid private key
            let other_priv = hex::decode(
                "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
            ).unwrap();
            (other_priv.clone(), derive_public_key(&other_priv).unwrap())
        };

        let token = CapabilityTokenBuilder::new(
            String::from("OPERATOR"),
            String::from("SAT-1"),
            String::from("SAT-2"),
            String::from("test-001"),
            vec![String::from("cmd:imaging:msi")],
        )
        .valid_for(1705320000, 3600)
        .sign(&privkey)
        .unwrap();

        let result = TokenValidator::new(&token)
            .with_issuer_key(&wrong_pubkey)
            .validate();

        assert!(matches!(result, Err(ScapError::VerificationFailed)));
    }

    #[test]
    fn test_capability_validation() {
        assert!(validate_capability("cmd:imaging:msi").is_ok());
        assert!(validate_capability("relay:task:forward").is_ok());
        assert!(validate_capability("cmd:*").is_ok());
        assert!(validate_capability("data:download").is_ok());

        assert!(validate_capability("single").is_err());
        assert!(validate_capability("unknown:action").is_err());
        assert!(validate_capability("cmd::empty").is_err());
    }

    #[test]
    fn test_capability_matching() {
        // Exact matches
        assert!(capability_matches("cmd:imaging:msi", "cmd:imaging:msi"));

        // Wildcards
        assert!(capability_matches("cmd:*", "cmd:imaging:msi"));
        assert!(capability_matches("cmd:imaging:*", "cmd:imaging:msi"));

        // Prefix matching
        assert!(capability_matches("cmd:imaging", "cmd:imaging:msi"));

        // Non-matches
        assert!(!capability_matches("cmd:imaging:msi", "cmd:imaging"));
        assert!(!capability_matches("cmd:propulsion", "cmd:imaging:msi"));
        assert!(!capability_matches("relay:task", "cmd:imaging:msi"));
    }

    #[test]
    fn test_delegation_token() {
        let (privkey, pubkey) = test_keypair();

        let token = CapabilityTokenBuilder::new(
            String::from("SATELLITE-1"),
            String::from("SATELLITE-2"),
            String::from("SATELLITE-3"),
            String::from("del-001"),
            vec![String::from("cmd:imaging:msi")],
        )
        .delegated_from(String::from("parent-001"))
        .chain_depth(1)
        .valid_for(1705320000, 3600)
        .sign(&privkey)
        .unwrap();

        assert_eq!(token.header.typ, "SAT-CAP-DEL");
        assert_eq!(token.header.chn, Some(1));
        assert_eq!(token.payload.prf, Some(String::from("parent-001")));

        TokenValidator::new(&token)
            .at_time(1705320500)
            .with_issuer_key(&pubkey)
            .validate()
            .unwrap();
    }
}
