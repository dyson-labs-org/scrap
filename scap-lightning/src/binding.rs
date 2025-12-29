//! SCAP task-payment binding
//!
//! This module binds capability tokens to Lightning payments, ensuring that
//! task authorization and payment are atomically linked.

use scap_core::{
    CapabilityToken, ExecutionProof, BoundTaskRequest,
    sha256, sign_message, verify_signature, compute_binding_hash, compute_proof_hash,
    encode_capability_token,
};
use std::collections::HashMap;
use std::sync::RwLock;
use serde::{Serialize, Deserialize};

/// Binding between a SCAP task and Lightning payment
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskPaymentBinding {
    /// Capability token JTI
    pub task_jti: String,
    /// Payment hash (32 bytes hex)
    pub payment_hash: String,
    /// Payment amount in millisatoshis
    pub amount_msat: u64,
    /// HTLC timeout in blocks
    pub htlc_timeout_blocks: u32,
    /// Binding signature (hex)
    pub binding_signature: String,
    /// CBOR-encoded capability token (hex)
    pub capability_token_cbor: String,
    /// Binding status
    pub status: BindingStatus,
    /// Creation timestamp
    pub created_at: u64,
}

/// Status of a task-payment binding
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BindingStatus {
    /// Binding created, awaiting task execution
    Pending,
    /// Task executed, proof submitted
    Executed,
    /// Payment settled (preimage revealed)
    Settled,
    /// Task failed or payment expired
    Failed,
    /// Disputed
    Disputed,
}

/// Manager for task-payment bindings
pub struct BindingManager {
    /// Active bindings (keyed by task JTI)
    bindings: RwLock<HashMap<String, TaskPaymentBinding>>,
    /// Index by payment hash
    by_payment_hash: RwLock<HashMap<String, String>>,
    /// Timestamp provider
    get_timestamp: Box<dyn Fn() -> u64 + Send + Sync>,
}

impl BindingManager {
    /// Create a new binding manager
    pub fn new() -> Self {
        Self::with_timestamp(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0)
        })
    }

    /// Create with custom timestamp provider
    pub fn with_timestamp<F: Fn() -> u64 + Send + Sync + 'static>(get_timestamp: F) -> Self {
        Self {
            bindings: RwLock::new(HashMap::new()),
            by_payment_hash: RwLock::new(HashMap::new()),
            get_timestamp: Box::new(get_timestamp),
        }
    }

    /// Create a new task-payment binding
    ///
    /// This creates a binding between a capability token and a Lightning payment.
    /// The binding is signed by the requester to prove they authorized both.
    pub fn create_binding(
        &self,
        token: &CapabilityToken,
        payment_hash: [u8; 32],
        amount_msat: u64,
        htlc_timeout_blocks: u32,
        signing_key: &[u8],
    ) -> Result<TaskPaymentBinding, BindingError> {
        let task_jti = token.payload.jti.clone();
        let payment_hash_hex = hex::encode(payment_hash);

        // Compute binding hash: SHA256(jti || payment_hash)
        let binding_hash = compute_binding_hash(&task_jti, &payment_hash);

        // Sign the binding
        let binding_sig = sign_message(signing_key, &binding_hash)
            .map_err(|e| BindingError::SigningFailed(e.to_string()))?;

        // Encode the token to CBOR
        let token_cbor = encode_capability_token(token)
            .map_err(|e| BindingError::EncodingFailed(e.to_string()))?;

        let binding = TaskPaymentBinding {
            task_jti: task_jti.clone(),
            payment_hash: payment_hash_hex.clone(),
            amount_msat,
            htlc_timeout_blocks,
            binding_signature: hex::encode(&binding_sig),
            capability_token_cbor: hex::encode(&token_cbor),
            status: BindingStatus::Pending,
            created_at: (self.get_timestamp)(),
        };

        // Store binding
        self.bindings.write().unwrap().insert(task_jti.clone(), binding.clone());
        self.by_payment_hash.write().unwrap().insert(payment_hash_hex, task_jti);

        Ok(binding)
    }

    /// Verify a binding signature
    pub fn verify_binding(
        binding: &TaskPaymentBinding,
        requester_pubkey: &[u8],
    ) -> Result<bool, BindingError> {
        let payment_hash = hex::decode(&binding.payment_hash)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        let binding_hash = compute_binding_hash(&binding.task_jti, &payment_hash);

        let signature = hex::decode(&binding.binding_signature)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        verify_signature(requester_pubkey, &binding_hash, &signature)
            .map_err(|e| BindingError::VerificationFailed(e.to_string()))
    }

    /// Create a bound task request message
    pub fn create_task_request(
        &self,
        binding: &TaskPaymentBinding,
    ) -> Result<BoundTaskRequest, BindingError> {
        let token_cbor = hex::decode(&binding.capability_token_cbor)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        let payment_hash = hex::decode(&binding.payment_hash)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        let binding_sig = hex::decode(&binding.binding_signature)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        Ok(BoundTaskRequest {
            capability_token: token_cbor,
            payment_hash,
            payment_amount_msat: binding.amount_msat,
            htlc_timeout_blocks: binding.htlc_timeout_blocks,
            binding_sig,
        })
    }

    /// Create an execution proof
    pub fn create_proof(
        &self,
        task_jti: &str,
        output_data: &[u8],
        executor_key: &[u8],
    ) -> Result<ExecutionProof, BindingError> {
        let binding = self.get_by_jti(task_jti)
            .ok_or_else(|| BindingError::NotFound(task_jti.to_string()))?;

        let payment_hash = hex::decode(&binding.payment_hash)
            .map_err(|e| BindingError::InvalidData(e.to_string()))?;

        let output_hash = sha256(output_data);
        let timestamp = (self.get_timestamp)();

        // Compute proof hash
        let proof_hash = compute_proof_hash(task_jti, &payment_hash, &output_hash, timestamp);

        // Sign the proof
        let signature = sign_message(executor_key, &proof_hash)
            .map_err(|e| BindingError::SigningFailed(e.to_string()))?;

        Ok(ExecutionProof {
            task_jti: task_jti.to_string(),
            payment_hash,
            output_hash: output_hash.to_vec(),
            execution_timestamp: timestamp,
            output_metadata: None,
            executor_sig: signature,
        })
    }

    /// Verify an execution proof
    pub fn verify_proof(
        proof: &ExecutionProof,
        executor_pubkey: &[u8],
    ) -> Result<bool, BindingError> {
        let proof_hash = compute_proof_hash(
            &proof.task_jti,
            &proof.payment_hash,
            &proof.output_hash,
            proof.execution_timestamp,
        );

        verify_signature(executor_pubkey, &proof_hash, &proof.executor_sig)
            .map_err(|e| BindingError::VerificationFailed(e.to_string()))
    }

    /// Update binding status
    pub fn update_status(&self, task_jti: &str, status: BindingStatus) -> bool {
        if let Some(binding) = self.bindings.write().unwrap().get_mut(task_jti) {
            binding.status = status;
            true
        } else {
            false
        }
    }

    /// Get binding by task JTI
    pub fn get_by_jti(&self, task_jti: &str) -> Option<TaskPaymentBinding> {
        self.bindings.read().unwrap().get(task_jti).cloned()
    }

    /// Get binding by payment hash
    pub fn get_by_payment_hash(&self, payment_hash: &str) -> Option<TaskPaymentBinding> {
        let jti = self.by_payment_hash.read().unwrap().get(payment_hash)?.clone();
        self.get_by_jti(&jti)
    }

    /// Get all pending bindings
    pub fn get_pending(&self) -> Vec<TaskPaymentBinding> {
        self.bindings.read().unwrap()
            .values()
            .filter(|b| b.status == BindingStatus::Pending)
            .cloned()
            .collect()
    }

    /// Remove a binding
    pub fn remove(&self, task_jti: &str) -> Option<TaskPaymentBinding> {
        let binding = self.bindings.write().unwrap().remove(task_jti)?;
        self.by_payment_hash.write().unwrap().remove(&binding.payment_hash);
        Some(binding)
    }
}

impl Default for BindingManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Binding errors
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BindingError {
    /// Binding not found
    NotFound(String),
    /// Signing failed
    SigningFailed(String),
    /// Verification failed
    VerificationFailed(String),
    /// Encoding failed
    EncodingFailed(String),
    /// Invalid data
    InvalidData(String),
}

impl std::fmt::Display for BindingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotFound(jti) => write!(f, "binding not found: {}", jti),
            Self::SigningFailed(msg) => write!(f, "signing failed: {}", msg),
            Self::VerificationFailed(msg) => write!(f, "verification failed: {}", msg),
            Self::EncodingFailed(msg) => write!(f, "encoding failed: {}", msg),
            Self::InvalidData(msg) => write!(f, "invalid data: {}", msg),
        }
    }
}

impl std::error::Error for BindingError {}

#[cfg(test)]
mod tests {
    use super::*;
    use scap_core::{CapabilityTokenBuilder, derive_public_key};

    fn test_keypair() -> (Vec<u8>, Vec<u8>) {
        let privkey = hex::decode(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ).unwrap();
        let pubkey = derive_public_key(&privkey).unwrap();
        (privkey, pubkey)
    }

    fn test_token() -> CapabilityToken {
        let (privkey, _) = test_keypair();
        CapabilityTokenBuilder::new(
            "OPERATOR".into(),
            "SAT-1".into(),
            "SAT-2".into(),
            "task-001".into(),
            vec!["cmd:imaging:msi".into()],
        )
        .valid_for(1705320000, 86400)
        .sign(&privkey)
        .unwrap()
    }

    #[test]
    fn test_create_binding() {
        let manager = BindingManager::new();
        let (privkey, pubkey) = test_keypair();
        let token = test_token();
        let payment_hash = sha256(b"preimage");

        let binding = manager.create_binding(
            &token,
            payment_hash,
            1_000_000,
            336,
            &privkey,
        ).unwrap();

        assert_eq!(binding.task_jti, "task-001");
        assert_eq!(binding.amount_msat, 1_000_000);
        assert_eq!(binding.status, BindingStatus::Pending);

        // Verify the binding
        let valid = BindingManager::verify_binding(&binding, &pubkey).unwrap();
        assert!(valid);
    }

    #[test]
    fn test_create_and_verify_proof() {
        let manager = BindingManager::new();
        let (privkey, pubkey) = test_keypair();
        let token = test_token();
        let payment_hash = sha256(b"preimage");

        manager.create_binding(&token, payment_hash, 1_000_000, 336, &privkey).unwrap();

        let output_data = b"imaging output data";
        let proof = manager.create_proof("task-001", output_data, &privkey).unwrap();

        assert_eq!(proof.task_jti, "task-001");

        let valid = BindingManager::verify_proof(&proof, &pubkey).unwrap();
        assert!(valid);
    }

    #[test]
    fn test_get_by_payment_hash() {
        let manager = BindingManager::new();
        let (privkey, _) = test_keypair();
        let token = test_token();
        let payment_hash = sha256(b"preimage");
        let payment_hash_hex = hex::encode(payment_hash);

        manager.create_binding(&token, payment_hash, 1_000_000, 336, &privkey).unwrap();

        let binding = manager.get_by_payment_hash(&payment_hash_hex).unwrap();
        assert_eq!(binding.task_jti, "task-001");
    }

    #[test]
    fn test_update_status() {
        let manager = BindingManager::new();
        let (privkey, _) = test_keypair();
        let token = test_token();
        let payment_hash = sha256(b"preimage");

        manager.create_binding(&token, payment_hash, 1_000_000, 336, &privkey).unwrap();

        manager.update_status("task-001", BindingStatus::Executed);
        let binding = manager.get_by_jti("task-001").unwrap();
        assert_eq!(binding.status, BindingStatus::Executed);
    }
}
