from __future__ import annotations

# pyright: reportMissingImports=false

import unittest
from dataclasses import replace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.engine import Ed25519Verifier
from backend.models import Attestation, canonical_bytes


class ProductionCryptoTests(unittest.TestCase):
    def test_ed25519_verifier_accepts_exact_payload_and_rejects_tampering(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw().hex()
        attestation = Attestation(
            provider_id="primary",
            resource="https://primary.example/api/attestation",
            published_at=990,
            observed_at=990,
            expires_at=2_000,
            payload_hash="a" * 64,
            signature="",
            statement="delivery-confirmed",
        )
        signature = private_key.sign(canonical_bytes(attestation.signed_payload())).hex()
        signed = replace(attestation, signature=signature)
        verifier = Ed25519Verifier({"primary": public_key})

        self.assertTrue(verifier.verify(signed))
        self.assertFalse(verifier.verify(replace(signed, statement="tampered")))
        self.assertFalse(verifier.verify(replace(signed, provider_id="unknown")))


if __name__ == "__main__":
    unittest.main()
