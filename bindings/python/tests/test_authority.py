"""Exercise the installed wheel against the real native verifier, without provider calls."""

import unittest
from scrap_authority import Authority, AuthorityError


class AuthorityTests(unittest.TestCase):
    """Synthetic keys establish interoperability only, never deployed authority."""

    def setUp(self):
        self.authority = Authority()
        self.key = bytes([7]) * 32
        self.expected = dict(
            issuer="marketplace", subject="account:one",
            audience="marketplace:observation-worker:v1",
            capability="data:observations:prepare", grant_digest="a" * 64,
        )
        self.token = self.authority.sign(
            private_key=self.key, issued_at=90, expires_at=110, **self.expected,
        )
        self.public_key = self.authority.public_key(self.key)

    def test_round_trip_and_repeated_owned_buffer_release(self):
        """Native ownership remains correct across repeated signing and verification."""
        for _ in range(50):
            token = self.authority.sign(
                private_key=self.key, issued_at=90, expires_at=110, **self.expected,
            )
            self.authority.verify(token, public_key=self.public_key, now=100, **self.expected)

    def test_identity_scope_and_expiry(self):
        """A valid signature for another operation is not authorization."""
        for field in self.expected:
            with self.subTest(field=field), self.assertRaises(AuthorityError):
                self.authority.verify(
                    self.token, public_key=self.public_key, now=100,
                    **(self.expected | {field: "different"}),
                )
        for now in (89, 110):
            with self.assertRaises(AuthorityError):
                self.authority.verify(self.token, public_key=self.public_key, now=now, **self.expected)

    def test_tampered_wire_and_wrong_key(self):
        """Verify received bytes, never a reserialized claim object."""
        for token in (self.token + b"\x00", self.token[:-1], bytes([self.token[0] ^ 1]) + self.token[1:]):
            with self.assertRaises(AuthorityError):
                self.authority.verify(token, public_key=self.public_key, now=100, **self.expected)
        with self.assertRaises(AuthorityError):
            self.authority.verify(
                self.token, public_key=self.authority.public_key(bytes([8])*32),
                now=100, **self.expected,
            )

    def test_native_boundary_rejects_nul_and_bad_lengths(self):
        """Do not let C-string truncation change the expected identity."""
        with self.assertRaises(ValueError):
            self.authority.verify(
                self.token, public_key=self.public_key, now=100,
                **(self.expected | {"subject": "account:one\x00other"}),
            )
        with self.assertRaises(ValueError):
            self.authority.verify(self.token, public_key=b"short", now=100, **self.expected)


if __name__ == "__main__":
    unittest.main()
