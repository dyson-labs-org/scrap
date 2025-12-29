//! C FFI bindings for SCAP protocol

use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::ptr;
use std::slice;

use scap_core::{
    CapabilityToken, CapabilityTokenBuilder, TokenValidator, Constraints,
    sha256, sign_message, verify_signature, derive_public_key,
    compute_binding_hash, compute_proof_hash,
    encode_capability_token, decode_capability_token,
    capability_matches, ScapError,
};

/// Error codes matching scap.h
#[repr(i32)]
pub enum ScapErrorCode {
    Ok = 0,
    NullPointer = -1,
    InvalidKey = -2,
    InvalidSignature = -3,
    VerificationFailed = -4,
    CborEncode = -5,
    CborDecode = -6,
    TokenExpired = -7,
    TokenNotValidYet = -8,
    InvalidCapability = -9,
    BufferTooSmall = -10,
    Internal = -99,
}

impl From<ScapError> for ScapErrorCode {
    fn from(e: ScapError) -> Self {
        match e {
            ScapError::InvalidPrivateKey | ScapError::InvalidPublicKey => ScapErrorCode::InvalidKey,
            ScapError::InvalidSignature => ScapErrorCode::InvalidSignature,
            ScapError::VerificationFailed => ScapErrorCode::VerificationFailed,
            ScapError::CborEncode(_) => ScapErrorCode::CborEncode,
            ScapError::CborDecode(_) => ScapErrorCode::CborDecode,
            ScapError::TokenExpired => ScapErrorCode::TokenExpired,
            ScapError::TokenNotYetValid => ScapErrorCode::TokenNotValidYet,
            ScapError::InvalidCapability(_) => ScapErrorCode::InvalidCapability,
            _ => ScapErrorCode::Internal,
        }
    }
}

/// Byte buffer for FFI
#[repr(C)]
pub struct ScapBuffer {
    pub data: *mut u8,
    pub len: usize,
}

impl ScapBuffer {
    fn from_vec(v: Vec<u8>) -> Self {
        let mut v = v.into_boxed_slice();
        let data = v.as_mut_ptr();
        let len = v.len();
        std::mem::forget(v);
        ScapBuffer { data, len }
    }

    fn null() -> Self {
        ScapBuffer { data: ptr::null_mut(), len: 0 }
    }
}

/// Free a buffer allocated by SCAP functions
#[no_mangle]
pub extern "C" fn scap_buffer_free(buf: *mut ScapBuffer) {
    if buf.is_null() {
        return;
    }
    unsafe {
        let buf = &mut *buf;
        if !buf.data.is_null() && buf.len > 0 {
            let _ = Vec::from_raw_parts(buf.data, buf.len, buf.len);
        }
        buf.data = ptr::null_mut();
        buf.len = 0;
    }
}

// ============================================================================
// Cryptographic Functions
// ============================================================================

/// Compute SHA-256 hash
#[no_mangle]
pub extern "C" fn scap_sha256(
    data: *const u8,
    data_len: usize,
    hash_out: *mut u8,
) -> i32 {
    if data.is_null() || hash_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let data = unsafe { slice::from_raw_parts(data, data_len) };
    let hash = sha256(data);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScapErrorCode::Ok as i32
}

/// Derive public key from private key
#[no_mangle]
pub extern "C" fn scap_derive_public_key(
    private_key: *const u8,
    public_key_out: *mut u8,
) -> i32 {
    if private_key.is_null() || public_key_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };

    match derive_public_key(privkey) {
        Ok(pubkey) => {
            unsafe {
                ptr::copy_nonoverlapping(pubkey.as_ptr(), public_key_out, 33);
            }
            ScapErrorCode::Ok as i32
        }
        Err(e) => ScapErrorCode::from(e) as i32,
    }
}

/// Sign a message
#[no_mangle]
pub extern "C" fn scap_sign(
    private_key: *const u8,
    message: *const u8,
    message_len: usize,
    signature_out: *mut ScapBuffer,
) -> i32 {
    if private_key.is_null() || message.is_null() || signature_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };
    let msg = unsafe { slice::from_raw_parts(message, message_len) };

    match sign_message(privkey, msg) {
        Ok(sig) => {
            unsafe {
                *signature_out = ScapBuffer::from_vec(sig);
            }
            ScapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe {
                *signature_out = ScapBuffer::null();
            }
            ScapErrorCode::from(e) as i32
        }
    }
}

/// Verify a signature
#[no_mangle]
pub extern "C" fn scap_verify(
    public_key: *const u8,
    message: *const u8,
    message_len: usize,
    signature: *const u8,
    signature_len: usize,
    valid_out: *mut bool,
) -> i32 {
    if public_key.is_null() || message.is_null() || signature.is_null() || valid_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let pubkey = unsafe { slice::from_raw_parts(public_key, 33) };
    let msg = unsafe { slice::from_raw_parts(message, message_len) };
    let sig = unsafe { slice::from_raw_parts(signature, signature_len) };

    match verify_signature(pubkey, msg, sig) {
        Ok(valid) => {
            unsafe { *valid_out = valid; }
            ScapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *valid_out = false; }
            ScapErrorCode::from(e) as i32
        }
    }
}

// ============================================================================
// Token Builder
// ============================================================================

/// Opaque token builder handle
pub struct ScapTokenBuilder {
    issuer: String,
    subject: String,
    audience: String,
    jti: String,
    capabilities: Vec<String>,
    issued_at: u64,
    expires_at: u64,
    constraints: Option<Constraints>,
    parent_jti: Option<String>,
    chain_depth: Option<u32>,
}

/// Create a new token builder
#[no_mangle]
pub extern "C" fn scap_token_builder_new(
    issuer: *const c_char,
    subject: *const c_char,
    audience: *const c_char,
    jti: *const c_char,
) -> *mut ScapTokenBuilder {
    if issuer.is_null() || subject.is_null() || audience.is_null() || jti.is_null() {
        return ptr::null_mut();
    }

    let issuer = match unsafe { CStr::from_ptr(issuer) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ptr::null_mut(),
    };
    let subject = match unsafe { CStr::from_ptr(subject) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ptr::null_mut(),
    };
    let audience = match unsafe { CStr::from_ptr(audience) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ptr::null_mut(),
    };
    let jti = match unsafe { CStr::from_ptr(jti) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ptr::null_mut(),
    };

    Box::into_raw(Box::new(ScapTokenBuilder {
        issuer,
        subject,
        audience,
        jti,
        capabilities: Vec::new(),
        issued_at: 0,
        expires_at: 0,
        constraints: None,
        parent_jti: None,
        chain_depth: None,
    }))
}

/// Free a token builder
#[no_mangle]
pub extern "C" fn scap_token_builder_free(builder: *mut ScapTokenBuilder) {
    if !builder.is_null() {
        unsafe { drop(Box::from_raw(builder)); }
    }
}

/// Add a capability to the token
#[no_mangle]
pub extern "C" fn scap_token_builder_add_capability(
    builder: *mut ScapTokenBuilder,
    capability: *const c_char,
) -> i32 {
    if builder.is_null() || capability.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let cap = match unsafe { CStr::from_ptr(capability) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ScapErrorCode::InvalidCapability as i32,
    };

    unsafe {
        (*builder).capabilities.push(cap);
    }

    ScapErrorCode::Ok as i32
}

/// Set token validity window
#[no_mangle]
pub extern "C" fn scap_token_builder_set_validity(
    builder: *mut ScapTokenBuilder,
    issued_at: u64,
    expires_at: u64,
) -> i32 {
    if builder.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    unsafe {
        (*builder).issued_at = issued_at;
        (*builder).expires_at = expires_at;
    }

    ScapErrorCode::Ok as i32
}

/// Set maximum area constraint
#[no_mangle]
pub extern "C" fn scap_token_builder_set_max_area(
    builder: *mut ScapTokenBuilder,
    max_area_km2: u64,
) -> i32 {
    if builder.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    unsafe {
        let b = &mut *builder;
        let constraints = b.constraints.get_or_insert_with(Constraints::default);
        constraints.max_area_km2 = Some(max_area_km2);
    }

    ScapErrorCode::Ok as i32
}

/// Set maximum hops constraint
#[no_mangle]
pub extern "C" fn scap_token_builder_set_max_hops(
    builder: *mut ScapTokenBuilder,
    max_hops: u32,
) -> i32 {
    if builder.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    unsafe {
        let b = &mut *builder;
        let constraints = b.constraints.get_or_insert_with(Constraints::default);
        constraints.max_hops = Some(max_hops);
    }

    ScapErrorCode::Ok as i32
}

/// Set as delegation token
#[no_mangle]
pub extern "C" fn scap_token_builder_set_delegation(
    builder: *mut ScapTokenBuilder,
    parent_jti: *const c_char,
    chain_depth: u32,
) -> i32 {
    if builder.is_null() || parent_jti.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let parent = match unsafe { CStr::from_ptr(parent_jti) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ScapErrorCode::InvalidCapability as i32,
    };

    unsafe {
        (*builder).parent_jti = Some(parent);
        (*builder).chain_depth = Some(chain_depth);
    }

    ScapErrorCode::Ok as i32
}

/// Build and sign the token
#[no_mangle]
pub extern "C" fn scap_token_builder_sign(
    builder: *mut ScapTokenBuilder,
    private_key: *const u8,
    token_out: *mut *mut ScapToken,
) -> i32 {
    if builder.is_null() || private_key.is_null() || token_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let b = unsafe { Box::from_raw(builder) };
    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };

    let mut token_builder = CapabilityTokenBuilder::new(
        b.issuer,
        b.subject,
        b.audience,
        b.jti,
        b.capabilities,
    )
    .issued_at(b.issued_at)
    .expires_at(b.expires_at);

    if let Some(constraints) = b.constraints {
        token_builder = token_builder.with_constraints(constraints);
    }

    if let Some(parent) = b.parent_jti {
        token_builder = token_builder.delegated_from(parent);
    }

    if let Some(depth) = b.chain_depth {
        token_builder = token_builder.chain_depth(depth);
    }

    match token_builder.sign(privkey) {
        Ok(token) => {
            let token_ptr = Box::into_raw(Box::new(ScapToken { inner: token }));
            unsafe { *token_out = token_ptr; }
            ScapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *token_out = ptr::null_mut(); }
            ScapErrorCode::from(e) as i32
        }
    }
}

// ============================================================================
// Token Operations
// ============================================================================

/// Opaque token handle
pub struct ScapToken {
    inner: CapabilityToken,
}

/// Free a token
#[no_mangle]
pub extern "C" fn scap_token_free(token: *mut ScapToken) {
    if !token.is_null() {
        unsafe { drop(Box::from_raw(token)); }
    }
}

/// Decode a token from CBOR bytes
#[no_mangle]
pub extern "C" fn scap_token_decode(
    cbor_data: *const u8,
    cbor_len: usize,
    token_out: *mut *mut ScapToken,
) -> i32 {
    if cbor_data.is_null() || token_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let data = unsafe { slice::from_raw_parts(cbor_data, cbor_len) };

    match decode_capability_token(data) {
        Ok(token) => {
            let token_ptr = Box::into_raw(Box::new(ScapToken { inner: token }));
            unsafe { *token_out = token_ptr; }
            ScapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *token_out = ptr::null_mut(); }
            ScapErrorCode::from(e) as i32
        }
    }
}

/// Encode a token to CBOR bytes
#[no_mangle]
pub extern "C" fn scap_token_encode(
    token: *const ScapToken,
    cbor_out: *mut ScapBuffer,
) -> i32 {
    if token.is_null() || cbor_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };

    match encode_capability_token(&token.inner) {
        Ok(data) => {
            unsafe { *cbor_out = ScapBuffer::from_vec(data); }
            ScapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *cbor_out = ScapBuffer::null(); }
            ScapErrorCode::from(e) as i32
        }
    }
}

/// Validate a token
#[no_mangle]
pub extern "C" fn scap_token_validate(
    token: *const ScapToken,
    current_time: u64,
    issuer_pubkey: *const u8,
) -> i32 {
    if token.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };

    let mut validator = TokenValidator::new(&token.inner);

    if current_time > 0 {
        validator = validator.at_time(current_time);
    }

    if !issuer_pubkey.is_null() {
        let pubkey = unsafe { slice::from_raw_parts(issuer_pubkey, 33) };
        validator = validator.with_issuer_key(pubkey);
    }

    match validator.validate() {
        Ok(()) => ScapErrorCode::Ok as i32,
        Err(e) => ScapErrorCode::from(e) as i32,
    }
}

/// Get token JTI
#[no_mangle]
pub extern "C" fn scap_token_get_jti(
    token: *const ScapToken,
    jti_out: *mut c_char,
    jti_len: usize,
) -> i32 {
    if token.is_null() || jti_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    let jti = &token.inner.payload.jti;

    if jti.len() + 1 > jti_len {
        return ScapErrorCode::BufferTooSmall as i32;
    }

    let c_str = match CString::new(jti.as_str()) {
        Ok(s) => s,
        Err(_) => return ScapErrorCode::Internal as i32,
    };

    unsafe {
        ptr::copy_nonoverlapping(c_str.as_ptr(), jti_out, jti.len() + 1);
    }

    ScapErrorCode::Ok as i32
}

/// Get token issuer
#[no_mangle]
pub extern "C" fn scap_token_get_issuer(
    token: *const ScapToken,
    issuer_out: *mut c_char,
    issuer_len: usize,
) -> i32 {
    if token.is_null() || issuer_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    let issuer = &token.inner.payload.iss;

    if issuer.len() + 1 > issuer_len {
        return ScapErrorCode::BufferTooSmall as i32;
    }

    let c_str = match CString::new(issuer.as_str()) {
        Ok(s) => s,
        Err(_) => return ScapErrorCode::Internal as i32,
    };

    unsafe {
        ptr::copy_nonoverlapping(c_str.as_ptr(), issuer_out, issuer.len() + 1);
    }

    ScapErrorCode::Ok as i32
}

/// Get token expiration time
#[no_mangle]
pub extern "C" fn scap_token_get_expiration(
    token: *const ScapToken,
    exp_out: *mut u64,
) -> i32 {
    if token.is_null() || exp_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    unsafe { *exp_out = token.inner.payload.exp; }

    ScapErrorCode::Ok as i32
}

// ============================================================================
// Capability Matching
// ============================================================================

/// Check if a granted capability authorizes a requested capability
#[no_mangle]
pub extern "C" fn scap_capability_matches(
    granted: *const c_char,
    requested: *const c_char,
) -> bool {
    if granted.is_null() || requested.is_null() {
        return false;
    }

    let granted_str = match unsafe { CStr::from_ptr(granted) }.to_str() {
        Ok(s) => s,
        Err(_) => return false,
    };

    let requested_str = match unsafe { CStr::from_ptr(requested) }.to_str() {
        Ok(s) => s,
        Err(_) => return false,
    };

    capability_matches(granted_str, requested_str)
}

// ============================================================================
// Binding and Proof Functions
// ============================================================================

/// Compute binding hash
#[no_mangle]
pub extern "C" fn scap_compute_binding_hash(
    jti: *const c_char,
    payment_hash: *const u8,
    hash_out: *mut u8,
) -> i32 {
    if jti.is_null() || payment_hash.is_null() || hash_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let jti_str = match unsafe { CStr::from_ptr(jti) }.to_str() {
        Ok(s) => s,
        Err(_) => return ScapErrorCode::Internal as i32,
    };

    let payment_hash = unsafe { slice::from_raw_parts(payment_hash, 32) };
    let hash = compute_binding_hash(jti_str, payment_hash);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScapErrorCode::Ok as i32
}

/// Compute proof hash
#[no_mangle]
pub extern "C" fn scap_compute_proof_hash(
    task_jti: *const c_char,
    payment_hash: *const u8,
    output_hash: *const u8,
    timestamp: u64,
    hash_out: *mut u8,
) -> i32 {
    if task_jti.is_null() || payment_hash.is_null() || output_hash.is_null() || hash_out.is_null() {
        return ScapErrorCode::NullPointer as i32;
    }

    let jti_str = match unsafe { CStr::from_ptr(task_jti) }.to_str() {
        Ok(s) => s,
        Err(_) => return ScapErrorCode::Internal as i32,
    };

    let payment_hash = unsafe { slice::from_raw_parts(payment_hash, 32) };
    let output_hash = unsafe { slice::from_raw_parts(output_hash, 32) };
    let hash = compute_proof_hash(jti_str, payment_hash, output_hash, timestamp);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScapErrorCode::Ok as i32
}

// ============================================================================
// Version Information
// ============================================================================

/// Get library version string
#[no_mangle]
pub extern "C" fn scap_version() -> *const c_char {
    static VERSION: &[u8] = b"1.0.0\0";
    VERSION.as_ptr() as *const c_char
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sha256_ffi() {
        let data = b"test";
        let mut hash = [0u8; 32];

        let result = scap_sha256(data.as_ptr(), data.len(), hash.as_mut_ptr());
        assert_eq!(result, 0);

        // Compare with known hash of "test"
        let expected = hex::decode("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08").unwrap();
        assert_eq!(hash.to_vec(), expected);
    }

    #[test]
    fn test_key_derivation_ffi() {
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];

        let result = scap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());
        assert_eq!(result, 0);
        assert_eq!(pubkey[0], 0x03); // Compressed key starts with 02 or 03
    }

    #[test]
    fn test_sign_verify_ffi() {
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];
        scap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());

        let message = b"test message";
        let mut signature = ScapBuffer::null();

        let result = scap_sign(privkey.as_ptr(), message.as_ptr(), message.len(), &mut signature);
        assert_eq!(result, 0);
        assert!(!signature.data.is_null());

        let mut valid = false;
        let result = scap_verify(
            pubkey.as_ptr(),
            message.as_ptr(),
            message.len(),
            signature.data,
            signature.len,
            &mut valid,
        );
        assert_eq!(result, 0);
        assert!(valid);

        scap_buffer_free(&mut signature);
    }

    #[test]
    fn test_token_builder_ffi() {
        let issuer = std::ffi::CString::new("OPERATOR").unwrap();
        let subject = std::ffi::CString::new("SAT-1").unwrap();
        let audience = std::ffi::CString::new("SAT-2").unwrap();
        let jti = std::ffi::CString::new("test-001").unwrap();
        let cap = std::ffi::CString::new("cmd:imaging:msi").unwrap();

        let builder = scap_token_builder_new(
            issuer.as_ptr(),
            subject.as_ptr(),
            audience.as_ptr(),
            jti.as_ptr(),
        );
        assert!(!builder.is_null());

        scap_token_builder_add_capability(builder, cap.as_ptr());
        scap_token_builder_set_validity(builder, 1705320000, 1705406400);
        scap_token_builder_set_max_area(builder, 1000);

        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];
        scap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());

        let mut token: *mut ScapToken = ptr::null_mut();
        let result = scap_token_builder_sign(builder, privkey.as_ptr(), &mut token);
        assert_eq!(result, 0);
        assert!(!token.is_null());

        // Validate the token
        let result = scap_token_validate(token, 1705320500, pubkey.as_ptr());
        assert_eq!(result, 0);

        // Get JTI
        let mut jti_buf = [0i8; 64];
        let result = scap_token_get_jti(token, jti_buf.as_mut_ptr(), 64);
        assert_eq!(result, 0);

        scap_token_free(token);
    }
}
