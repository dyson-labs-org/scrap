"""Portable ctypes consumer of the SCRAP online-grant verification profile."""

import ctypes
from pathlib import Path
import sys


class AuthorityError(ValueError):
    """The token did not establish the exact expected operation authority."""


class _Buffer(ctypes.Structure):
    _fields_ = [("data", ctypes.POINTER(ctypes.c_ubyte)), ("length", ctypes.c_size_t)]


def _bytes(value, length=None):
    """Copy a bounded byte sequence into a native input buffer."""
    if not isinstance(value, bytes) or (length is not None and len(value) != length):
        raise ValueError("Invalid byte input")
    return (ctypes.c_ubyte * len(value)).from_buffer_copy(value)


def _text(value):
    """Reject NUL truncation at the native string boundary."""
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 256:
        raise ValueError("Invalid authority identity")
    return value.encode("utf-8")


class Authority:
    """Sign and verify root operation tokens using the packaged upstream library."""

    def __init__(self):
        suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
        self._lib = ctypes.CDLL(str(Path(__file__).with_name("scrap_native" + suffix)))
        lib = self._lib
        pointer = ctypes.c_void_p
        text = ctypes.c_char_p
        lib.scrap_verify_operation.argtypes = [
            pointer, ctypes.c_size_t, pointer, text, text, text, text, text, ctypes.c_uint64,
        ]
        lib.scrap_verify_operation.restype = ctypes.c_int
        lib.scrap_token_builder_new.argtypes = [text, text, text, text]
        lib.scrap_token_builder_new.restype = pointer
        lib.scrap_token_builder_add_capability.argtypes = [pointer, text]
        lib.scrap_token_builder_set_validity.argtypes = [pointer, ctypes.c_uint64, ctypes.c_uint64]
        lib.scrap_token_builder_sign.argtypes = [pointer, pointer, ctypes.POINTER(pointer)]
        lib.scrap_token_builder_sign.restype = ctypes.c_int
        lib.scrap_token_encode.argtypes = [pointer, ctypes.POINTER(_Buffer)]
        lib.scrap_token_encode.restype = ctypes.c_int
        lib.scrap_token_free.argtypes = [pointer]
        lib.scrap_token_free.restype = None
        lib.scrap_token_builder_free.argtypes = [pointer]
        lib.scrap_token_builder_free.restype = None
        lib.scrap_buffer_free.argtypes = [ctypes.POINTER(_Buffer)]
        lib.scrap_buffer_free.restype = None
        lib.scrap_derive_public_key.argtypes = [pointer, pointer]
        lib.scrap_derive_public_key.restype = ctypes.c_int

    def public_key(self, private_key):
        """Derive a public key without returning or logging private material."""
        output = (ctypes.c_ubyte * 33)()
        if self._lib.scrap_derive_public_key(_bytes(private_key, 32), output):
            raise AuthorityError("Invalid signing key")
        return bytes(output)

    def sign(self, *, private_key, issuer, subject, audience, capability, grant_digest, issued_at, expires_at):
        """Bind one root grant; current grant policy must be checked by its executor."""
        fields = [_text(value) for value in (issuer, subject, audience, grant_digest)]
        if not 0 <= issued_at < expires_at < 2**64:
            raise ValueError("Invalid grant validity")
        key = _bytes(private_key, 32)
        builder = self._lib.scrap_token_builder_new(*fields)
        if not builder:
            raise AuthorityError("Invalid grant")
        output = _Buffer()
        token = ctypes.c_void_p()
        try:
            if self._lib.scrap_token_builder_add_capability(builder, _text(capability)):
                raise AuthorityError("Invalid capability")
            if self._lib.scrap_token_builder_set_validity(builder, issued_at, expires_at):
                raise AuthorityError("Invalid validity")
            result = self._lib.scrap_token_builder_sign(builder, key, ctypes.byref(token))
            builder = None  # The native signing call consumes the builder on either outcome.
            if result:
                raise AuthorityError("Signing failed")
            if self._lib.scrap_token_encode(token, ctypes.byref(output)):
                raise AuthorityError("Encoding failed")
            return ctypes.string_at(output.data, output.length)
        finally:
            self._lib.scrap_buffer_free(ctypes.byref(output))
            self._lib.scrap_token_free(token)
            if builder:
                self._lib.scrap_token_builder_free(builder)
            ctypes.memset(key, 0, len(key))

    def verify(self, token, *, public_key, issuer, subject, audience, capability, grant_digest, now):
        """Require all trusted expectations; the caller separately checks live policy."""
        if not isinstance(token, bytes) or not 0 < len(token) <= 16384:
            raise AuthorityError("Invalid token size")
        if not 0 <= now < 2**64:
            raise ValueError("Invalid verification time")
        identities = [_text(value) for value in (issuer, subject, audience, capability, grant_digest)]
        result = self._lib.scrap_verify_operation(
            _bytes(token), len(token), _bytes(public_key, 33), *identities, now,
        )
        if result:
            raise AuthorityError("Operation authority rejected")
