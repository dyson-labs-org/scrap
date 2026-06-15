//! C FFI bindings for SCRAP protocol

use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::ptr;
use std::slice;

use scrap_core::{
    CapabilityToken, CapabilityTokenBuilder, TokenValidator, Constraints,
    sha256, sign_message, verify_signature, derive_public_key,
    compute_binding_hash, compute_proof_hash,
    encode_capability_token, decode_capability_token,
    capability_matches, ScrapError,
};

/// Error codes matching scrap.h
#[repr(i32)]
pub enum ScrapErrorCode {
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

impl From<ScrapError> for ScrapErrorCode {
    fn from(e: ScrapError) -> Self {
        match e {
            ScrapError::InvalidPrivateKey | ScrapError::InvalidPublicKey => ScrapErrorCode::InvalidKey,
            ScrapError::InvalidSignature => ScrapErrorCode::InvalidSignature,
            ScrapError::VerificationFailed => ScrapErrorCode::VerificationFailed,
            ScrapError::CborEncode(_) => ScrapErrorCode::CborEncode,
            ScrapError::CborDecode(_) => ScrapErrorCode::CborDecode,
            ScrapError::TokenExpired => ScrapErrorCode::TokenExpired,
            ScrapError::TokenNotYetValid => ScrapErrorCode::TokenNotValidYet,
            ScrapError::InvalidCapability(_) => ScrapErrorCode::InvalidCapability,
            _ => ScrapErrorCode::Internal,
        }
    }
}

/// Byte buffer for FFI
#[repr(C)]
pub struct ScrapBuffer {
    pub data: *mut u8,
    pub len: usize,
}

impl ScrapBuffer {
    fn from_vec(v: Vec<u8>) -> Self {
        let mut v = v.into_boxed_slice();
        let data = v.as_mut_ptr();
        let len = v.len();
        std::mem::forget(v);
        ScrapBuffer { data, len }
    }

    fn null() -> Self {
        ScrapBuffer { data: ptr::null_mut(), len: 0 }
    }
}

/// Free a buffer allocated by SCRAP functions
#[no_mangle]
pub extern "C" fn scrap_buffer_free(buf: *mut ScrapBuffer) {
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
pub extern "C" fn scrap_sha256(
    data: *const u8,
    data_len: usize,
    hash_out: *mut u8,
) -> i32 {
    if data.is_null() || hash_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let data = unsafe { slice::from_raw_parts(data, data_len) };
    let hash = sha256(data);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScrapErrorCode::Ok as i32
}

/// Derive public key from private key
#[no_mangle]
pub extern "C" fn scrap_derive_public_key(
    private_key: *const u8,
    public_key_out: *mut u8,
) -> i32 {
    if private_key.is_null() || public_key_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };

    match derive_public_key(privkey) {
        Ok(pubkey) => {
            unsafe {
                ptr::copy_nonoverlapping(pubkey.as_ptr(), public_key_out, 33);
            }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => ScrapErrorCode::from(e) as i32,
    }
}

/// Sign a message
#[no_mangle]
pub extern "C" fn scrap_sign(
    private_key: *const u8,
    message: *const u8,
    message_len: usize,
    signature_out: *mut ScrapBuffer,
) -> i32 {
    if private_key.is_null() || message.is_null() || signature_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };
    let msg = unsafe { slice::from_raw_parts(message, message_len) };

    match sign_message(privkey, msg) {
        Ok(sig) => {
            unsafe {
                *signature_out = ScrapBuffer::from_vec(sig);
            }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe {
                *signature_out = ScrapBuffer::null();
            }
            ScrapErrorCode::from(e) as i32
        }
    }
}

/// Verify a signature
#[no_mangle]
pub extern "C" fn scrap_verify(
    public_key: *const u8,
    message: *const u8,
    message_len: usize,
    signature: *const u8,
    signature_len: usize,
    valid_out: *mut bool,
) -> i32 {
    if public_key.is_null() || message.is_null() || signature.is_null() || valid_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let pubkey = unsafe { slice::from_raw_parts(public_key, 33) };
    let msg = unsafe { slice::from_raw_parts(message, message_len) };
    let sig = unsafe { slice::from_raw_parts(signature, signature_len) };

    match verify_signature(pubkey, msg, sig) {
        Ok(valid) => {
            unsafe { *valid_out = valid; }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *valid_out = false; }
            ScrapErrorCode::from(e) as i32
        }
    }
}

// ============================================================================
// Signer (opaque) — keeps private keys out of this library when desired
// ============================================================================

/// Host-provided signing callback. Receives a 32-byte `digest`, writes a
/// DER-encoded ECDSA signature into `sig_out` (capacity `sig_cap`), sets
/// `*sig_len_out` to the bytes written, and returns 0 on success (nonzero = fail).
/// `ctx` is the opaque pointer passed to `scrap_signer_from_callback`.
pub type ScrapSignCallback = extern "C" fn(
    ctx: *mut std::ffi::c_void,
    digest: *const u8,
    sig_out: *mut u8,
    sig_cap: usize,
    sig_len_out: *mut usize,
) -> i32;

struct CallbackSigner {
    cb: ScrapSignCallback,
    ctx: *mut std::ffi::c_void,
}

impl scrap_core::Signer for CallbackSigner {
    fn sign_digest(&self, digest: &[u8; 32]) -> Result<Vec<u8>, ScrapError> {
        let mut buf = [0u8; 80]; // DER secp256k1 sig is <= 72 bytes
        let mut len: usize = 0;
        let rc = (self.cb)(self.ctx, digest.as_ptr(), buf.as_mut_ptr(), buf.len(), &mut len);
        if rc != 0 || len == 0 || len > buf.len() {
            return Err(ScrapError::InvalidSignature);
        }
        Ok(buf[..len].to_vec())
    }
}

/// Opaque signer handle. Free with `scrap_signer_free`.
pub struct ScrapSigner {
    inner: Box<dyn scrap_core::Signer>,
}

/// Create a signer that holds a raw 32-byte private key in-process (zeroized on free).
#[no_mangle]
pub extern "C" fn scrap_signer_from_key(private_key: *const u8) -> *mut ScrapSigner {
    if private_key.is_null() {
        return ptr::null_mut();
    }
    let pk = unsafe { slice::from_raw_parts(private_key, 32) };
    match scrap_core::KeySigner::from_slice(pk) {
        Ok(s) => Box::into_raw(Box::new(ScrapSigner { inner: Box::new(s) })),
        Err(_) => ptr::null_mut(),
    }
}

/// Create a signer that delegates to a host callback (HSM / secure element /
/// signing daemon). The private key never enters this library's memory.
#[no_mangle]
pub extern "C" fn scrap_signer_from_callback(
    cb: ScrapSignCallback,
    ctx: *mut std::ffi::c_void,
) -> *mut ScrapSigner {
    Box::into_raw(Box::new(ScrapSigner { inner: Box::new(CallbackSigner { cb, ctx }) }))
}

/// Free a signer.
#[no_mangle]
pub extern "C" fn scrap_signer_free(signer: *mut ScrapSigner) {
    if !signer.is_null() {
        unsafe { drop(Box::from_raw(signer)); }
    }
}

// ============================================================================
// Token Builder
// ============================================================================

/// Opaque token builder handle
pub struct ScrapTokenBuilder {
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
pub extern "C" fn scrap_token_builder_new(
    issuer: *const c_char,
    subject: *const c_char,
    audience: *const c_char,
    jti: *const c_char,
) -> *mut ScrapTokenBuilder {
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

    Box::into_raw(Box::new(ScrapTokenBuilder {
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
pub extern "C" fn scrap_token_builder_free(builder: *mut ScrapTokenBuilder) {
    if !builder.is_null() {
        unsafe { drop(Box::from_raw(builder)); }
    }
}

/// Add a capability to the token
#[no_mangle]
pub extern "C" fn scrap_token_builder_add_capability(
    builder: *mut ScrapTokenBuilder,
    capability: *const c_char,
) -> i32 {
    if builder.is_null() || capability.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let cap = match unsafe { CStr::from_ptr(capability) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ScrapErrorCode::InvalidCapability as i32,
    };

    unsafe {
        (*builder).capabilities.push(cap);
    }

    ScrapErrorCode::Ok as i32
}

/// Set token validity window
#[no_mangle]
pub extern "C" fn scrap_token_builder_set_validity(
    builder: *mut ScrapTokenBuilder,
    issued_at: u64,
    expires_at: u64,
) -> i32 {
    if builder.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    unsafe {
        (*builder).issued_at = issued_at;
        (*builder).expires_at = expires_at;
    }

    ScrapErrorCode::Ok as i32
}

/// Set maximum area constraint
#[no_mangle]
pub extern "C" fn scrap_token_builder_set_max_area(
    builder: *mut ScrapTokenBuilder,
    max_area_km2: u64,
) -> i32 {
    if builder.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    unsafe {
        let b = &mut *builder;
        let constraints = b.constraints.get_or_insert_with(Constraints::default);
        constraints.max_area_km2 = Some(max_area_km2);
    }

    ScrapErrorCode::Ok as i32
}

/// Set maximum hops constraint
#[no_mangle]
pub extern "C" fn scrap_token_builder_set_max_hops(
    builder: *mut ScrapTokenBuilder,
    max_hops: u32,
) -> i32 {
    if builder.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    unsafe {
        let b = &mut *builder;
        let constraints = b.constraints.get_or_insert_with(Constraints::default);
        constraints.max_hops = Some(max_hops);
    }

    ScrapErrorCode::Ok as i32
}

/// Set as delegation token
#[no_mangle]
pub extern "C" fn scrap_token_builder_set_delegation(
    builder: *mut ScrapTokenBuilder,
    parent_jti: *const c_char,
    chain_depth: u32,
) -> i32 {
    if builder.is_null() || parent_jti.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let parent = match unsafe { CStr::from_ptr(parent_jti) }.to_str() {
        Ok(s) => s.to_string(),
        Err(_) => return ScrapErrorCode::InvalidCapability as i32,
    };

    unsafe {
        (*builder).parent_jti = Some(parent);
        (*builder).chain_depth = Some(chain_depth);
    }

    ScrapErrorCode::Ok as i32
}

/// Reconstruct the core builder from the FFI builder box (consumes it).
fn core_builder_from(b: Box<ScrapTokenBuilder>) -> CapabilityTokenBuilder {
    let mut tb = CapabilityTokenBuilder::new(b.issuer, b.subject, b.audience, b.jti, b.capabilities)
        .issued_at(b.issued_at)
        .expires_at(b.expires_at);
    if let Some(constraints) = b.constraints {
        tb = tb.with_constraints(constraints);
    }
    if let Some(parent) = b.parent_jti {
        tb = tb.delegated_from(parent);
    }
    if let Some(depth) = b.chain_depth {
        tb = tb.chain_depth(depth);
    }
    tb
}

fn finish_sign(result: Result<CapabilityToken, ScrapError>, token_out: *mut *mut ScrapToken) -> i32 {
    match result {
        Ok(token) => {
            unsafe { *token_out = Box::into_raw(Box::new(ScrapToken { inner: token })); }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *token_out = ptr::null_mut(); }
            ScrapErrorCode::from(e) as i32
        }
    }
}

/// Build and sign the token with a raw private key (in-process convenience).
///
/// On multi-tenant hardware, prefer `scrap_token_builder_sign_with` + a callback
/// signer so the key never enters this library's address space.
#[no_mangle]
pub extern "C" fn scrap_token_builder_sign(
    builder: *mut ScrapTokenBuilder,
    private_key: *const u8,
    token_out: *mut *mut ScrapToken,
) -> i32 {
    if builder.is_null() || private_key.is_null() || token_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }
    let b = unsafe { Box::from_raw(builder) };
    let privkey = unsafe { slice::from_raw_parts(private_key, 32) };
    finish_sign(core_builder_from(b).sign(privkey), token_out)
}

/// Build and sign the token using an opaque signer (see `scrap_signer_*`).
/// The private key never enters this library when a callback signer is used.
#[no_mangle]
pub extern "C" fn scrap_token_builder_sign_with(
    builder: *mut ScrapTokenBuilder,
    signer: *const ScrapSigner,
    token_out: *mut *mut ScrapToken,
) -> i32 {
    if builder.is_null() || signer.is_null() || token_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }
    let b = unsafe { Box::from_raw(builder) };
    let signer = unsafe { &*signer };
    finish_sign(core_builder_from(b).sign_with(signer.inner.as_ref()), token_out)
}

// ============================================================================
// Token Operations
// ============================================================================

/// Opaque token handle
pub struct ScrapToken {
    inner: CapabilityToken,
}

/// Free a token
#[no_mangle]
pub extern "C" fn scrap_token_free(token: *mut ScrapToken) {
    if !token.is_null() {
        unsafe { drop(Box::from_raw(token)); }
    }
}

/// Decode a token from CBOR bytes
#[no_mangle]
pub extern "C" fn scrap_token_decode(
    cbor_data: *const u8,
    cbor_len: usize,
    token_out: *mut *mut ScrapToken,
) -> i32 {
    if cbor_data.is_null() || token_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let data = unsafe { slice::from_raw_parts(cbor_data, cbor_len) };

    match decode_capability_token(data) {
        Ok(token) => {
            let token_ptr = Box::into_raw(Box::new(ScrapToken { inner: token }));
            unsafe { *token_out = token_ptr; }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *token_out = ptr::null_mut(); }
            ScrapErrorCode::from(e) as i32
        }
    }
}

/// Encode a token to CBOR bytes
#[no_mangle]
pub extern "C" fn scrap_token_encode(
    token: *const ScrapToken,
    cbor_out: *mut ScrapBuffer,
) -> i32 {
    if token.is_null() || cbor_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };

    match encode_capability_token(&token.inner) {
        Ok(data) => {
            unsafe { *cbor_out = ScrapBuffer::from_vec(data); }
            ScrapErrorCode::Ok as i32
        }
        Err(e) => {
            unsafe { *cbor_out = ScrapBuffer::null(); }
            ScrapErrorCode::from(e) as i32
        }
    }
}

/// Validate a token
#[no_mangle]
pub extern "C" fn scrap_token_validate(
    token: *const ScrapToken,
    current_time: u64,
    issuer_pubkey: *const u8,
) -> i32 {
    if token.is_null() {
        return ScrapErrorCode::NullPointer as i32;
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
        Ok(()) => ScrapErrorCode::Ok as i32,
        Err(e) => ScrapErrorCode::from(e) as i32,
    }
}

/// Get token JTI
#[no_mangle]
pub extern "C" fn scrap_token_get_jti(
    token: *const ScrapToken,
    jti_out: *mut c_char,
    jti_len: usize,
) -> i32 {
    if token.is_null() || jti_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    let jti = &token.inner.payload.jti;

    if jti.len() + 1 > jti_len {
        return ScrapErrorCode::BufferTooSmall as i32;
    }

    let c_str = match CString::new(jti.as_str()) {
        Ok(s) => s,
        Err(_) => return ScrapErrorCode::Internal as i32,
    };

    unsafe {
        ptr::copy_nonoverlapping(c_str.as_ptr(), jti_out, jti.len() + 1);
    }

    ScrapErrorCode::Ok as i32
}

/// Get token issuer
#[no_mangle]
pub extern "C" fn scrap_token_get_issuer(
    token: *const ScrapToken,
    issuer_out: *mut c_char,
    issuer_len: usize,
) -> i32 {
    if token.is_null() || issuer_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    let issuer = &token.inner.payload.iss;

    if issuer.len() + 1 > issuer_len {
        return ScrapErrorCode::BufferTooSmall as i32;
    }

    let c_str = match CString::new(issuer.as_str()) {
        Ok(s) => s,
        Err(_) => return ScrapErrorCode::Internal as i32,
    };

    unsafe {
        ptr::copy_nonoverlapping(c_str.as_ptr(), issuer_out, issuer.len() + 1);
    }

    ScrapErrorCode::Ok as i32
}

/// Get token expiration time
#[no_mangle]
pub extern "C" fn scrap_token_get_expiration(
    token: *const ScrapToken,
    exp_out: *mut u64,
) -> i32 {
    if token.is_null() || exp_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let token = unsafe { &*token };
    unsafe { *exp_out = token.inner.payload.exp; }

    ScrapErrorCode::Ok as i32
}

// ============================================================================
// Capability Matching
// ============================================================================

/// Check if a granted capability authorizes a requested capability
#[no_mangle]
pub extern "C" fn scrap_capability_matches(
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
pub extern "C" fn scrap_compute_binding_hash(
    jti: *const c_char,
    payment_hash: *const u8,
    hash_out: *mut u8,
) -> i32 {
    if jti.is_null() || payment_hash.is_null() || hash_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let jti_str = match unsafe { CStr::from_ptr(jti) }.to_str() {
        Ok(s) => s,
        Err(_) => return ScrapErrorCode::Internal as i32,
    };

    let payment_hash = unsafe { slice::from_raw_parts(payment_hash, 32) };
    let hash = compute_binding_hash(jti_str, payment_hash);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScrapErrorCode::Ok as i32
}

/// Compute proof hash
#[no_mangle]
pub extern "C" fn scrap_compute_proof_hash(
    task_jti: *const c_char,
    payment_hash: *const u8,
    output_hash: *const u8,
    timestamp: u64,
    hash_out: *mut u8,
) -> i32 {
    if task_jti.is_null() || payment_hash.is_null() || output_hash.is_null() || hash_out.is_null() {
        return ScrapErrorCode::NullPointer as i32;
    }

    let jti_str = match unsafe { CStr::from_ptr(task_jti) }.to_str() {
        Ok(s) => s,
        Err(_) => return ScrapErrorCode::Internal as i32,
    };

    let payment_hash = unsafe { slice::from_raw_parts(payment_hash, 32) };
    let output_hash = unsafe { slice::from_raw_parts(output_hash, 32) };
    let hash = compute_proof_hash(jti_str, payment_hash, output_hash, timestamp);

    unsafe {
        ptr::copy_nonoverlapping(hash.as_ptr(), hash_out, 32);
    }

    ScrapErrorCode::Ok as i32
}

// ============================================================================
// Version Information
// ============================================================================

/// Get library version string
#[no_mangle]
pub extern "C" fn scrap_version() -> *const c_char {
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

        let result = scrap_sha256(data.as_ptr(), data.len(), hash.as_mut_ptr());
        assert_eq!(result, 0);

        // Compare with known hash of "test"
        let expected = hex::decode("9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08").unwrap();
        assert_eq!(hash.to_vec(), expected);
    }

    #[test]
    fn test_key_derivation_ffi() {
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];

        let result = scrap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());
        assert_eq!(result, 0);
        assert_eq!(pubkey[0], 0x03); // Compressed key starts with 02 or 03
    }

    #[test]
    fn test_sign_verify_ffi() {
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];
        scrap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());

        let message = b"test message";
        let mut signature = ScrapBuffer::null();

        let result = scrap_sign(privkey.as_ptr(), message.as_ptr(), message.len(), &mut signature);
        assert_eq!(result, 0);
        assert!(!signature.data.is_null());

        let mut valid = false;
        let result = scrap_verify(
            pubkey.as_ptr(),
            message.as_ptr(),
            message.len(),
            signature.data,
            signature.len,
            &mut valid,
        );
        assert_eq!(result, 0);
        assert!(valid);

        scrap_buffer_free(&mut signature);
    }

    // Host callback: signs the digest with a fixed key (stands in for an HSM).
    extern "C" fn test_sign_cb(
        _ctx: *mut std::ffi::c_void,
        digest: *const u8,
        sig_out: *mut u8,
        sig_cap: usize,
        sig_len_out: *mut usize,
    ) -> i32 {
        use scrap_core::Signer;
        let d = unsafe { slice::from_raw_parts(digest, 32) };
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut arr = [0u8; 32];
        arr.copy_from_slice(d);
        let sig = scrap_core::KeySigner::from_slice(&privkey).unwrap().sign_digest(&arr).unwrap();
        if sig.len() > sig_cap { return -1; }
        unsafe {
            ptr::copy_nonoverlapping(sig.as_ptr(), sig_out, sig.len());
            *sig_len_out = sig.len();
        }
        0
    }

    #[test]
    fn test_callback_signer_ffi() {
        let issuer = std::ffi::CString::new("OPERATOR").unwrap();
        let subject = std::ffi::CString::new("SAT-1").unwrap();
        let audience = std::ffi::CString::new("SAT-2").unwrap();
        let jti = std::ffi::CString::new("cb-001").unwrap();
        let cap = std::ffi::CString::new("cmd:compute:inference").unwrap();

        let builder = scrap_token_builder_new(issuer.as_ptr(), subject.as_ptr(), audience.as_ptr(), jti.as_ptr());
        scrap_token_builder_add_capability(builder, cap.as_ptr());
        scrap_token_builder_set_validity(builder, 1705320000, 1705406400);

        let signer = scrap_signer_from_callback(test_sign_cb, ptr::null_mut());
        assert!(!signer.is_null());

        let mut token: *mut ScrapToken = ptr::null_mut();
        let rc = scrap_token_builder_sign_with(builder, signer, &mut token);
        assert_eq!(rc, 0);
        assert!(!token.is_null());

        // Verify it validates against the operator pubkey derived from the same key.
        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];
        scrap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());
        let rc = scrap_token_validate(token, 1705320500, pubkey.as_ptr());
        assert_eq!(rc, 0, "callback-signed token should validate");

        scrap_signer_free(signer);
        scrap_token_free(token);
        let _ = test_sign_cb; // silence unused in some cfgs
    }

    #[test]
    fn test_token_builder_ffi() {
        let issuer = std::ffi::CString::new("OPERATOR").unwrap();
        let subject = std::ffi::CString::new("SAT-1").unwrap();
        let audience = std::ffi::CString::new("SAT-2").unwrap();
        let jti = std::ffi::CString::new("test-001").unwrap();
        let cap = std::ffi::CString::new("cmd:imaging:msi").unwrap();

        let builder = scrap_token_builder_new(
            issuer.as_ptr(),
            subject.as_ptr(),
            audience.as_ptr(),
            jti.as_ptr(),
        );
        assert!(!builder.is_null());

        scrap_token_builder_add_capability(builder, cap.as_ptr());
        scrap_token_builder_set_validity(builder, 1705320000, 1705406400);
        scrap_token_builder_set_max_area(builder, 1000);

        let privkey = hex::decode("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef").unwrap();
        let mut pubkey = [0u8; 33];
        scrap_derive_public_key(privkey.as_ptr(), pubkey.as_mut_ptr());

        let mut token: *mut ScrapToken = ptr::null_mut();
        let result = scrap_token_builder_sign(builder, privkey.as_ptr(), &mut token);
        assert_eq!(result, 0);
        assert!(!token.is_null());

        // Validate the token
        let result = scrap_token_validate(token, 1705320500, pubkey.as_ptr());
        assert_eq!(result, 0);

        // Get JTI
        let mut jti_buf = [0i8; 64];
        let result = scrap_token_get_jti(token, jti_buf.as_mut_ptr(), 64);
        assert_eq!(result, 0);

        scrap_token_free(token);
    }
}
