//! CBOR encoding and decoding for SCAP messages

use alloc::vec::Vec;
use ciborium::{de, ser};
use serde::{de::DeserializeOwned, Serialize};
use crate::error::ScapError;
use crate::types::*;

/// Encode a value to CBOR bytes
pub fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, ScapError> {
    let mut buf = Vec::new();
    ser::into_writer(value, &mut buf)
        .map_err(|e| ScapError::CborEncode(alloc::format!("{}", e)))?;
    Ok(buf)
}

/// Decode CBOR bytes to a value
pub fn decode<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, ScapError> {
    de::from_reader(bytes)
        .map_err(|e| ScapError::CborDecode(alloc::format!("{}", e)))
}

/// Encode a capability token header
pub fn encode_header(header: &CapHeader) -> Result<Vec<u8>, ScapError> {
    encode(header)
}

/// Encode a capability token payload
pub fn encode_payload(payload: &CapPayload) -> Result<Vec<u8>, ScapError> {
    encode(payload)
}

/// Decode a capability token header
pub fn decode_header(bytes: &[u8]) -> Result<CapHeader, ScapError> {
    decode(bytes)
}

/// Decode a capability token payload
pub fn decode_payload(bytes: &[u8]) -> Result<CapPayload, ScapError> {
    decode(bytes)
}

/// Encode a complete capability token
pub fn encode_capability_token(token: &CapabilityToken) -> Result<Vec<u8>, ScapError> {
    encode(token)
}

/// Decode a complete capability token
pub fn decode_capability_token(bytes: &[u8]) -> Result<CapabilityToken, ScapError> {
    decode(bytes)
}

/// Encode a bound task request
pub fn encode_task_request(request: &BoundTaskRequest) -> Result<Vec<u8>, ScapError> {
    encode(request)
}

/// Decode a bound task request
pub fn decode_task_request(bytes: &[u8]) -> Result<BoundTaskRequest, ScapError> {
    decode(bytes)
}

/// Encode an execution proof
pub fn encode_execution_proof(proof: &ExecutionProof) -> Result<Vec<u8>, ScapError> {
    encode(proof)
}

/// Decode an execution proof
pub fn decode_execution_proof(bytes: &[u8]) -> Result<ExecutionProof, ScapError> {
    decode(bytes)
}

/// Encode a task response
pub fn encode_task_response(response: &TaskResponse) -> Result<Vec<u8>, ScapError> {
    encode(response)
}

/// Decode a task response
pub fn decode_task_response(bytes: &[u8]) -> Result<TaskResponse, ScapError> {
    decode(bytes)
}

/// Encode an ISL SCAP message
pub fn encode_isl_message(message: &IslScapMessage) -> Result<Vec<u8>, ScapError> {
    encode(message)
}

/// Decode an ISL SCAP message
pub fn decode_isl_message(bytes: &[u8]) -> Result<IslScapMessage, ScapError> {
    decode(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::string::String;
    use alloc::vec;

    #[test]
    fn test_header_roundtrip() {
        let header = CapHeader::default();
        let encoded = encode_header(&header).unwrap();
        let decoded: CapHeader = decode_header(&encoded).unwrap();
        assert_eq!(header, decoded);
    }

    #[test]
    fn test_payload_roundtrip() {
        let payload = CapPayload {
            iss: String::from("OPERATOR-TEST"),
            sub: String::from("SATELLITE-1"),
            aud: String::from("SATELLITE-2"),
            iat: 1705320000,
            exp: 1705406400,
            jti: String::from("test-001"),
            cap: vec![String::from("cmd:imaging:msi")],
            cns: None,
            prf: None,
            cmd_pub: None,
        };
        let encoded = encode_payload(&payload).unwrap();
        let decoded: CapPayload = decode_payload(&encoded).unwrap();
        assert_eq!(payload, decoded);
    }

    #[test]
    fn test_capability_token_roundtrip() {
        let token = CapabilityToken {
            header: CapHeader::default(),
            payload: CapPayload {
                iss: String::from("OPERATOR-TEST"),
                sub: String::from("SATELLITE-1"),
                aud: String::from("SATELLITE-2"),
                iat: 1705320000,
                exp: 1705406400,
                jti: String::from("test-001"),
                cap: vec![String::from("cmd:imaging:msi")],
                cns: None,
                prf: None,
                cmd_pub: None,
            },
            signature: vec![0u8; 71],
        };
        let encoded = encode_capability_token(&token).unwrap();
        let decoded = decode_capability_token(&encoded).unwrap();
        assert_eq!(token, decoded);
    }

    #[test]
    fn test_execution_proof_roundtrip() {
        let proof = ExecutionProof {
            task_jti: String::from("test-001"),
            payment_hash: vec![0u8; 32],
            output_hash: vec![0u8; 32],
            execution_timestamp: 1705321000,
            output_metadata: None,
            executor_sig: vec![0u8; 71],
        };
        let encoded = encode_execution_proof(&proof).unwrap();
        let decoded = decode_execution_proof(&encoded).unwrap();
        assert_eq!(proof, decoded);
    }
}
