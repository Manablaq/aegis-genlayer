from __future__ import annotations

import unittest

from backend.genlayer_authority import (
    DEFAULT_FIREWALL,
    DEFAULT_GATEWAY,
    GenLayerAuthority,
    GenLayerAuthorityError,
    decode_transaction_call_data,
    encode_read_call,
)


TX_ID = "0x" + "12" * 32
INTENT_ID = "0x" + "99" * 32
ACTION_SUBJECT = "11" * 32
ACTION_INTENT = "22" * 32
CONSUMER = "0x" + "33" * 20
CALL_DATA = "f84cb849160461726773158302" + "99" * 32 + "840141454749535f544553545f414c4c4f57066d6574686f64346564656369646500"


class FakeAuthority(GenLayerAuthority):
    def __init__(self, responses):
        super().__init__(rpc_url="https://rpc.example.test", gateway=DEFAULT_GATEWAY, firewall=DEFAULT_FIREWALL)
        self.responses = responses

    def _rpc(self, method, params):  # type: ignore[override]
        return self.responses[method]


class GenLayerAuthorityTests(unittest.TestCase):
    def test_call_data_binds_exact_intent_and_gateway_method(self):
        decoded = decode_transaction_call_data(CALL_DATA, expected_intent_id=INTENT_ID)
        self.assertEqual(decoded["intent_id"], INTENT_ID)
        with self.assertRaisesRegex(GenLayerAuthorityError, "GENLAYER_INTENT_MISMATCH"):
            decode_transaction_call_data(CALL_DATA, expected_intent_id="0x" + "aa" * 32)

    def test_read_call_uses_finalized_genlayer_encoding(self):
        encoded = encode_read_call("get_intent", [bytes.fromhex("99" * 32)])
        self.assertTrue(encoded.startswith("0xf8"))
        self.assertIn("6765745f696e74656e74", encoded)

    def test_requires_finalized_successful_gateway_decision_and_state(self):
        authority = FakeAuthority(
            {
                "gen_getTransactionStatus": {"status": "Finalized", "statusCode": 7},
                "gen_getTransactionReceipt": {
                    "id": TX_ID,
                    "recipient": DEFAULT_GATEWAY,
                    "status": 7,
                    "statusName": None,
                    "txExecutionResult": 1,
                    "result": 1,
                    "txCallData": CALL_DATA,
                },
                "gen_dbg_traceTransaction": {"result_code": 0, "return_data": "0x0044415441" + "415554484f52495a45"},
                "gen_call": {"status": {"code": 0}, "data": ""},
            }
        )
        # The state read is tested separately because a production response is
        # decoded from the GenLayer calldata codec, not accepted from a caller.
        authority._read_intent = lambda intent_id: {  # type: ignore[method-assign]
            "state": 3,
            "reason": "CONSENSUS_AUTHORIZED",
            "action_subject": bytes.fromhex(ACTION_SUBJECT),
            "action_intent": bytes.fromhex(ACTION_INTENT),
            "consumer": CONSUMER,
            "expires_at": 100,
            "repair_deadline": 200,
        }
        proof = authority.verify_decision(
            transaction_id=TX_ID,
            intent_id=INTENT_ID,
            decision="AUTHORIZE",
            expected_action_subject=ACTION_SUBJECT,
            expected_action_intent=ACTION_INTENT,
            expected_consumer=CONSUMER,
            expected_expires_at=100,
            expected_repair_deadline=200,
        )
        self.assertEqual(proof.reason, "CONSENSUS_AUTHORIZED")
        self.assertEqual(proof.action_intent, "0x" + ACTION_INTENT)

    def test_rejects_local_intent_binding_mismatch(self):
        authority = FakeAuthority(
            {
                "gen_getTransactionStatus": {"status": "Finalized", "statusCode": 7},
                "gen_getTransactionReceipt": {
                    "id": TX_ID,
                    "recipient": DEFAULT_GATEWAY,
                    "status": 7,
                    "statusName": None,
                    "txExecutionResult": 1,
                    "result": 1,
                    "txCallData": CALL_DATA,
                },
                "gen_dbg_traceTransaction": {"result_code": 0, "return_data": "0x415554484f52495a45"},
            }
        )
        authority._read_intent = lambda intent_id: {  # type: ignore[method-assign]
            "state": 3,
            "reason": "CONSENSUS_AUTHORIZED",
            "action_subject": bytes.fromhex(ACTION_SUBJECT),
            "action_intent": bytes.fromhex(ACTION_INTENT),
            "consumer": CONSUMER,
            "expires_at": 100,
            "repair_deadline": 200,
        }
        with self.assertRaisesRegex(GenLayerAuthorityError, "GENLAYER_DECISION_MISMATCH"):
            authority.verify_decision(
                transaction_id=TX_ID,
                intent_id=INTENT_ID,
                decision="AUTHORIZE",
                expected_action_subject="44" * 32,
                expected_action_intent=ACTION_INTENT,
                expected_consumer=CONSUMER,
                expected_expires_at=100,
                expected_repair_deadline=200,
            )

    def test_rejects_accepted_receipt(self):
        authority = FakeAuthority(
            {
                "gen_getTransactionStatus": {"status": "Accepted", "statusCode": 5},
            }
        )
        with self.assertRaisesRegex(GenLayerAuthorityError, "GENLAYER_NOT_FINALIZED"):
            authority.verify_decision(
                transaction_id=TX_ID,
                intent_id=INTENT_ID,
                decision="AUTHORIZE",
                expected_action_subject=ACTION_SUBJECT,
                expected_action_intent=ACTION_INTENT,
                expected_consumer=CONSUMER,
                expected_expires_at=100,
                expected_repair_deadline=200,
            )


if __name__ == "__main__":
    unittest.main()
