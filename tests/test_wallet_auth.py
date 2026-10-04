from __future__ import annotations

import unittest

from backend.wallet_auth import create_challenge, session_address, verify_challenge


class WalletAuthTests(unittest.TestCase):
    def test_challenge_is_exact_and_session_cookie_is_signed(self):
        challenge = create_challenge(
            address="0x1111111111111111111111111111111111111111",
            chain_id="0x107d",
            origin="https://aegis.example",
            secret="s" * 64,
            now=1_700_000_000,
        )
        self.assertIn("Nonce:", challenge["message"])
        self.assertEqual(challenge["address"], "0x1111111111111111111111111111111111111111")
        with self.assertRaises(ValueError):
            verify_challenge(
                challenge_cookie=challenge["challenge"],
                address=challenge["address"],
                message=challenge["message"],
                signature="0x00",
                secret="s" * 64,
                now=1_700_000_001,
            )

    def test_tampered_session_and_expired_session_fail_closed(self):
        challenge = create_challenge(
            address="0x2222222222222222222222222222222222222222",
            chain_id="0x107d",
            origin="https://aegis.example",
            secret="s" * 64,
            now=1_700_000_000,
        )
        self.assertIsNone(session_address(challenge["challenge"], "s" * 63))
        self.assertIsNone(session_address(challenge["challenge"], "s" * 64, now=1_700_000_301))


if __name__ == "__main__":
    unittest.main()
