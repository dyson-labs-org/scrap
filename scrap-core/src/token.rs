//! Capability token building, signing, and validation

use alloc::string::String;
use alloc::vec::Vec;
use crate::cbor::{encode_protected_content, decode_capability_token};
use crate::crypto::{sha256, verify_signature, Signer, KeySigner};
use crate::error::ScrapError;
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

    /// Build and sign the token with any [`Signer`] — keeping the private key
    /// outside this library (HSM, secure element, signing daemon, …).
    ///
    /// The protected content (header + payload) is encoded once; the signature is
    /// over `SHA256(protected)`, and `protected` is retained and carried on the
    /// wire verbatim.
    pub fn sign_with<S: Signer + ?Sized>(self, signer: &S) -> Result<CapabilityToken, ScrapError> {
        let content = ProtectedContent { header: self.header, payload: self.payload };
        let protected = encode_protected_content(&content)?;
        let digest = sha256(&protected);
        let signature = signer.sign_digest(&digest)?;
        Ok(CapabilityToken {
            header: content.header,
            payload: content.payload,
            protected,
            signature,
        })
    }

    /// Build and sign with a raw private key (in-process convenience).
    ///
    /// Equivalent to `sign_with(&KeySigner::from_slice(private_key)?)`. On
    /// multi-tenant hardware, prefer [`Self::sign_with`] with an external signer.
    pub fn sign(self, private_key: &[u8]) -> Result<CapabilityToken, ScrapError> {
        let signer = KeySigner::from_slice(private_key)?;
        self.sign_with(&signer)
    }

    /// Build without signing (for testing)
    pub fn build_unsigned(self) -> CapabilityToken {
        let content = ProtectedContent { header: self.header, payload: self.payload };
        let protected = encode_protected_content(&content).unwrap_or_default();
        CapabilityToken {
            header: content.header,
            payload: content.payload,
            protected,
            signature: Vec::new(),
        }
    }
}

/// Validate a capability token
pub struct TokenValidator<'a> {
    token: &'a CapabilityToken,
    current_time: Option<Timestamp>,
    issuer_pubkey: Option<&'a [u8]>,
    parent: Option<&'a CapabilityToken>,
}

impl<'a> TokenValidator<'a> {
    /// Create a new validator for a token
    pub fn new(token: &'a CapabilityToken) -> Self {
        Self {
            token,
            current_time: None,
            issuer_pubkey: None,
            parent: None,
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

    /// Supply the parent token so delegation attenuation (child ⊆ parent) is
    /// enforced. Required to validate a `SAT-CAP-DEL` token's authority — without
    /// it, a delegation's capabilities cannot be checked against what it inherited.
    pub fn with_parent(mut self, parent: &'a CapabilityToken) -> Self {
        self.parent = Some(parent);
        self
    }

    /// Validate the token
    pub fn validate(self) -> Result<(), ScrapError> {
        // Check algorithm
        if self.token.header.alg != "ES256K" {
            return Err(ScrapError::InvalidCapability(
                alloc::format!("unsupported algorithm: {}", self.token.header.alg)
            ));
        }

        // Check token type
        if self.token.header.typ != "SAT-CAP" && self.token.header.typ != "SAT-CAP-DEL" {
            return Err(ScrapError::InvalidCapability(
                alloc::format!("invalid token type: {}", self.token.header.typ)
            ));
        }

        // Check delegation consistency
        if self.token.header.typ == "SAT-CAP-DEL" && self.token.payload.prf.is_none() {
            return Err(ScrapError::MissingField(String::from("prf (parent reference required for delegation)")));
        }

        // Enforce delegation attenuation against the parent (child ⊆ parent).
        if self.token.header.typ == "SAT-CAP-DEL" {
            if let Some(parent) = self.parent {
                // prf must name the parent
                if self.token.payload.prf.as_deref() != Some(parent.payload.jti.as_str()) {
                    return Err(ScrapError::ConstraintViolation(
                        alloc::format!("prf does not reference parent jti: {}", parent.payload.jti)
                    ));
                }
                // chain depth must increase by exactly one (root = 0)
                let parent_depth = parent.header.chn.unwrap_or(0);
                if let Some(child_depth) = self.token.header.chn {
                    if child_depth != parent_depth + 1 {
                        return Err(ScrapError::ConstraintViolation(
                            alloc::format!("chain depth {} is not parent depth {} + 1", child_depth, parent_depth)
                        ));
                    }
                }
                // every delegated capability must be authorized by the parent
                for cap in &self.token.payload.cap {
                    let authorized = parent.payload.cap.iter()
                        .any(|granted| capability_matches(granted, cap));
                    if !authorized {
                        return Err(ScrapError::InvalidCapability(
                            alloc::format!("delegated capability exceeds parent grant: {}", cap)
                        ));
                    }
                }
                // a delegation must not outlive its parent
                if self.token.payload.exp > parent.payload.exp {
                    return Err(ScrapError::ConstraintViolation(String::from(
                        "delegation expiry exceeds parent expiry"
                    )));
                }
            }
        }

        // Check time validity
        if let Some(now) = self.current_time {
            if now < self.token.payload.iat {
                return Err(ScrapError::TokenNotYetValid);
            }
            if now > self.token.payload.exp {
                return Err(ScrapError::TokenExpired);
            }
        }

        // Verify signature if public key provided.
        // The signature is verified over the verbatim `protected` bytes that were
        // received and signed — NOT over a re-serialization of header/payload — so
        // verification is independent of CBOR canonicalization (fixes C1).
        if let Some(pubkey) = self.issuer_pubkey {
            let valid = verify_signature(pubkey, &self.token.protected, &self.token.signature)?;
            if !valid {
                return Err(ScrapError::VerificationFailed);
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
pub fn validate_capability(cap: &str) -> Result<(), ScrapError> {
    let parts: Vec<&str> = cap.split(':').collect();
    if parts.len() < 2 {
        return Err(ScrapError::InvalidCapability(
            alloc::format!("capability must have at least 2 parts: {}", cap)
        ));
    }

    // Check for empty parts
    for part in &parts {
        if part.is_empty() {
            return Err(ScrapError::InvalidCapability(
                alloc::format!("capability contains empty part: {}", cap)
            ));
        }
    }

    // First part must be a known category
    let valid_categories = ["cmd", "relay", "data", "query", "admin"];
    if !valid_categories.contains(&parts[0]) && parts[0] != "*" {
        return Err(ScrapError::InvalidCapability(
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
) -> Result<CapabilityToken, ScrapError> {
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

    // An external signer that holds no key in the library: it delegates to a
    // closure (standing in for an HSM / secure element / signing daemon).
    struct ExternalSigner { privkey: Vec<u8> }
    impl Signer for ExternalSigner {
        fn sign_digest(&self, digest: &[u8; 32]) -> Result<Vec<u8>, ScrapError> {
            // In reality this call crosses to secure hardware; here we reuse the
            // in-process primitive to prove the wiring + that the result verifies.
            KeySigner::from_slice(&self.privkey)?.sign_digest(digest)
        }
    }

    #[test]
    fn test_sign_with_external_signer() {
        let (privkey, pubkey) = test_keypair();
        let signer = ExternalSigner { privkey };
        let token = CapabilityTokenBuilder::new(
            String::from("OPERATOR"), String::from("SAT-1"), String::from("SAT-2"),
            String::from("ext-001"), vec![String::from("cmd:compute:inference")],
        )
        .valid_for(1705320000, 3600)
        .sign_with(&signer)
        .unwrap();

        TokenValidator::new(&token)
            .at_time(1705320500)
            .with_issuer_key(&pubkey)
            .validate()
            .unwrap();
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

        assert!(matches!(result, Err(ScrapError::TokenExpired)));
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

        assert!(matches!(result, Err(ScrapError::TokenNotYetValid)));
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

        assert!(matches!(result, Err(ScrapError::VerificationFailed)));
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

    fn parent_and_child(child_caps: Vec<String>, child_exp_secs: u64) -> (CapabilityToken, CapabilityToken) {
        let (privkey, _) = test_keypair();
        let parent = CapabilityTokenBuilder::new(
            String::from("OPERATOR-A"), String::from("SAT-RELAY"), String::from("SAT-EXEC"),
            String::from("parent-001"),
            vec![String::from("cmd:compute:inference"), String::from("relay:task:forward")],
        ).valid_for(1705320000, 7200).sign(&privkey).unwrap();

        let child = CapabilityTokenBuilder::new(
            String::from("SAT-RELAY"), String::from("SAT-EXEC"), String::from("SAT-EXEC-2"),
            String::from("child-001"), child_caps,
        )
        .delegated_from(String::from("parent-001"))
        .chain_depth(1)
        .valid_for(1705320000, child_exp_secs)
        .sign(&privkey).unwrap();
        (parent, child)
    }

    #[test]
    fn test_delegation_attenuation_ok() {
        // child requests a subset of the parent's grant
        let (parent, child) = parent_and_child(vec![String::from("cmd:compute:inference")], 3600);
        TokenValidator::new(&child)
            .at_time(1705320500)
            .with_parent(&parent)
            .validate()
            .unwrap();
    }

    #[test]
    fn test_delegation_exceeds_parent() {
        // child claims a capability the parent never granted
        let (parent, child) = parent_and_child(vec![String::from("cmd:propulsion:burn")], 3600);
        let result = TokenValidator::new(&child).at_time(1705320500).with_parent(&parent).validate();
        assert!(matches!(result, Err(ScrapError::InvalidCapability(_))));
    }

    #[test]
    fn test_delegation_outlives_parent() {
        // child expires after the parent
        let (parent, child) = parent_and_child(vec![String::from("cmd:compute:inference")], 999999);
        let result = TokenValidator::new(&child).at_time(1705320500).with_parent(&parent).validate();
        assert!(matches!(result, Err(ScrapError::ConstraintViolation(_))));
    }

    #[test]
    fn test_delegation_wrong_parent() {
        // prf does not reference the supplied parent
        let (privkey, _) = test_keypair();
        let (_, child) = parent_and_child(vec![String::from("cmd:compute:inference")], 3600);
        let other_parent = CapabilityTokenBuilder::new(
            String::from("OPERATOR-A"), String::from("X"), String::from("Y"),
            String::from("some-other-jti"), vec![String::from("cmd:compute:inference")],
        ).valid_for(1705320000, 7200).sign(&privkey).unwrap();
        let result = TokenValidator::new(&child).at_time(1705320500).with_parent(&other_parent).validate();
        assert!(matches!(result, Err(ScrapError::ConstraintViolation(_))));
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
