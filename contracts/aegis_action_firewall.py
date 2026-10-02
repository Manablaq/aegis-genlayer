# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Aegis' immutable receipt and intent state machine.

The decision gateway is a separately deployed GenLayer contract whose own
transaction reaches protocol finality. This contract accepts only a gateway
commitment bound to the exact intent, action intent, and decision token. It has
no upgrade, emergency, arbitrary-call, or receipt-replay path.
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import typing

from genlayer import *


STATE_PENDING = u256(1)
STATE_REPAIR_REQUIRED = u256(2)
STATE_AUTHORIZED = u256(3)
STATE_DENIED = u256(4)
STATE_EXPIRED = u256(5)
STATE_CONSUMED = u256(6)
DECISION_AUTHORIZE = "AUTHORIZE"
DECISION_DENY = "DENY"
DOMAIN_SUBJECT = hashlib.sha256(b"AEGIS/V1/ACTION_SUBJECT").digest()
DOMAIN_INTENT = hashlib.sha256(b"AEGIS/V1/ACTION_INTENT").digest()
DOMAIN_DECISION = hashlib.sha256(b"AEGIS/V1/DECISION_COMMITMENT").digest()
DOMAIN_RECEIPT = hashlib.sha256(b"AEGIS/V1/RECEIPT_ID").digest()
MAX_POLICY_ID_BYTES = 128
MAX_ACTION_HASH_BYTES = 32
MAX_EVIDENCE_DIGEST_BYTES = 32


@allow_storage
@dataclass
class PolicyRecord:
    agent: Address
    consumer: Address
    action_hash: bytes
    max_value: u256
    intent_ttl_seconds: u256
    repair_window_seconds: u256
    active: bool


@allow_storage
@dataclass
class IntentRecord:
    state: u256
    agent: Address
    consumer: Address
    action_hash: bytes
    target_hash: bytes
    payload_hash: bytes
    value: u256
    created_at: u256
    expires_at: u256
    repair_deadline: u256
    evidence_digest: bytes
    evidence_revision: u256
    action_subject: bytes
    action_intent: bytes
    receipt_id: bytes
    decision_commitment: bytes
    reason: str


@allow_storage
@dataclass
class ReceiptRecord:
    intent_id: bytes
    action_intent: bytes
    consumer: Address
    expires_at: u256
    consumed: bool


def _hash(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _u256(value: u256) -> bytes:
    return int(value).to_bytes(32, byteorder="big", signed=False)


def _now() -> u256:
    raw = gl.message_raw["datetime"]
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return u256(int(parsed.timestamp()))


def _require_digest(value: bytes, field: str) -> None:
    if len(value) != 32:
        raise gl.vm.UserError(field + "_DIGEST")


def _require_policy_id(value: str) -> str:
    if not value or len(value.encode("utf-8")) > MAX_POLICY_ID_BYTES:
        raise gl.vm.UserError("POLICY_ID")
    return value


class AegisActionFirewall(gl.Contract):
    owner: Address
    decision_gateway: Address
    policies: TreeMap[str, PolicyRecord]
    intents: TreeMap[bytes, IntentRecord]
    receipts: TreeMap[bytes, ReceiptRecord]

    def __init__(self, decision_gateway: Address) -> None:
        if decision_gateway == Address("0x" + "00" * 20):
            raise gl.vm.UserError("GATEWAY_ZERO")
        self.owner = gl.message.sender_address
        self.decision_gateway = decision_gateway

    @gl.public.write
    def register_policy(
        self,
        policy_id: str,
        agent: Address,
        consumer: Address,
        action_hash: bytes,
        max_value: u256,
        intent_ttl_seconds: u256,
        repair_window_seconds: u256,
    ) -> None:
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("OWNER_ONLY")
        key = _require_policy_id(policy_id)
        if self.policies.get(key, None) is not None:
            raise gl.vm.UserError("POLICY_IMMUTABLE")
        if len(action_hash) != MAX_ACTION_HASH_BYTES:
            raise gl.vm.UserError("ACTION_HASH")
        if max_value < u256(0) or intent_ttl_seconds <= u256(0) or repair_window_seconds <= u256(0):
            raise gl.vm.UserError("POLICY_LIMIT")
        self.policies[key] = PolicyRecord(
            agent=agent,
            consumer=consumer,
            action_hash=action_hash,
            max_value=max_value,
            intent_ttl_seconds=intent_ttl_seconds,
            repair_window_seconds=repair_window_seconds,
            active=True,
        )

    @gl.public.write
    def deactivate_policy(self, policy_id: str) -> None:
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("OWNER_ONLY")
        key = _require_policy_id(policy_id)
        policy = self.policies.get(key, None)
        if policy is None:
            raise gl.vm.UserError("POLICY_UNKNOWN")
        policy.active = False
        self.policies[key] = policy

    @gl.public.write
    def submit_intent(
        self,
        intent_id: bytes,
        policy_id: str,
        action_hash: bytes,
        target_hash: bytes,
        payload_hash: bytes,
        value: u256,
        expires_at: u256,
        evidence_digest: bytes,
    ) -> bytes:
        _require_digest(intent_id, "INTENT_ID")
        _require_digest(target_hash, "TARGET")
        _require_digest(payload_hash, "PAYLOAD")
        _require_digest(evidence_digest, "EVIDENCE")
        key = _require_policy_id(policy_id)
        policy = self.policies.get(key, None)
        if policy is None or not policy.active:
            raise gl.vm.UserError("POLICY_INACTIVE")
        if self.intents.get(intent_id, None) is not None:
            raise gl.vm.UserError("INTENT_EXISTS")
        if gl.message.sender_address != policy.agent:
            raise gl.vm.UserError("AGENT_ONLY")
        if action_hash != policy.action_hash:
            raise gl.vm.UserError("ACTION_NOT_APPROVED")
        now = _now()
        if value > policy.max_value or expires_at <= now or expires_at > now + policy.intent_ttl_seconds:
            raise gl.vm.UserError("INTENT_LIMIT")
        subject = _hash(
            DOMAIN_SUBJECT
            + action_hash
            + target_hash
            + payload_hash
            + gl.message.sender_address.as_bytes
            + policy.consumer.as_bytes
            + _u256(value)
        )
        action = _hash(DOMAIN_INTENT + intent_id + subject + key.encode("utf-8"))
        self.intents[intent_id] = IntentRecord(
            state=STATE_PENDING,
            agent=gl.message.sender_address,
            consumer=policy.consumer,
            action_hash=action_hash,
            target_hash=target_hash,
            payload_hash=payload_hash,
            value=value,
            created_at=now,
            expires_at=expires_at,
            repair_deadline=expires_at + policy.repair_window_seconds,
            evidence_digest=evidence_digest,
            evidence_revision=u256(0),
            action_subject=subject,
            action_intent=action,
            receipt_id=b"",
            decision_commitment=b"",
            reason="PENDING",
        )
        return action

    @gl.public.write
    def mark_repair_required(self, intent_id: bytes, reason: str) -> None:
        if gl.message.sender_address != self.decision_gateway:
            raise gl.vm.UserError("GATEWAY_ONLY")
        intent = self._intent(intent_id)
        if intent.state != STATE_PENDING:
            raise gl.vm.UserError("NOT_PENDING")
        if _now() >= intent.expires_at:
            intent.state = STATE_EXPIRED
            intent.reason = "INTENT_EXPIRED"
        else:
            intent.state = STATE_REPAIR_REQUIRED
            intent.reason = reason
        self.intents[intent_id] = intent

    @gl.public.write
    def replace_evidence(self, intent_id: bytes, evidence_digest: bytes) -> None:
        _require_digest(evidence_digest, "EVIDENCE")
        intent = self._intent(intent_id)
        if gl.message.sender_address != intent.agent:
            raise gl.vm.UserError("AGENT_ONLY")
        if intent.state != STATE_REPAIR_REQUIRED:
            raise gl.vm.UserError("REPAIR_REQUIRED")
        if _now() >= intent.repair_deadline:
            intent.state = STATE_EXPIRED
            intent.reason = "REPAIR_DEADLINE_EXPIRED"
        elif evidence_digest == intent.evidence_digest:
            raise gl.vm.UserError("EVIDENCE_UNCHANGED")
        else:
            intent.evidence_digest = evidence_digest
            intent.evidence_revision += u256(1)
            intent.state = STATE_PENDING
            intent.reason = "EVIDENCE_REPLACED"
        self.intents[intent_id] = intent

    @gl.public.write
    def record_decision(self, intent_id: bytes, decision: str, commitment: bytes) -> bytes:
        if gl.message.sender_address != self.decision_gateway:
            raise gl.vm.UserError("GATEWAY_ONLY")
        intent = self._intent(intent_id)
        if intent.state != STATE_PENDING:
            raise gl.vm.UserError("NOT_PENDING")
        if _now() >= intent.expires_at:
            intent.state = STATE_EXPIRED
            intent.reason = "INTENT_EXPIRED"
            self.intents[intent_id] = intent
            return b""
        if decision not in (DECISION_AUTHORIZE, DECISION_DENY):
            raise gl.vm.UserError("DECISION_TOKEN")
        expected = _hash(DOMAIN_DECISION + intent.action_intent + decision.encode("ascii"))
        if commitment != expected:
            raise gl.vm.UserError("DECISION_BINDING")
        intent.decision_commitment = commitment
        if decision == DECISION_DENY:
            intent.state = STATE_DENIED
            intent.reason = "CONSENSUS_DENIED"
            self.intents[intent_id] = intent
            return b""
        receipt_id = _hash(DOMAIN_RECEIPT + intent_id + intent.action_intent)
        intent.state = STATE_AUTHORIZED
        intent.reason = "CONSENSUS_AUTHORIZED"
        intent.receipt_id = receipt_id
        self.receipts[receipt_id] = ReceiptRecord(
            intent_id=intent_id,
            action_intent=intent.action_intent,
            consumer=intent.consumer,
            expires_at=intent.expires_at,
            consumed=False,
        )
        self.intents[intent_id] = intent
        return receipt_id

    @gl.public.write
    def expire(self, intent_id: bytes) -> None:
        intent = self._intent(intent_id)
        if intent.state not in (STATE_PENDING, STATE_REPAIR_REQUIRED):
            raise gl.vm.UserError("NOT_EXPIRABLE")
        if _now() < (intent.repair_deadline if intent.state == STATE_REPAIR_REQUIRED else intent.expires_at):
            raise gl.vm.UserError("NOT_EXPIRED")
        intent.state = STATE_EXPIRED
        intent.reason = "EXPIRED"
        self.intents[intent_id] = intent

    @gl.public.write
    def consume_receipt(self, receipt_id: bytes, action_intent: bytes) -> None:
        _require_digest(receipt_id, "RECEIPT_ID")
        _require_digest(action_intent, "ACTION_INTENT")
        receipt = self.receipts.get(receipt_id, None)
        if receipt is None or receipt.consumed:
            raise gl.vm.UserError("RECEIPT_CONSUMED_OR_UNKNOWN")
        if gl.message.sender_address != receipt.consumer:
            raise gl.vm.UserError("CONSUMER_ONLY")
        if receipt.action_intent != action_intent or _now() >= receipt.expires_at:
            raise gl.vm.UserError("RECEIPT_BINDING")
        intent = self._intent(receipt.intent_id)
        if intent.state != STATE_AUTHORIZED:
            raise gl.vm.UserError("INTENT_NOT_AUTHORIZED")
        receipt.consumed = True
        self.receipts[receipt_id] = receipt
        intent.state = STATE_CONSUMED
        intent.reason = "CONSUMED"
        self.intents[receipt.intent_id] = intent

    @gl.public.view
    def get_intent(self, intent_id: bytes) -> dict[str, typing.Any]:
        intent = self._intent(intent_id)
        return {
            "state": intent.state,
            "agent": intent.agent,
            "consumer": intent.consumer,
            "expires_at": intent.expires_at,
            "repair_deadline": intent.repair_deadline,
            "evidence_revision": intent.evidence_revision,
            "action_subject": intent.action_subject,
            "action_intent": intent.action_intent,
            "receipt_id": intent.receipt_id,
            "reason": intent.reason,
        }

    def _intent(self, intent_id: bytes) -> IntentRecord:
        _require_digest(intent_id, "INTENT_ID")
        intent = self.intents.get(intent_id, None)
        if intent is None:
            raise gl.vm.UserError("INTENT_UNKNOWN")
        return intent
