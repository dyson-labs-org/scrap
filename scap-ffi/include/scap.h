/*
 * SCAP (Satellite Capability and Payment) Protocol - C API
 *
 * This header provides C bindings for the SCAP protocol library.
 * Link with: -lscap_ffi -lpthread -ldl -lm
 */

#ifndef SCAP_H
#define SCAP_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * Error Codes
 * ============================================================================ */

typedef enum {
    SCAP_OK = 0,
    SCAP_ERR_NULL_POINTER = -1,
    SCAP_ERR_INVALID_KEY = -2,
    SCAP_ERR_INVALID_SIGNATURE = -3,
    SCAP_ERR_VERIFICATION_FAILED = -4,
    SCAP_ERR_CBOR_ENCODE = -5,
    SCAP_ERR_CBOR_DECODE = -6,
    SCAP_ERR_TOKEN_EXPIRED = -7,
    SCAP_ERR_TOKEN_NOT_VALID_YET = -8,
    SCAP_ERR_INVALID_CAPABILITY = -9,
    SCAP_ERR_BUFFER_TOO_SMALL = -10,
    SCAP_ERR_INTERNAL = -99,
} scap_error_t;

/* ============================================================================
 * Opaque Types
 * ============================================================================ */

/* Opaque handle to a capability token */
typedef struct scap_token scap_token_t;

/* Opaque handle to a token builder */
typedef struct scap_token_builder scap_token_builder_t;

/* Opaque handle to a task request */
typedef struct scap_task_request scap_task_request_t;

/* Opaque handle to an execution proof */
typedef struct scap_execution_proof scap_execution_proof_t;

/* ============================================================================
 * Buffer Types
 * ============================================================================ */

/* Byte buffer returned by SCAP functions. Caller must free with scap_buffer_free() */
typedef struct {
    uint8_t *data;
    size_t len;
} scap_buffer_t;

/* Free a buffer allocated by SCAP functions */
void scap_buffer_free(scap_buffer_t *buf);

/* ============================================================================
 * Cryptographic Functions
 * ============================================================================ */

/* Compute SHA-256 hash
 * @param data Input data
 * @param data_len Length of input data
 * @param hash_out Output buffer (must be at least 32 bytes)
 * @return SCAP_OK on success
 */
scap_error_t scap_sha256(
    const uint8_t *data,
    size_t data_len,
    uint8_t hash_out[32]
);

/* Derive public key from private key
 * @param private_key 32-byte private key
 * @param public_key_out Output buffer (must be at least 33 bytes)
 * @return SCAP_OK on success
 */
scap_error_t scap_derive_public_key(
    const uint8_t private_key[32],
    uint8_t public_key_out[33]
);

/* Sign a message
 * @param private_key 32-byte private key
 * @param message Message to sign
 * @param message_len Length of message
 * @param signature_out Output buffer for DER signature
 * @return SCAP_OK on success, caller must free signature_out with scap_buffer_free()
 */
scap_error_t scap_sign(
    const uint8_t private_key[32],
    const uint8_t *message,
    size_t message_len,
    scap_buffer_t *signature_out
);

/* Verify a signature
 * @param public_key 33-byte compressed public key
 * @param message Original message
 * @param message_len Length of message
 * @param signature DER-encoded signature
 * @param signature_len Length of signature
 * @param valid_out Set to true if signature is valid
 * @return SCAP_OK on success
 */
scap_error_t scap_verify(
    const uint8_t public_key[33],
    const uint8_t *message,
    size_t message_len,
    const uint8_t *signature,
    size_t signature_len,
    bool *valid_out
);

/* ============================================================================
 * Token Builder
 * ============================================================================ */

/* Create a new token builder
 * @param issuer Issuer identifier (null-terminated string)
 * @param subject Subject identifier (null-terminated string)
 * @param audience Audience identifier (null-terminated string)
 * @param jti Unique token ID (null-terminated string)
 * @return New builder handle, or NULL on error
 */
scap_token_builder_t *scap_token_builder_new(
    const char *issuer,
    const char *subject,
    const char *audience,
    const char *jti
);

/* Free a token builder */
void scap_token_builder_free(scap_token_builder_t *builder);

/* Add a capability to the token
 * @param builder Builder handle
 * @param capability Capability string (e.g., "cmd:imaging:msi")
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_add_capability(
    scap_token_builder_t *builder,
    const char *capability
);

/* Set token validity window
 * @param builder Builder handle
 * @param issued_at Unix timestamp when token was issued
 * @param expires_at Unix timestamp when token expires
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_set_validity(
    scap_token_builder_t *builder,
    uint64_t issued_at,
    uint64_t expires_at
);

/* Set maximum area constraint
 * @param builder Builder handle
 * @param max_area_km2 Maximum area in square kilometers
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_set_max_area(
    scap_token_builder_t *builder,
    uint64_t max_area_km2
);

/* Set maximum hops constraint
 * @param builder Builder handle
 * @param max_hops Maximum number of relay hops
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_set_max_hops(
    scap_token_builder_t *builder,
    uint32_t max_hops
);

/* Set as delegation token
 * @param builder Builder handle
 * @param parent_jti JTI of parent token being delegated
 * @param chain_depth Depth in delegation chain (0 = root)
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_set_delegation(
    scap_token_builder_t *builder,
    const char *parent_jti,
    uint32_t chain_depth
);

/* Build and sign the token
 * @param builder Builder handle (consumed, do not use after this call)
 * @param private_key 32-byte signing key
 * @param token_out Output token handle
 * @return SCAP_OK on success
 */
scap_error_t scap_token_builder_sign(
    scap_token_builder_t *builder,
    const uint8_t private_key[32],
    scap_token_t **token_out
);

/* ============================================================================
 * Token Operations
 * ============================================================================ */

/* Free a token */
void scap_token_free(scap_token_t *token);

/* Decode a token from CBOR bytes
 * @param cbor_data CBOR-encoded token
 * @param cbor_len Length of CBOR data
 * @param token_out Output token handle
 * @return SCAP_OK on success
 */
scap_error_t scap_token_decode(
    const uint8_t *cbor_data,
    size_t cbor_len,
    scap_token_t **token_out
);

/* Encode a token to CBOR bytes
 * @param token Token handle
 * @param cbor_out Output buffer
 * @return SCAP_OK on success, caller must free cbor_out with scap_buffer_free()
 */
scap_error_t scap_token_encode(
    const scap_token_t *token,
    scap_buffer_t *cbor_out
);

/* Validate a token
 * @param token Token handle
 * @param current_time Current Unix timestamp (0 to skip time check)
 * @param issuer_pubkey 33-byte issuer public key (NULL to skip signature check)
 * @return SCAP_OK if valid, error code otherwise
 */
scap_error_t scap_token_validate(
    const scap_token_t *token,
    uint64_t current_time,
    const uint8_t *issuer_pubkey
);

/* Get token JTI
 * @param token Token handle
 * @param jti_out Output buffer for JTI string
 * @param jti_len Size of output buffer
 * @return SCAP_OK on success
 */
scap_error_t scap_token_get_jti(
    const scap_token_t *token,
    char *jti_out,
    size_t jti_len
);

/* Get token issuer
 * @param token Token handle
 * @param issuer_out Output buffer for issuer string
 * @param issuer_len Size of output buffer
 * @return SCAP_OK on success
 */
scap_error_t scap_token_get_issuer(
    const scap_token_t *token,
    char *issuer_out,
    size_t issuer_len
);

/* Get token expiration time
 * @param token Token handle
 * @param exp_out Output for expiration timestamp
 * @return SCAP_OK on success
 */
scap_error_t scap_token_get_expiration(
    const scap_token_t *token,
    uint64_t *exp_out
);

/* ============================================================================
 * Capability Matching
 * ============================================================================ */

/* Check if a granted capability authorizes a requested capability
 * @param granted The capability that was granted (e.g., "cmd:imaging:*")
 * @param requested The capability being requested (e.g., "cmd:imaging:msi")
 * @return true if granted authorizes requested
 */
bool scap_capability_matches(
    const char *granted,
    const char *requested
);

/* ============================================================================
 * Binding and Proof Functions
 * ============================================================================ */

/* Compute binding hash for payment-capability binding
 * @param jti Token JTI
 * @param payment_hash 32-byte payment hash
 * @param hash_out Output buffer (must be at least 32 bytes)
 * @return SCAP_OK on success
 */
scap_error_t scap_compute_binding_hash(
    const char *jti,
    const uint8_t payment_hash[32],
    uint8_t hash_out[32]
);

/* Compute proof hash for execution proof
 * @param task_jti Task JTI
 * @param payment_hash 32-byte payment hash
 * @param output_hash 32-byte output hash
 * @param timestamp Execution timestamp
 * @param hash_out Output buffer (must be at least 32 bytes)
 * @return SCAP_OK on success
 */
scap_error_t scap_compute_proof_hash(
    const char *task_jti,
    const uint8_t payment_hash[32],
    const uint8_t output_hash[32],
    uint64_t timestamp,
    uint8_t hash_out[32]
);

/* ============================================================================
 * Version Information
 * ============================================================================ */

/* Get library version string */
const char *scap_version(void);

#ifdef __cplusplus
}
#endif

#endif /* SCAP_H */
