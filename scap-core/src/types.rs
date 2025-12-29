//! SCAP message types
//!
//! These types correspond to the CDDL schema in `schemas/scap.cddl`

use alloc::string::String;
use alloc::vec::Vec;
use serde::{Deserialize, Serialize};

/// Unix timestamp (seconds since epoch)
pub type Timestamp = u64;

/// SHA-256 hash (32 bytes)
pub type Sha256Hash = [u8; 32];

/// secp256k1 compressed public key (33 bytes)
pub type PublicKey = [u8; 33];

/// ECDSA signature in DER format (variable length, typically 70-72 bytes)
pub type Signature = Vec<u8>;

/// Capability token header
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapHeader {
    /// Algorithm (always "ES256K" for secp256k1)
    pub alg: String,
    /// Token type: "SAT-CAP" or "SAT-CAP-DEL" for delegations
    pub typ: String,
    /// Encoding format (optional, defaults to "CBOR")
    #[serde(skip_serializing_if = "Option::is_none")]
    pub enc: Option<String>,
    /// Chain depth for delegations (0 = root token)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chn: Option<u32>,
}

impl Default for CapHeader {
    fn default() -> Self {
        Self {
            alg: String::from("ES256K"),
            typ: String::from("SAT-CAP"),
            enc: Some(String::from("CBOR")),
            chn: None,
        }
    }
}

/// Geographic bounds constraint
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GeoBounds {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lat_min: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lat_max: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lon_min: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lon_max: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub polygon: Option<Vec<[f64; 2]>>,
}

/// Time window constraint
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TimeWindow {
    pub start: Timestamp,
    pub end: Timestamp,
}

/// Constraints on capability usage
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct Constraints {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_area_km2: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_range_km: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_hops: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub geographic_bounds: Option<GeoBounds>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub time_window: Option<TimeWindow>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub min_approach_distance_m: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_relative_velocity_m_s: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fuel_budget_kg: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub abort_triggers: Option<Vec<String>>,
}

/// Capability token payload
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CapPayload {
    /// Issuer (operator ID or satellite ID)
    pub iss: String,
    /// Subject (authorized entity)
    pub sub: String,
    /// Audience (target satellite ID)
    pub aud: String,
    /// Issued at timestamp
    pub iat: Timestamp,
    /// Expiration timestamp
    pub exp: Timestamp,
    /// Unique token ID
    pub jti: String,
    /// Granted capabilities (e.g., ["cmd:imaging:msi"])
    pub cap: Vec<String>,
    /// Constraints on capabilities
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cns: Option<Constraints>,
    /// Parent token JTI (for delegations)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub prf: Option<String>,
    /// Authorized command signing key
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[serde(with = "optional_bytes")]
    pub cmd_pub: Option<Vec<u8>>,
}

/// Complete capability token
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CapabilityToken {
    pub header: CapHeader,
    pub payload: CapPayload,
    #[serde(with = "serde_bytes")]
    pub signature: Vec<u8>,
}

/// Task request bound to a Lightning payment
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BoundTaskRequest {
    /// CBOR-encoded capability token
    #[serde(with = "serde_bytes")]
    pub capability_token: Vec<u8>,
    /// Lightning payment hash (SHA256)
    #[serde(with = "serde_bytes")]
    pub payment_hash: Vec<u8>,
    /// Payment amount in millisatoshi
    pub payment_amount_msat: u64,
    /// HTLC timeout in Bitcoin blocks
    pub htlc_timeout_blocks: u32,
    /// Signature over binding hash
    #[serde(with = "serde_bytes")]
    pub binding_sig: Vec<u8>,
}

/// Output metadata for execution proof
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OutputMetadata {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size_bytes: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub storage_location: Option<String>,
}

/// Proof that a task was executed
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExecutionProof {
    /// Reference to capability token JTI
    pub task_jti: String,
    /// Binds proof to specific HTLC
    #[serde(with = "serde_bytes")]
    pub payment_hash: Vec<u8>,
    /// SHA256 of task output data
    #[serde(with = "serde_bytes")]
    pub output_hash: Vec<u8>,
    /// When the task was executed
    pub execution_timestamp: Timestamp,
    /// Optional metadata about the output
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_metadata: Option<OutputMetadata>,
    /// Signature over proof hash
    #[serde(with = "serde_bytes")]
    pub executor_sig: Vec<u8>,
}

/// Dispute message for settlement conflicts
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DisputeMessage {
    /// Reference to capability token
    pub task_jti: String,
    /// Payment hash being disputed
    #[serde(with = "serde_bytes")]
    pub payment_hash: Vec<u8>,
    /// Type of dispute
    pub dispute_type: String,
    /// Evidence supporting the dispute
    pub evidence: DisputeEvidence,
    /// Dispute submission timestamp
    pub timestamp: Timestamp,
    /// Signature by disputing party
    #[serde(with = "serde_bytes")]
    pub signature: Vec<u8>,
}

/// Evidence for a dispute
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DisputeEvidence {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub invalid_proof_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expected_output_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_sample: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub validation_failure_reason: Option<String>,
}

/// Task response status
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TaskStatus {
    Accepted,
    Rejected,
    Completed,
    Failed,
}

/// Response to a task request
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TaskResponse {
    pub task_jti: String,
    pub status: TaskStatus,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub proof: Option<ExecutionProof>,
    pub timestamp: Timestamp,
    #[serde(with = "serde_bytes")]
    pub signature: Vec<u8>,
}

/// ISL message types
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MessageType {
    TaskRequest,
    TaskResponse,
    Proof,
    Dispute,
    Lightning,
    Heartbeat,
}

/// ISL-encapsulated SCAP message
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct IslScapMessage {
    pub version: u32,
    pub msg_type: MessageType,
    pub sender: String,
    pub recipient: String,
    pub sequence: u64,
    pub timestamp: Timestamp,
    pub payload: ScapPayload,
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(with = "optional_bytes")]
    pub hmac: Option<Vec<u8>>,
}

/// SCAP message payload variants
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ScapPayload {
    TaskRequest(BoundTaskRequest),
    TaskResponse(TaskResponse),
    Proof(ExecutionProof),
    Dispute(DisputeMessage),
    Heartbeat(Heartbeat),
}

/// Channel state for heartbeat
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChannelState {
    #[serde(with = "serde_bytes")]
    pub channel_id: Vec<u8>,
    pub local_balance_msat: u64,
    pub remote_balance_msat: u64,
    pub pending_htlcs: u32,
    pub state: String,
}

/// Heartbeat message for connection liveness
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Heartbeat {
    pub sender: String,
    pub timestamp: Timestamp,
    pub channel_states: Vec<ChannelState>,
    pub pending_htlcs: u32,
    pub queue_depth: u32,
}

mod serde_bytes {
    use alloc::vec::Vec;
    use serde::{Deserializer, Serializer};

    pub fn serialize<S>(bytes: &Vec<u8>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_bytes(bytes)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Vec<u8>, D::Error>
    where
        D: Deserializer<'de>,
    {
        serde::Deserialize::deserialize(deserializer)
    }
}

mod optional_bytes {
    use alloc::vec::Vec;
    use serde::{Deserializer, Serializer};

    pub fn serialize<S>(bytes: &Option<Vec<u8>>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match bytes {
            Some(b) => serializer.serialize_bytes(b),
            None => serializer.serialize_none(),
        }
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<Vec<u8>>, D::Error>
    where
        D: Deserializer<'de>,
    {
        serde::Deserialize::deserialize(deserializer)
    }
}
