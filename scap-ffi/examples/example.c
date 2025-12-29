/*
 * SCAP C API Example
 *
 * Demonstrates creating, signing, and validating a capability token.
 *
 * Compile with:
 *   gcc -o example example.c -L../target/release -lscap_ffi -lpthread -ldl -lm
 *
 * Run with:
 *   LD_LIBRARY_PATH=../target/release ./example
 */

#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "../include/scap.h"

/* Print hex bytes */
static void print_hex(const char *label, const uint8_t *data, size_t len) {
    printf("%s: ", label);
    for (size_t i = 0; i < len && i < 32; i++) {
        printf("%02x", data[i]);
    }
    if (len > 32) printf("...");
    printf("\n");
}

int main(void) {
    scap_error_t err;

    printf("SCAP C API Example\n");
    printf("==================\n");
    printf("Library version: %s\n\n", scap_version());

    /* Generate a keypair (in real code, use secure key storage) */
    uint8_t private_key[32] = {
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef,
        0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef
    };

    uint8_t public_key[33];
    err = scap_derive_public_key(private_key, public_key);
    if (err != SCAP_OK) {
        fprintf(stderr, "Failed to derive public key: %d\n", err);
        return 1;
    }
    print_hex("Public key", public_key, 33);

    /* Create a capability token */
    printf("\n1. Creating capability token...\n");

    scap_token_builder_t *builder = scap_token_builder_new(
        "OPERATOR-ALPHA",      /* issuer */
        "SATELLITE-CUSTOMER",  /* subject */
        "SENTINEL-2A",         /* audience */
        "task-img-001"         /* jti */
    );

    if (!builder) {
        fprintf(stderr, "Failed to create token builder\n");
        return 1;
    }

    /* Add capabilities */
    scap_token_builder_add_capability(builder, "cmd:imaging:msi");
    scap_token_builder_add_capability(builder, "data:download:standard");

    /* Set validity (24 hours from a fixed timestamp) */
    uint64_t now = 1705320000;
    scap_token_builder_set_validity(builder, now, now + 86400);

    /* Set constraints */
    scap_token_builder_set_max_area(builder, 1000);  /* 1000 km² */
    scap_token_builder_set_max_hops(builder, 3);

    /* Sign the token */
    scap_token_t *token = NULL;
    err = scap_token_builder_sign(builder, private_key, &token);
    /* Note: builder is consumed by sign, don't free it */

    if (err != SCAP_OK) {
        fprintf(stderr, "Failed to sign token: %d\n", err);
        return 1;
    }

    printf("   Token created successfully!\n");

    /* Get token info */
    char jti_buf[64];
    char issuer_buf[64];
    uint64_t expiration;

    scap_token_get_jti(token, jti_buf, sizeof(jti_buf));
    scap_token_get_issuer(token, issuer_buf, sizeof(issuer_buf));
    scap_token_get_expiration(token, &expiration);

    printf("   JTI: %s\n", jti_buf);
    printf("   Issuer: %s\n", issuer_buf);
    printf("   Expires: %lu\n", (unsigned long)expiration);

    /* Encode to CBOR */
    printf("\n2. Encoding to CBOR...\n");

    scap_buffer_t cbor_buf = {0};
    err = scap_token_encode(token, &cbor_buf);
    if (err != SCAP_OK) {
        fprintf(stderr, "Failed to encode token: %d\n", err);
        scap_token_free(token);
        return 1;
    }

    printf("   CBOR size: %zu bytes\n", cbor_buf.len);
    print_hex("   CBOR data", cbor_buf.data, cbor_buf.len);

    /* Validate the token */
    printf("\n3. Validating token...\n");

    err = scap_token_validate(token, now + 100, public_key);
    if (err == SCAP_OK) {
        printf("   Token is VALID\n");
    } else if (err == SCAP_ERR_TOKEN_EXPIRED) {
        printf("   Token has EXPIRED\n");
    } else if (err == SCAP_ERR_VERIFICATION_FAILED) {
        printf("   Signature verification FAILED\n");
    } else {
        printf("   Validation error: %d\n", err);
    }

    /* Decode from CBOR */
    printf("\n4. Decoding from CBOR...\n");

    scap_token_t *decoded_token = NULL;
    err = scap_token_decode(cbor_buf.data, cbor_buf.len, &decoded_token);
    if (err != SCAP_OK) {
        fprintf(stderr, "Failed to decode token: %d\n", err);
        scap_buffer_free(&cbor_buf);
        scap_token_free(token);
        return 1;
    }

    char decoded_jti[64];
    scap_token_get_jti(decoded_token, decoded_jti, sizeof(decoded_jti));
    printf("   Decoded JTI: %s\n", decoded_jti);

    /* Test capability matching */
    printf("\n5. Capability matching...\n");

    const char *granted = "cmd:imaging:*";
    const char *requested1 = "cmd:imaging:msi";
    const char *requested2 = "cmd:propulsion:fire";

    printf("   Does '%s' grant '%s'? %s\n",
        granted, requested1,
        scap_capability_matches(granted, requested1) ? "YES" : "NO");

    printf("   Does '%s' grant '%s'? %s\n",
        granted, requested2,
        scap_capability_matches(granted, requested2) ? "YES" : "NO");

    /* Compute binding hash */
    printf("\n6. Payment binding...\n");

    uint8_t payment_hash[32] = {0};  /* In real code, this comes from Lightning */
    scap_sha256((const uint8_t*)"secret-preimage", 15, payment_hash);

    uint8_t binding_hash[32];
    scap_compute_binding_hash(jti_buf, payment_hash, binding_hash);
    print_hex("   Binding hash", binding_hash, 32);

    /* Sign the binding */
    scap_buffer_t binding_sig = {0};
    err = scap_sign(private_key, binding_hash, 32, &binding_sig);
    if (err == SCAP_OK) {
        printf("   Binding signature: %zu bytes\n", binding_sig.len);
        scap_buffer_free(&binding_sig);
    }

    /* Cleanup */
    printf("\n7. Cleanup...\n");
    scap_buffer_free(&cbor_buf);
    scap_token_free(token);
    scap_token_free(decoded_token);
    printf("   Done!\n");

    return 0;
}
