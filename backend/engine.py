from __future__ import annotations

# Optional production dependency is declared in requirements.txt and startup
# fails closed when it is unavailable.
# pyright: reportMissingImports=false

import hashlib
import time
from dataclasses import asdict
from typing import Any, Callable, Protocol, cast

from .models import (
    TERMINAL_STATES,
    Attestation,
    Intent,
    IntentState,
    MAX_ATTESTATIONS,
    MAX_PROVIDER_ID_BYTES,
    MAX_RESOURCE_BYTES,
    MAX_STATEMENT_BYTES,
    Policy,
    Receipt,
    _safe_https_reference,
    action_intent,
    action_subject,
    canonical_bytes,
    digest_hex,
)
from .store import JsonStore


class ValidationError(ValueError):
    pass


class DecisionError(RuntimeError):
    pass


class AttestationVerifier(Protocol):
    def verify(self, attestation: Attestation) -> bool: ...


class StaticVerifier:
    """Explicit test verifier; production must use Ed25519Verifier."""

    def __init__(self, valid_signatures: set[str] | None = None):
        self.valid_signatures = valid_signatures or set()

    def verify(self, attestation: Attestation) -> bool:
        return attestation.signature in self.valid_signatures


class Ed25519Verifier:
    """Verify provider-signed attestations and fail closed if crypto is absent."""

    def __init__(self, public_keys_hex: dict[str, str]):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as exc:  # pragma: no cover - exercised in deployment packaging
            raise RuntimeError("cryptography is required for production verification") from exc
        self._ed25519 = Ed25519PublicKey
        self._keys = {
            provider: Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
            for provider, public_key in public_keys_hex.items()
        }

    def verify(self, attestation: Attestation) -> bool:
        key = self._keys.get(attestation.provider_id)
        if key is None:
            return False
        try:
            key.verify(bytes.fromhex(attestation.signature), canonical_bytes(attestation.signed_payload()))
            return True
        except (ValueError, TypeError):
            return False


def _now() -> int:
    return int(time.time())


class AegisEngine:
    def __init__(
        self,
        *,
        verifier: AttestationVerifier,
        clock: Callable[[], int] = _now,
        store: JsonStore | None = None,
    ):
        self.verifier = verifier
        self.clock = clock
        self.store = store
        self.policies: dict[str, Policy] = {}
        self.intents: dict[str, Intent] = {}
        self.receipts: dict[str, Receipt] = {}
        if store is not None:
            snapshot = store.load()
            if snapshot:
                self._restore(snapshot)

    def register_policy(self, policy: Policy) -> None:
        policy.validate()
        key = f"{policy.policy_id}:{policy.version}"
        if key in self.policies:
            raise ValidationError("POLICY_VERSION_ALREADY_EXISTS")
        self.policies[key] = policy
        self._persist()

    def create_intent(
        self,
        *,
        intent_id: str,
        policy_id: str,
        policy_version: int,
        agent: str,
        action_type: str,
        target: str,
        recipient: str,
        value: int,
        payload_hash: str,
        attestations: list[Attestation],
    ) -> Intent:
        policy = self._policy(policy_id, policy_version)
        if intent_id in self.intents:
            raise ValidationError("INTENT_ALREADY_EXISTS")
        if not _is_digest(intent_id) or not _is_digest(payload_hash):
            raise ValidationError("DIGEST_FORMAT")
        if len(attestations) > MAX_ATTESTATIONS:
            raise ValidationError("EVIDENCE_COUNT")
        if value < 0:
            raise ValidationError("VALUE_NEGATIVE")
        if not all((agent, action_type, target, recipient)):
            raise ValidationError("ACTION_FIELDS_EMPTY")
        now = self.clock()
        expires_at = now + policy.intent_ttl_seconds
        subject = action_subject(
            agent=agent,
            action_type=action_type,
            target=target,
            recipient=recipient,
            value=value,
            payload_hash=payload_hash,
        )
        record = Intent(
            intent_id=intent_id,
            policy_id=policy_id,
            policy_version=policy_version,
            agent=agent,
            action_type=action_type,
            target=target,
            recipient=recipient,
            value=value,
            payload_hash=payload_hash,
            created_at=now,
            expires_at=expires_at,
            repair_deadline=expires_at + policy.repair_window_seconds,
            action_subject=subject,
            action_intent=action_intent(
                intent_id=intent_id,
                subject=subject,
                policy_id=policy_id,
                policy_version=policy_version,
            ),
            attestations=list(attestations),
        )
        self.intents[intent_id] = record
        self._persist()
        return record

    def evaluate(self, *, intent_id: str, consensus_decision: str) -> Intent:
        intent = self._intent(intent_id)
        now = self.clock()
        if intent.state in TERMINAL_STATES:
            raise DecisionError("TERMINAL_INTENT")
        if now >= intent.expires_at:
            intent.state = IntentState.EXPIRED
            intent.reason = "INTENT_EXPIRED"
            self._persist()
            return intent
        policy = self._policy(intent.policy_id, intent.policy_version)
        deterministic_reason = self._deterministic_failure(intent, policy)
        if deterministic_reason:
            intent.state = IntentState.DENIED
            intent.reason = deterministic_reason
            self._persist()
            return intent
        evidence_reason = self._evidence_failure(intent, policy, now)
        if evidence_reason:
            intent.state = IntentState.REPAIR_REQUIRED
            intent.reason = evidence_reason
            self._persist()
            return intent
        if consensus_decision not in {"AUTHORIZE", "DENY"}:
            raise DecisionError("INVALID_CONSENSUS_DECISION")
        if consensus_decision == "DENY":
            intent.state = IntentState.DENIED
            intent.reason = "CONSENSUS_DENIED"
        else:
            intent.state = IntentState.AUTHORIZED
            intent.reason = "CONSENSUS_AUTHORIZED"
            receipt_id = digest_hex({"domain": "AEGIS/RECEIPT/V1", "intent": intent.intent_id, "action_intent": intent.action_intent})
            intent.receipt_id = receipt_id
            self.receipts[receipt_id] = Receipt(
                receipt_id=receipt_id,
                intent_id=intent.intent_id,
                action_intent=intent.action_intent,
                consumer=intent.recipient,
                expires_at=intent.expires_at,
            )
        self._persist()
        return intent

    def replace_evidence(self, *, intent_id: str, caller: str, attestations: list[Attestation]) -> Intent:
        intent = self._intent(intent_id)
        now = self.clock()
        if intent.state != IntentState.REPAIR_REQUIRED:
            raise DecisionError("REPAIR_NOT_REQUIRED")
        if caller != intent.agent:
            raise DecisionError("AGENT_ONLY")
        if now >= intent.repair_deadline:
            intent.state = IntentState.EXPIRED
            intent.reason = "REPAIR_DEADLINE_EXPIRED"
            self._persist()
            return intent
        if _attestation_fingerprint(intent.attestations) == _attestation_fingerprint(attestations):
            raise ValidationError("EVIDENCE_UNCHANGED")
        if len(attestations) > MAX_ATTESTATIONS:
            raise ValidationError("EVIDENCE_COUNT")
        intent.attestations = list(attestations)
        intent.evidence_revision += 1
        intent.state = IntentState.PENDING
        intent.reason = "EVIDENCE_REPLACED"
        self._persist()
        return intent

    def consume_receipt(self, *, receipt_id: str, consumer: str, action_intent_value: str) -> Receipt:
        receipt = self.receipts.get(receipt_id)
        if receipt is None:
            raise DecisionError("RECEIPT_UNKNOWN")
        intent = self._intent(receipt.intent_id)
        if intent.state != IntentState.AUTHORIZED:
            raise DecisionError("INTENT_NOT_AUTHORIZED")
        if receipt.consumed_at is not None:
            raise DecisionError("RECEIPT_ALREADY_CONSUMED")
        if consumer != receipt.consumer:
            raise DecisionError("CONSUMER_MISMATCH")
        if action_intent_value != receipt.action_intent:
            raise DecisionError("ACTION_INTENT_MISMATCH")
        if self.clock() >= receipt.expires_at:
            raise DecisionError("RECEIPT_EXPIRED")
        receipt.consumed_at = self.clock()
        intent.state = IntentState.CONSUMED
        self._persist()
        return receipt

    def snapshot(self) -> dict[str, object]:
        return {
            "policies": {key: policy.to_dict() for key, policy in self.policies.items()},
            "intents": {key: intent.to_dict() for key, intent in self.intents.items()},
            "receipts": {key: receipt.to_dict() for key, receipt in self.receipts.items()},
        }

    def _deterministic_failure(self, intent: Intent, policy: Policy) -> str | None:
        if not policy.active:
            return "POLICY_INACTIVE"
        if intent.agent not in policy.approved_agents:
            return "AGENT_NOT_APPROVED"
        if intent.action_type not in policy.allowed_action_types:
            return "ACTION_NOT_APPROVED"
        if intent.recipient not in policy.allowed_recipients:
            return "RECIPIENT_NOT_APPROVED"
        if intent.value > policy.max_value:
            return "VALUE_OVER_LIMIT"
        return None

    def _evidence_failure(self, intent: Intent, policy: Policy, now: int) -> str | None:
        if len(intent.attestations) < policy.minimum_attestations:
            return "EVIDENCE_INSUFFICIENT"
        seen: set[str] = set()
        valid_sources: set[str] = set()
        for attestation in intent.attestations:
            if (
                not attestation.provider_id
                or len(attestation.provider_id.encode("utf-8")) > MAX_PROVIDER_ID_BYTES
                or len(attestation.resource.encode("utf-8")) > MAX_RESOURCE_BYTES
                or len(attestation.statement.encode("utf-8")) > MAX_STATEMENT_BYTES
            ):
                return "EVIDENCE_FIELD_LIMIT"
            if attestation.provider_id in seen:
                return "EVIDENCE_DUPLICATE_PROVIDER"
            seen.add(attestation.provider_id)
            prefix = policy.approved_sources.get(attestation.provider_id)
            if prefix is None or not _safe_https_reference(attestation.resource) or not attestation.resource.startswith(prefix):
                return "SOURCE_NOT_APPROVED"
            if not self.verifier.verify(attestation):
                return "ATTESTATION_SIGNATURE_INVALID"
            if attestation.published_at > now or attestation.observed_at > now:
                return "EVIDENCE_FROM_FUTURE"
            if attestation.expires_at <= now:
                return "EVIDENCE_EXPIRED"
            if attestation.expires_at <= attestation.observed_at or attestation.observed_at < attestation.published_at:
                return "EVIDENCE_TIME_ORDER"
            if now - attestation.observed_at > policy.maximum_age_seconds:
                return "EVIDENCE_STALE"
            if not _is_digest(attestation.payload_hash):
                return "EVIDENCE_DIGEST_INVALID"
            valid_sources.add(attestation.provider_id)
        if not policy.required_sources.issubset(valid_sources):
            return "REQUIRED_SOURCE_MISSING"
        return None

    def _policy(self, policy_id: str, version: int) -> Policy:
        policy = self.policies.get(f"{policy_id}:{version}")
        if policy is None:
            raise ValidationError("POLICY_UNKNOWN")
        return policy

    def _intent(self, intent_id: str) -> Intent:
        intent = self.intents.get(intent_id)
        if intent is None:
            raise ValidationError("INTENT_UNKNOWN")
        return intent

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save(self.snapshot())

    def _restore(self, snapshot: dict[str, object]) -> None:
        # Restore is deliberately strict: malformed persisted state prevents
        # startup instead of silently dropping security-critical records.
        policy_values = cast(dict[str, Any], snapshot.get("policies", {}))
        for key, value in policy_values.items():
            raw = cast(dict[str, Any], value)
            policy = Policy(
                policy_id=raw["policy_id"], version=int(raw["version"]),
                approved_agents=frozenset(raw["approved_agents"]),
                allowed_action_types=frozenset(raw["allowed_action_types"]),
                allowed_recipients=frozenset(raw["allowed_recipients"]),
                approved_sources=dict(raw["approved_sources"]), max_value=int(raw["max_value"]),
                required_sources=frozenset(raw["required_sources"]),
                minimum_attestations=int(raw["minimum_attestations"]),
                maximum_age_seconds=int(raw["maximum_age_seconds"]),
                intent_ttl_seconds=int(raw["intent_ttl_seconds"]),
                repair_window_seconds=int(raw["repair_window_seconds"]), active=bool(raw["active"]),
            )
            policy.validate()
            self.policies[key] = policy
        intent_values = cast(dict[str, Any], snapshot.get("intents", {}))
        for key, value in intent_values.items():
            raw = cast(dict[str, Any], value)
            self.intents[key] = Intent(
                intent_id=raw["intent_id"], policy_id=raw["policy_id"], policy_version=int(raw["policy_version"]),
                agent=raw["agent"], action_type=raw["action_type"], target=raw["target"], recipient=raw["recipient"],
                value=int(raw["value"]), payload_hash=raw["payload_hash"], created_at=int(raw["created_at"]),
                expires_at=int(raw["expires_at"]), repair_deadline=int(raw["repair_deadline"]),
                action_subject=raw["action_subject"], action_intent=raw["action_intent"],
                evidence_revision=int(raw["evidence_revision"]), state=IntentState(raw["state"]),
                reason=raw["reason"], attestations=[Attestation(**item) for item in raw["attestations"]],
                receipt_id=raw["receipt_id"],
            )
        receipt_values = cast(dict[str, Any], snapshot.get("receipts", {}))
        for key, value in receipt_values.items():
            self.receipts[key] = Receipt(**cast(dict[str, Any], value))


def _is_digest(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _attestation_fingerprint(items: list[Attestation]) -> str:
    return hashlib.sha256(canonical_bytes([item.to_dict() for item in items])).hexdigest()
