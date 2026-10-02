from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentState(str, Enum):
    PENDING = "PENDING"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


TERMINAL_STATES = {
    IntentState.AUTHORIZED,
    IntentState.DENIED,
    IntentState.EXPIRED,
    IntentState.CONSUMED,
}

MAX_ATTESTATIONS = 8
MAX_PROVIDER_ID_BYTES = 128
MAX_RESOURCE_BYTES = 2048
MAX_STATEMENT_BYTES = 8192


def _validate_json_value(value: Any) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        raise ValueError("floating-point values are forbidden in canonical data")
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical object keys must be strings")
        for item in value.values():
            _validate_json_value(item)
        return
    raise ValueError(f"unsupported canonical value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    _validate_json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def action_subject(*, agent: str, action_type: str, target: str, recipient: str, value: int, payload_hash: str) -> str:
    return digest_hex(
        {
            "agent": agent,
            "action_type": action_type,
            "target": target,
            "recipient": recipient,
            "value": value,
            "payload_hash": payload_hash,
        }
    )


def action_intent(*, intent_id: str, subject: str, policy_id: str, policy_version: int) -> str:
    return digest_hex(
        {
            "intent_id": intent_id,
            "subject": subject,
            "policy_id": policy_id,
            "policy_version": policy_version,
        }
    )


@dataclass(frozen=True)
class Attestation:
    provider_id: str
    resource: str
    published_at: int
    observed_at: int
    expires_at: int
    payload_hash: str
    signature: str
    statement: str = ""

    def signed_payload(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "resource": self.resource,
            "published_at": self.published_at,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "payload_hash": self.payload_hash,
            "statement": self.statement,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.signed_payload(), "signature": self.signature}


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version: int
    approved_agents: frozenset[str]
    allowed_action_types: frozenset[str]
    allowed_recipients: frozenset[str]
    approved_sources: dict[str, str]
    max_value: int
    required_sources: frozenset[str]
    minimum_attestations: int
    maximum_age_seconds: int
    intent_ttl_seconds: int
    repair_window_seconds: int
    active: bool = True

    def validate(self) -> None:
        if not self.policy_id or self.version <= 0:
            raise ValueError("invalid policy identity")
        if not self.approved_agents or not self.allowed_action_types or not self.allowed_recipients:
            raise ValueError("policy allowlists cannot be empty")
        if self.max_value < 0 or self.minimum_attestations <= 0:
            raise ValueError("invalid policy limits")
        if self.intent_ttl_seconds <= 0 or self.repair_window_seconds <= 0:
            raise ValueError("invalid policy windows")
        if self.maximum_age_seconds <= 0:
            raise ValueError("invalid evidence age")
        if len(self.required_sources) > MAX_ATTESTATIONS or self.minimum_attestations > MAX_ATTESTATIONS:
            raise ValueError("evidence limits exceed backend maximum")
        if not self.required_sources.issubset(self.approved_sources):
            raise ValueError("required source is not approved")
        if self.minimum_attestations < len(self.required_sources):
            raise ValueError("minimum attestations cannot omit required sources")
        for source_id, prefix in self.approved_sources.items():
            if not source_id or not _safe_https_reference(prefix):
                raise ValueError("approved sources must use canonical HTTPS prefixes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "approved_agents": sorted(self.approved_agents),
            "allowed_action_types": sorted(self.allowed_action_types),
            "allowed_recipients": sorted(self.allowed_recipients),
            "approved_sources": dict(sorted(self.approved_sources.items())),
            "max_value": self.max_value,
            "required_sources": sorted(self.required_sources),
            "minimum_attestations": self.minimum_attestations,
            "maximum_age_seconds": self.maximum_age_seconds,
            "intent_ttl_seconds": self.intent_ttl_seconds,
            "repair_window_seconds": self.repair_window_seconds,
            "active": self.active,
        }


@dataclass
class Intent:
    intent_id: str
    policy_id: str
    policy_version: int
    agent: str
    action_type: str
    target: str
    recipient: str
    value: int
    payload_hash: str
    created_at: int
    expires_at: int
    repair_deadline: int
    action_subject: str
    action_intent: str
    evidence_revision: int = 0
    state: IntentState = IntentState.PENDING
    reason: str = ""
    attestations: list[Attestation] = field(default_factory=list)
    receipt_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "agent": self.agent,
            "action_type": self.action_type,
            "target": self.target,
            "recipient": self.recipient,
            "value": self.value,
            "payload_hash": self.payload_hash,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "repair_deadline": self.repair_deadline,
            "action_subject": self.action_subject,
            "action_intent": self.action_intent,
            "evidence_revision": self.evidence_revision,
            "state": self.state.value,
            "reason": self.reason,
            "attestations": [item.to_dict() for item in self.attestations],
            "receipt_id": self.receipt_id,
        }


@dataclass
class Receipt:
    receipt_id: str
    intent_id: str
    action_intent: str
    consumer: str
    expires_at: int
    consumed_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _safe_https_reference(value: str) -> bool:
    if not value.startswith("https://") or any(char in value for char in ("\\", "?", "#", "%")):
        return False
    rest = value[8:]
    slash = rest.find("/")
    if slash <= 0:
        return False
    authority = rest[:slash]
    if "@" in authority or any(char.isspace() for char in authority):
        return False
    return all(segment not in {".", ".."} for segment in value[8 + slash :].split("/"))
