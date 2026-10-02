from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.engine import AegisEngine, DecisionError, StaticVerifier, ValidationError
from backend.models import Attestation, IntentState, Policy, digest_hex
from backend.store import JsonStore


class Clock:
    def __init__(self, value: int = 1_000):
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


def attestation(provider: str, signature: str, *, observed: int = 990, resource: str | None = None) -> Attestation:
    return Attestation(
        provider_id=provider,
        resource=resource or f"https://{provider}.example/api/attestation",
        published_at=observed,
        observed_at=observed,
        expires_at=2_000,
        payload_hash="a" * 64,
        signature=signature,
        statement="delivery-confirmed",
    )


def policy() -> Policy:
    return Policy(
        policy_id="vendor-payment",
        version=1,
        approved_agents=frozenset({"agent-1"}),
        allowed_action_types=frozenset({"release_payment"}),
        allowed_recipients=frozenset({"vendor-1"}),
        approved_sources={"primary": "https://primary.example/api/", "secondary": "https://secondary.example/api/"},
        max_value=10_000,
        required_sources=frozenset({"primary", "secondary"}),
        minimum_attestations=2,
        maximum_age_seconds=100,
        intent_ttl_seconds=60,
        repair_window_seconds=120,
    )


class AegisEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.verifier = StaticVerifier({"sig-primary", "sig-secondary", "sig-repaired"})
        self.engine = AegisEngine(verifier=self.verifier, clock=self.clock)
        self.engine.register_policy(policy())

    def create(self, attestations: list[Attestation] | None = None):
        return self.engine.create_intent(
            intent_id="b" * 64,
            policy_id="vendor-payment",
            policy_version=1,
            agent="agent-1",
            action_type="release_payment",
            target="invoice-42",
            recipient="vendor-1",
            value=500,
            payload_hash="c" * 64,
            attestations=attestations or [attestation("primary", "sig-primary"), attestation("secondary", "sig-secondary")],
        )

    def test_approval_receipt_is_bound_and_single_use(self):
        intent = self.create()
        authorized = self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        self.assertEqual(authorized.state, IntentState.AUTHORIZED)
        receipt = self.engine.consume_receipt(
            receipt_id=authorized.receipt_id or "",
            consumer="vendor-1",
            action_intent_value=authorized.action_intent,
        )
        self.assertIsNotNone(receipt.consumed_at)
        self.assertEqual(authorized.state, IntentState.CONSUMED)
        with self.assertRaises(DecisionError):
            self.engine.consume_receipt(
                receipt_id=receipt.receipt_id,
                consumer="vendor-1",
                action_intent_value=authorized.action_intent,
            )

    def test_wrong_consumer_and_action_intent_fail_closed(self):
        intent = self.create()
        self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        receipt_id = self.engine.intents[intent.intent_id].receipt_id or ""
        with self.assertRaises(DecisionError):
            self.engine.consume_receipt(receipt_id=receipt_id, consumer="attacker", action_intent_value=intent.action_intent)
        with self.assertRaises(DecisionError):
            self.engine.consume_receipt(receipt_id=receipt_id, consumer="vendor-1", action_intent_value="d" * 64)
        self.assertEqual(self.engine.intents[intent.intent_id].state, IntentState.AUTHORIZED)

    def test_invalid_evidence_requires_repair_then_preserves_action_binding(self):
        intent = self.create([attestation("primary", "bad"), attestation("secondary", "sig-secondary")])
        repaired = self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        self.assertEqual(repaired.state, IntentState.REPAIR_REQUIRED)
        subject = repaired.action_subject
        action = repaired.action_intent
        deadline = repaired.repair_deadline
        repaired = self.engine.replace_evidence(
            intent_id=intent.intent_id,
            caller="agent-1",
            attestations=[attestation("primary", "sig-repaired"), attestation("secondary", "sig-secondary")],
        )
        self.assertEqual(repaired.evidence_revision, 1)
        self.assertEqual(repaired.action_subject, subject)
        self.assertEqual(repaired.action_intent, action)
        self.assertEqual(repaired.repair_deadline, deadline)
        self.assertEqual(self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE").state, IntentState.AUTHORIZED)

    def test_policy_violation_is_denied_not_repaired(self):
        intent = self.engine.create_intent(
            intent_id="d" * 64, policy_id="vendor-payment", policy_version=1, agent="untrusted-agent",
            action_type="release_payment", target="invoice-42", recipient="vendor-1", value=500,
            payload_hash="c" * 64, attestations=[],
        )
        result = self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        self.assertEqual(result.state, IntentState.DENIED)
        self.assertEqual(result.reason, "AGENT_NOT_APPROVED")

    def test_expiry_is_terminal(self):
        intent = self.create()
        self.clock.advance(60)
        result = self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        self.assertEqual(result.state, IntentState.EXPIRED)
        with self.assertRaises(DecisionError):
            self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")

    def test_restart_restores_terminal_receipt_without_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonStore(Path(directory) / "aegis.state.json")
            engine = AegisEngine(verifier=self.verifier, clock=self.clock, store=store)
            engine.register_policy(policy())
            intent = engine.create_intent(
                intent_id="e" * 64, policy_id="vendor-payment", policy_version=1, agent="agent-1",
                action_type="release_payment", target="invoice-42", recipient="vendor-1", value=500,
                payload_hash="c" * 64,
                attestations=[attestation("primary", "sig-primary"), attestation("secondary", "sig-secondary")],
            )
            engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
            restored = AegisEngine(verifier=self.verifier, clock=self.clock, store=store)
            restored_intent = restored.intents[intent.intent_id]
            self.assertEqual(restored_intent.state, IntentState.AUTHORIZED)
            self.assertEqual(restored_intent.receipt_id, intent.receipt_id)
            restored.consume_receipt(
                receipt_id=restored_intent.receipt_id or "", consumer="vendor-1", action_intent_value=intent.action_intent
            )
            self.assertEqual(restored.intents[intent.intent_id].state, IntentState.CONSUMED)

    def test_invalid_consensus_decision_does_not_mutate_state(self):
        intent = self.create()
        with self.assertRaises(DecisionError):
            self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="MAYBE")
        self.assertEqual(intent.state, IntentState.PENDING)

    def test_policy_rejects_redirect_ambiguous_source(self):
        with self.assertRaises(ValueError):
            Policy(**{**policy().__dict__, "approved_sources": {"primary": "https://primary.example/api?next=x", "secondary": "https://secondary.example/api/"}}).validate()

    def test_attestation_redirect_ambiguity_requires_repair(self):
        intent = self.create(
            [
                attestation("primary", "sig-primary", resource="https://primary.example/api/item?redirect=other"),
                attestation("secondary", "sig-secondary"),
            ]
        )
        result = self.engine.evaluate(intent_id=intent.intent_id, consensus_decision="AUTHORIZE")
        self.assertEqual(result.state, IntentState.REPAIR_REQUIRED)
        self.assertEqual(result.reason, "SOURCE_NOT_APPROVED")

    def test_policy_requires_explicit_recipient_allowlist(self):
        with self.assertRaises(ValueError):
            Policy(**{**policy().__dict__, "allowed_recipients": frozenset()}).validate()


if __name__ == "__main__":
    unittest.main()
