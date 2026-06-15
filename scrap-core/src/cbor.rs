//! CBOR encoding and decoding for SCRAP messages

use alloc::vec::Vec;
use ciborium::{de, ser};
use serde::{de::DeserializeOwned, Serialize};
use crate::error::ScrapError;
use crate::types::*;

/// Encode a value to CBOR bytes
pub fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, ScrapError> {
    let mut buf = Vec::new();
    ser::into_writer(value, &mut buf)
        .map_err(|e| ScrapError::CborEncode(alloc::format!("{}", e)))?;
    Ok(buf)
}

/// Decode CBOR bytes to a value
pub fn decode<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, ScrapError> {
    de::from_reader(bytes)
        .map_err(|e| ScrapError::CborDecode(alloc::format!("{}", e)))
}

/// Encode a capability token header
pub fn encode_header(header: &CapHeader) -> Result<Vec<u8>, ScrapError> {
    encode(header)
}

/// Encode a capability token payload
pub fn encode_payload(payload: &CapPayload) -> Result<Vec<u8>, ScrapError> {
    encode(payload)
}

/// Decode a capability token header
pub fn decode_header(bytes: &[u8]) -> Result<CapHeader, ScrapError> {
    decode(bytes)
}

/// Decode a capability token payload
pub fn decode_payload(bytes: &[u8]) -> Result<CapPayload, ScrapError> {
    decode(bytes)
}

/// Wire representation of a capability token: `{ protected: bstr, signature: bstr }`.
/// The `protected` byte string is the verbatim signed content, carried unchanged
/// so verification never re-serializes a parsed structure.
#[derive(serde::Serialize, serde::Deserialize)]
struct CapabilityTokenWire {
    #[serde(with = "wire_bytes")]
    protected: Vec<u8>,
    #[serde(with = "wire_bytes")]
    signature: Vec<u8>,
}

mod wire_bytes {
    use alloc::vec::Vec;
    use serde::{Deserializer, Serializer};
    pub fn serialize<S: Serializer>(bytes: &Vec<u8>, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_bytes(bytes)
    }
    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<u8>, D::Error> {
        serde::Deserialize::deserialize(d)
    }
}

/// Encode the protected content (the signed bytes) of a capability token.
pub fn encode_protected_content(content: &ProtectedContent) -> Result<Vec<u8>, ScrapError> {
    encode(content)
}

/// Encode a complete capability token to its wire form `{ protected, signature }`.
pub fn encode_capability_token(token: &CapabilityToken) -> Result<Vec<u8>, ScrapError> {
    let wire = CapabilityTokenWire {
        protected: token.protected.clone(),
        signature: token.signature.clone(),
    };
    encode(&wire)
}

/// Decode a complete capability token from its wire form. The `protected` bytes
/// are retained verbatim (for signature verification) and also parsed into
/// `header`/`payload` for inspection.
pub fn decode_capability_token(bytes: &[u8]) -> Result<CapabilityToken, ScrapError> {
    let wire: CapabilityTokenWire = decode(bytes)?;
    let content: ProtectedContent = decode(&wire.protected)?;
    Ok(CapabilityToken {
        header: content.header,
        payload: content.payload,
        protected: wire.protected,
        signature: wire.signature,
    })
}

/// Encode a bound task request
pub fn encode_task_request(request: &BoundTaskRequest) -> Result<Vec<u8>, ScrapError> {
    encode(request)
}

/// Decode a bound task request
pub fn decode_task_request(bytes: &[u8]) -> Result<BoundTaskRequest, ScrapError> {
    decode(bytes)
}

/// Encode an execution proof
pub fn encode_execution_proof(proof: &ExecutionProof) -> Result<Vec<u8>, ScrapError> {
    encode(proof)
}

/// Decode an execution proof
pub fn decode_execution_proof(bytes: &[u8]) -> Result<ExecutionProof, ScrapError> {
    decode(bytes)
}

/// Encode a task response
pub fn encode_task_response(response: &TaskResponse) -> Result<Vec<u8>, ScrapError> {
    encode(response)
}

/// Decode a task response
pub fn decode_task_response(bytes: &[u8]) -> Result<TaskResponse, ScrapError> {
    decode(bytes)
}

/// Encode an ISL SCRAP message
pub fn encode_isl_message(message: &IslScrapMessage) -> Result<Vec<u8>, ScrapError> {
    encode(message)
}

/// Decode an ISL SCRAP message
pub fn decode_isl_message(bytes: &[u8]) -> Result<IslScrapMessage, ScrapError> {
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
        let content = ProtectedContent {
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
        };
        let protected = encode_protected_content(&content).unwrap();
        let token = CapabilityToken {
            header: content.header.clone(),
            payload: content.payload.clone(),
            protected,
            signature: vec![0u8; 71],
        };
        let encoded = encode_capability_token(&token).unwrap();
        let decoded = decode_capability_token(&encoded).unwrap();
        assert_eq!(token, decoded);
    }

    #[test]
    fn test_protected_content_reencode_is_stable() {
        // Verification uses the verbatim `protected` bytes, so it no longer depends
        // on canonical CBOR (C1 fixed). This test still guards that THIS encoder is
        // self-consistent (decode→re-encode is byte-identical), which keeps token
        // re-emission stable across a round-trip.
        let payload = CapPayload {
            iss: String::from("OPERATOR-A"),
            sub: String::from("SAT-RELAY"),
            aud: String::from("SAT-EXEC"),
            iat: 1705320000,
            exp: 1705406400,
            jti: String::from("job-inf-2026-0042"),
            cap: vec![String::from("cmd:compute:inference")],
            cns: None,
            prf: None,
            cmd_pub: None,
        };
        let header = CapHeader::default();

        let h1 = encode_header(&header).unwrap();
        let p1 = encode_payload(&payload).unwrap();

        // decode then re-encode; bytes must be identical
        let header2: CapHeader = decode_header(&h1).unwrap();
        let payload2: CapPayload = decode_payload(&p1).unwrap();
        assert_eq!(h1, encode_header(&header2).unwrap(), "header re-encode not byte-identical");
        assert_eq!(p1, encode_payload(&payload2).unwrap(), "payload re-encode not byte-identical");
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
