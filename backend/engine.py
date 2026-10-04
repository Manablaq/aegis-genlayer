from __future__ import annotations

# Optional production dependency is declared in requirements.txt and startup
# fails closed when it is unavailable.
# pyright: reportMissingImports=false

import hashlib
import threading
import time
from typing import Any, Callable, Protocol, cast

from .models import (
    TERMINAL_STATES,
    Attestation,
    Intent,
    IntentState,
    MAX_ATTESTATIONS,
    Policy,
    Receipt,
    _safe_https_reference,
    action_intent,
    action_subject,
    chain_action_intent,
    chain_action_subject,
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
        except Exception:  # cryptography raises InvalidSignature for hostile evidence
            return False
        return True


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
        self._lock = threading.RLock()
        self.policies: dict[str, Policy] = {}
        self.intents: dict[str, Intent] = {}
        self.receipts: dict[str, Receipt] = {}
        if store is not None:
            snapshot = store.load()
            if snapshot:
                self._restore(snapshot)

    def register_policy(self, policy: Policy) -> None:
        with self._lock:
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
        onchain_target_hash: str | None = None,
        expires_at: int | None = None,
    ) -> Intent:
        with self._lock:
            policy = self._policy(policy_id, policy_version)
            if intent_id in self.intents:
                raise ValidationError("INTENT_ALREADY_EXISTS")
            if not _is_digest(intent_id) or not _is_digest(payload_hash):
                raise ValidationError("DIGEST_FORMAT")
            if len(attestations) > MAX_ATTESTATIONS:
                raise ValidationError("EVIDENCE_COUNT")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValidationError("VALUE_FORMAT")
            if not all(isinstance(field, str) and field for field in (agent, action_type, target, recipient)):
                raise ValidationError("ACTION_FIELDS_EMPTY")
            if onchain_target_hash is not None:
                if policy.onchain_action_hash is None:
                    raise ValidationError("ONCHAIN_ACTION_HASH_NOT_CONFIGURED")
                if not _is_digest(onchain_target_hash):
                    raise ValidationError("ONCHAIN_TARGET_DIGEST")
            if expires_at is not None and onchain_target_hash is None:
                raise ValidationError("EXPIRES_AT_REQUIRES_ONCHAIN_BINDING")
            now = self.clock()
            effective_expires_at = now + policy.intent_ttl_seconds if expires_at is None else expires_at
            if isinstance(effective_expires_at, bool) or not isinstance(effective_expires_at, int):
                raise ValidationError("EXPIRES_AT_FORMAT")
            if effective_expires_at <= now or effective_expires_at > now + policy.intent_ttl_seconds:
                raise ValidationError("INTENT_LIMIT")
            evidence_digest = _attestation_fingerprint(attestations)
            if onchain_target_hash is None:
                subject = action_subject(
                    agent=agent,
                    action_type=action_type,
                    target=target,
                    recipient=recipient,
                    value=value,
                    payload_hash=payload_hash,
                )
                intent_digest = action_intent(
                    intent_id=intent_id,
                    subject=subject,
                    policy_id=policy_id,
                    policy_version=policy_version,
                )
                stored_target_hash = None
                stored_evidence_digest = None
            else:
                subject = chain_action_subject(
                    action_hash=policy.onchain_action_hash,
                    target_hash=onchain_target_hash,
                    payload_hash=payload_hash,
                    agent=agent,
                    consumer=recipient,
                    value=value,
                )
                intent_digest = chain_action_intent(intent_id=intent_id, subject=subject, policy_id=policy_id)
                stored_target_hash = onchain_target_hash
                stored_evidence_digest = evidence_digest
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
                expires_at=effective_expires_at,
                repair_deadline=effective_expires_at + policy.repair_window_seconds,
                action_subject=subject,
                action_intent=intent_digest,
                attestations=list(attestations),
                onchain_target_hash=stored_target_hash,
                onchain_evidence_digest=stored_evidence_digest,
            )
            self.intents[intent_id] = record
            self._persist()
            return record

    def evaluate(self, *, intent_id: str, consensus_decision: str) -> Intent:
        with self._lock:
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

    def evaluate_genlayer(self, *, intent_id: str, consensus_decision: str) -> Intent:
        """Apply a decision already proven by the bound GenLayer firewall.

        This path deliberately does not accept a caller-supplied decision as
        authority. The HTTP adapter must verify a finalized Bradbury receipt,
        exact gateway calldata, and matching on-chain intent state first.
        """
        with self._lock:
            intent = self._intent(intent_id)
            if intent.state != IntentState.PENDING:
                raise DecisionError("INTENT_NOT_PENDING")
            if intent.onchain_target_hash is None or intent.onchain_evidence_digest is None:
                raise DecisionError("GENLAYER_BINDING_REQUIRED")
            if consensus_decision not in {"AUTHORIZE", "DENY"}:
                raise DecisionError("DECISION_TOKEN")
            if consensus_decision == "DENY":
                intent.state = IntentState.DENIED
                intent.reason = "GENLAYER_FINALIZED_DENIED"
                self._persist()
                return intent
            intent.state = IntentState.AUTHORIZED
            intent.reason = "GENLAYER_FINALIZED_AUTHORIZED"
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
        with self._lock:
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
            if intent.onchain_target_hash is not None:
                intent.onchain_evidence_digest = _attestation_fingerprint(attestations)
            intent.state = IntentState.PENDING
            intent.reason = "EVIDENCE_REPLACED"
            self._persist()
            return intent

    def consume_receipt(self, *, receipt_id: str, consumer: str, action_intent_value: str) -> Receipt:
        with self._lock:
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
        with self._lock:
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
                not _valid_attestation_shape(attestation)
            ):
                return "EVIDENCE_FORMAT"
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
        policy_values = _mapping(snapshot, "policies")
        for key, value in policy_values.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("invalid persisted policy record")
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
                onchain_action_hash=raw.get("onchain_action_hash"),
            )
            policy.validate()
            if key != f"{policy.policy_id}:{policy.version}":
                raise ValueError("persisted policy key mismatch")
            self.policies[key] = policy
        intent_values = _mapping(snapshot, "intents")
        for key, value in intent_values.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("invalid persisted intent record")
            raw = cast(dict[str, Any], value)
            intent = Intent(
                intent_id=raw["intent_id"], policy_id=raw["policy_id"], policy_version=int(raw["policy_version"]),
                agent=raw["agent"], action_type=raw["action_type"], target=raw["target"], recipient=raw["recipient"],
                value=int(raw["value"]), payload_hash=raw["payload_hash"], created_at=int(raw["created_at"]),
                expires_at=int(raw["expires_at"]), repair_deadline=int(raw["repair_deadline"]),
                action_subject=raw["action_subject"], action_intent=raw["action_intent"],
                evidence_revision=int(raw["evidence_revision"]), state=IntentState(raw["state"]),
                reason=raw["reason"], attestations=[Attestation(**item) for item in raw["attestations"]],
                receipt_id=raw["receipt_id"],
                onchain_target_hash=raw.get("onchain_target_hash"),
                onchain_evidence_digest=raw.get("onchain_evidence_digest"),
            )
            if key != intent.intent_id or not _is_digest(intent.intent_id) or not _is_digest(intent.payload_hash):
                raise ValueError("persisted intent identity mismatch")
            if f"{intent.policy_id}:{intent.policy_version}" not in self.policies:
                raise ValueError("persisted intent policy missing")
            if not all(isinstance(field, str) and field for field in (intent.agent, intent.action_type, intent.target, intent.recipient)):
                raise ValueError("persisted intent action fields invalid")
            if isinstance(intent.value, bool) or intent.value < 0:
                raise ValueError("persisted intent value invalid")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (intent.created_at, intent.expires_at, intent.repair_deadline, intent.evidence_revision)):
                raise ValueError("persisted intent timestamps invalid")
            if not intent.created_at <= intent.expires_at <= intent.repair_deadline:
                raise ValueError("persisted intent deadline order invalid")
            if intent.evidence_revision < 0:
                raise ValueError("persisted evidence revision invalid")
            policy = self.policies[f"{intent.policy_id}:{intent.policy_version}"]
            if intent.onchain_target_hash is None:
                if intent.onchain_evidence_digest is not None:
                    raise ValueError("persisted onchain evidence binding mismatch")
                expected_subject = action_subject(
                    agent=intent.agent,
                    action_type=intent.action_type,
                    target=intent.target,
                    recipient=intent.recipient,
                    value=intent.value,
                    payload_hash=intent.payload_hash,
                )
                expected_action_intent = action_intent(
                    intent_id=intent.intent_id,
                    subject=intent.action_subject,
                    policy_id=intent.policy_id,
                    policy_version=intent.policy_version,
                )
            else:
                if policy.onchain_action_hash is None or intent.onchain_evidence_digest is None:
                    raise ValueError("persisted onchain binding incomplete")
                expected_subject = chain_action_subject(
                    action_hash=policy.onchain_action_hash,
                    target_hash=intent.onchain_target_hash,
                    payload_hash=intent.payload_hash,
                    agent=intent.agent,
                    consumer=intent.recipient,
                    value=intent.value,
                )
                expected_action_intent = chain_action_intent(
                    intent_id=intent.intent_id,
                    subject=intent.action_subject,
                    policy_id=intent.policy_id,
                )
                if intent.onchain_evidence_digest != _attestation_fingerprint(intent.attestations):
                    raise ValueError("persisted onchain evidence digest mismatch")
            if intent.action_subject != expected_subject:
                raise ValueError("persisted action subject mismatch")
            if intent.action_intent != expected_action_intent:
                raise ValueError("persisted action intent mismatch")
            if not isinstance(intent.attestations, list):
                raise ValueError("persisted attestations invalid")
            for attestation in intent.attestations:
                attestation.validate()
            self.intents[key] = intent
        receipt_values = _mapping(snapshot, "receipts")
        for key, value in receipt_values.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("invalid persisted receipt record")
            receipt = Receipt(**cast(dict[str, Any], value))
            if key != receipt.receipt_id or not _is_digest(receipt.receipt_id) or not _is_digest(receipt.intent_id):
                raise ValueError("persisted receipt identity mismatch")
            intent = self.intents.get(receipt.intent_id)
            if intent is None or receipt.action_intent != intent.action_intent or receipt.consumer != intent.recipient:
                raise ValueError("persisted receipt binding mismatch")
            if receipt.expires_at != intent.expires_at:
                raise ValueError("persisted receipt expiry mismatch")
            if receipt.consumed_at is not None and (isinstance(receipt.consumed_at, bool) or not isinstance(receipt.consumed_at, int)):
                raise ValueError("persisted receipt consumption timestamp invalid")
            self.receipts[key] = receipt
        for intent in self.intents.values():
            receipt = self.receipts.get(intent.receipt_id or "")
            if intent.state in {IntentState.AUTHORIZED, IntentState.CONSUMED}:
                if receipt is None:
                    raise ValueError("persisted authorized intent has no receipt")
                if intent.state == IntentState.CONSUMED and receipt.consumed_at is None:
                    raise ValueError("persisted consumed intent has unconsumed receipt")
                if intent.state == IntentState.AUTHORIZED and receipt.consumed_at is not None:
                    raise ValueError("persisted authorized intent has consumed receipt")
            elif intent.receipt_id is not None:
                raise ValueError("persisted non-authorized intent has receipt")


def _mapping(value: dict[str, object], field: str) -> dict[str, object]:
    raw = value.get(field)
    if not isinstance(raw, dict):
        raise ValueError(f"persisted {field} must be an object")
    return raw


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _valid_attestation_shape(attestation: Attestation) -> bool:
    try:
        attestation.validate()
    except (TypeError, UnicodeError, ValueError):
        return False
    return True


def _attestation_fingerprint(items: list[Attestation]) -> str:
    return hashlib.sha256(canonical_bytes([item.to_dict() for item in items])).hexdigest()
