from __future__ import annotations

import unittest

from backend.genlayer_authority import (
    DEFAULT_FIREWALL,
    DEFAULT_GATEWAY,
    GenLayerAuthority,
    GenLayerAuthorityError,
    decode_transaction_call_data,
    _encode_calldata,
    encode_read_call,
    _rlp_encode_bytes,
)


TX_ID = "0x" + "12" * 32
INTENT_ID = "0x" + "99" * 32
ACTION_SUBJECT = "11" * 32
ACTION_INTENT = "22" * 32
ACTION_HASH = "44" * 32
TARGET_HASH = "55" * 32
PAYLOAD_HASH = "66" * 32
EVIDENCE_DIGEST = "77" * 32
AGENT = "0x" + "88" * 20
CONSUMER = "0x" + "33" * 20
CALL_DATA = "f84cb849160461726773158302" + "99" * 32 + "840141454749535f544553545f414c4c4f57066d6574686f64346564656369646500"


def write_call_data(method: str, args: list[bytes]) -> str:
    call = _encode_calldata({"args": args, "method": method})
    payload = _rlp_encode_bytes(call) + _rlp_encode_bytes(b"\x00")
    if len(payload) <= 55:
        envelope = bytes([0xC0 + len(payload)]) + payload
    else:
        size = len(payload).to_bytes((len(payload).bit_length() + 7) // 8, "big")
        envelope = bytes([0xF7 + len(size)]) + size + payload
    return envelope.hex()


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
            "action_hash": bytes.fromhex(ACTION_HASH),
            "target_hash": bytes.fromhex(TARGET_HASH),
            "payload_hash": bytes.fromhex(PAYLOAD_HASH),
            "evidence_digest": bytes.fromhex(EVIDENCE_DIGEST),
            "agent": AGENT,
            "consumer": CONSUMER,
            "value": 500,
            "expires_at": 100,
            "repair_deadline": 200,
        }
        proof = authority.verify_decision(
            transaction_id=TX_ID,
            intent_id=INTENT_ID,
            decision="AUTHORIZE",
            expected_action_subject=ACTION_SUBJECT,
            expected_action_intent=ACTION_INTENT,
            expected_action_hash=ACTION_HASH,
            expected_target_hash=TARGET_HASH,
            expected_payload_hash=PAYLOAD_HASH,
            expected_evidence_digest=EVIDENCE_DIGEST,
            expected_agent=AGENT,
            expected_consumer=CONSUMER,
            expected_value=500,
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
            "action_hash": bytes.fromhex(ACTION_HASH),
            "target_hash": bytes.fromhex(TARGET_HASH),
            "payload_hash": bytes.fromhex(PAYLOAD_HASH),
            "evidence_digest": bytes.fromhex(EVIDENCE_DIGEST),
            "agent": AGENT,
            "consumer": CONSUMER,
            "value": 500,
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
                expected_action_hash=ACTION_HASH,
                expected_target_hash=TARGET_HASH,
                expected_payload_hash=PAYLOAD_HASH,
                expected_evidence_digest=EVIDENCE_DIGEST,
                expected_agent=AGENT,
                expected_consumer=CONSUMER,
                expected_value=500,
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
                expected_action_hash=ACTION_HASH,
                expected_target_hash=TARGET_HASH,
                expected_payload_hash=PAYLOAD_HASH,
                expected_evidence_digest=EVIDENCE_DIGEST,
                expected_agent=AGENT,
                expected_consumer=CONSUMER,
                expected_value=500,
                expected_expires_at=100,
                expected_repair_deadline=200,
            )

    def test_verifies_finalized_evidence_replacement(self):
        authority = FakeAuthority(
            {
                "gen_getTransactionStatus": {"status": "Finalized", "statusCode": 7},
                "gen_getTransactionReceipt": {
                    "id": TX_ID, "recipient": DEFAULT_FIREWALL, "status": 7,
                    "statusName": "FINALIZED", "txExecutionResult": 1, "result": 1,
                    "txCallData": write_call_data("replace_evidence", [bytes.fromhex("99" * 32), bytes.fromhex(EVIDENCE_DIGEST)]),
                },
                "gen_dbg_traceTransaction": {"result_code": 0},
            }
        )
        authority._read_intent = lambda intent_id: {"state": 1, "reason": "EVIDENCE_REPLACED", "evidence_digest": bytes.fromhex(EVIDENCE_DIGEST), "evidence_revision": 1}  # type: ignore[method-assign]
        proof = authority.verify_evidence_replacement(transaction_id=TX_ID, intent_id=INTENT_ID, evidence_digest=EVIDENCE_DIGEST, expected_revision=0)
        self.assertEqual(proof.method, "replace_evidence")

    def test_verifies_finalized_receipt_consumption(self):
        authority = FakeAuthority(
            {
                "gen_getTransactionStatus": {"status": "Finalized", "statusCode": 7},
                "gen_getTransactionReceipt": {
                    "id": TX_ID, "recipient": DEFAULT_FIREWALL, "status": 7,
                    "statusName": "FINALIZED", "txExecutionResult": 1, "result": 1,
                    "txCallData": write_call_data("consume_receipt", [bytes.fromhex("77" * 32), bytes.fromhex(ACTION_INTENT)]),
                },
                "gen_dbg_traceTransaction": {"result_code": 0},
            }
        )
        authority._read_intent = lambda intent_id: {"state": 6, "reason": "CONSUMED", "consumer": CONSUMER, "receipt_id": bytes.fromhex("77" * 32), "action_intent": bytes.fromhex(ACTION_INTENT)}  # type: ignore[method-assign]
        proof = authority.verify_receipt_consumption(transaction_id=TX_ID, intent_id=INTENT_ID, receipt_id="77" * 32, action_intent=ACTION_INTENT, expected_consumer=CONSUMER)
        self.assertEqual(proof.method, "consume_receipt")


if __name__ == "__main__":
    unittest.main()
