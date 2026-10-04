from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


class GenLayerAuthorityError(ValueError):
    """Stable, non-sensitive error raised when a GenLayer proof is invalid."""


_DIGEST_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_RAW_DIGEST_RE = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_MAX_RPC_RESPONSE_BYTES = 4 * 1024 * 1024

# Deployed repair-capable Bradbury contracts. These defaults are source-matched
# to the current source and docs/BRADBURY_DEPLOYMENT_2026-10-02.md. They may
# only be changed explicitly.
DEFAULT_RPC_URL = "https://rpc-bradbury.genlayer.com"
DEFAULT_GATEWAY = "0x2a274E66687AF4f8FD6B3DAeffCf02C736233000"
DEFAULT_FIREWALL = "0x2D8CfEFf124eBCb813CA55ad90Ceff93a6d6E523"
DEFAULT_RPC_ORIGIN = "https://explorer-bradbury.genlayer.com"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _require_digest(value: str, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise GenLayerAuthorityError(f"{field}_FORMAT")
    return value.lower()


def _digest_bytes(value: str, field: str) -> bytes:
    if not isinstance(value, str) or not _RAW_DIGEST_RE.fullmatch(value):
        raise GenLayerAuthorityError(f"{field}_FORMAT")
    return bytes.fromhex(value.removeprefix("0x"))


def _hex_digest(value: Any, field: str) -> str:
    if not isinstance(value, bytes) or len(value) != 32:
        raise GenLayerAuthorityError(f"{field}_FORMAT")
    return "0x" + value.hex()


def _require_address(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ADDRESS_RE.fullmatch(value):
        raise GenLayerAuthorityError(f"{field}_FORMAT")
    return value.lower()


def _uleb128(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if index >= len(data):
            raise GenLayerAuthorityError("CALLDATA_TRUNCATED")
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index
        shift += 7
    raise GenLayerAuthorityError("CALLDATA_INTEGER_TOO_LARGE")


def _decode_calldata(data: bytes, index: int = 0) -> tuple[Any, int]:
    encoded, index = _uleb128(data, index)
    special = {0: None, 8: False, 16: True, 24: "__address__"}
    if encoded in special:
        value = special[encoded]
        if value != "__address__":
            return value, index
        end = index + 20
        if end > len(data):
            raise GenLayerAuthorityError("CALLDATA_TRUNCATED")
        return "0x" + data[index:end].hex(), end

    value_type = encoded & 0x07
    rest = encoded >> 3
    if value_type == 1:
        return rest, index
    if value_type == 2:
        return -1 - rest, index
    if value_type in {3, 4}:
        end = index + rest
        if end > len(data):
            raise GenLayerAuthorityError("CALLDATA_TRUNCATED")
        raw = data[index:end]
        if value_type == 3:
            return raw, end
        try:
            return raw.decode("utf-8"), end
        except UnicodeDecodeError as exc:
            raise GenLayerAuthorityError("CALLDATA_UTF8") from exc
    if value_type == 5:
        items: list[Any] = []
        for _ in range(rest):
            item, index = _decode_calldata(data, index)
            items.append(item)
        return items, index
    if value_type == 6:
        result: dict[str, Any] = {}
        previous_key: bytes | None = None
        for _ in range(rest):
            key_length, index = _uleb128(data, index)
            end = index + key_length
            if end > len(data):
                raise GenLayerAuthorityError("CALLDATA_TRUNCATED")
            key_bytes = data[index:end]
            index = end
            if previous_key is not None and key_bytes <= previous_key:
                raise GenLayerAuthorityError("CALLDATA_MAP_ORDER")
            previous_key = key_bytes
            try:
                key = key_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise GenLayerAuthorityError("CALLDATA_UTF8") from exc
            if key in result:
                raise GenLayerAuthorityError("CALLDATA_DUPLICATE_KEY")
            result[key], index = _decode_calldata(data, index)
        return result, index
    raise GenLayerAuthorityError("CALLDATA_TYPE")


def decode_genlayer_calldata(data: bytes) -> Any:
    value, index = _decode_calldata(data)
    if index != len(data):
        raise GenLayerAuthorityError("CALLDATA_TRAILING_BYTES")
    return value


def _rlp_decode_one(data: bytes, index: int = 0) -> tuple[bytes | list[Any], int]:
    if index >= len(data):
        raise GenLayerAuthorityError("RLP_TRUNCATED")
    prefix = data[index]
    index += 1
    if prefix <= 0x7F:
        return bytes([prefix]), index
    if prefix <= 0xB7:
        size = prefix - 0x80
        end = index + size
        if end > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
        return data[index:end], end
    if prefix <= 0xBF:
        length_size = prefix - 0xB7
        if index + length_size > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
        size = int.from_bytes(data[index:index + length_size], "big")
        index += length_size
        end = index + size
        if end > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
        return data[index:end], end
    if prefix <= 0xF7:
        size = prefix - 0xC0
        end = index + size
        if end > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
    else:
        length_size = prefix - 0xF7
        if index + length_size > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
        size = int.from_bytes(data[index:index + length_size], "big")
        index += length_size
        end = index + size
        if end > len(data):
            raise GenLayerAuthorityError("RLP_TRUNCATED")
    items: list[Any] = []
    while index < end:
        item, index = _rlp_decode_one(data, index)
        items.append(item)
    if index != end:
        raise GenLayerAuthorityError("RLP_LENGTH")
    return items, end


def decode_transaction_call_data(
    value: str,
    *,
    expected_intent_id: str | None = None,
    expected_method: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]+", value) or len(value) % 2:
        raise GenLayerAuthorityError("TX_CALLDATA_FORMAT")
    raw = bytes.fromhex(value)
    envelope, consumed = _rlp_decode_one(raw)
    if not isinstance(envelope, list) or len(envelope) != 2 or not isinstance(envelope[0], bytes):
        raise GenLayerAuthorityError("TX_CALLDATA_ENVELOPE")
    # Current Bradbury receipts expose a legacy envelope with one trailing
    # marker byte and an off-by-one string-length artifact. Accept that exact
    # shape or a correctly length-delimited envelope; never fall back to a
    # substring search for a method name or digest.
    if consumed == len(raw):
        pass
    elif consumed == len(raw) - 1 and envelope[1] == b"e":
        pass
    else:
        raise GenLayerAuthorityError("TX_CALLDATA_TRAILING_BYTES")
    try:
        call = _decode_calldata(envelope[0])[0]
    except GenLayerAuthorityError:
        raise
    allowed_methods = {expected_method} if expected_method is not None else {"decide", "edecid"}
    if not isinstance(call, dict) or call.get("method") not in allowed_methods:
        raise GenLayerAuthorityError("TX_CALLDATA_METHOD")
    args = call.get("args")
    if not isinstance(args, list) or not args or not isinstance(args[0], bytes) or len(args[0]) != 32:
        raise GenLayerAuthorityError("TX_CALLDATA_ARGS")
    if expected_intent_id is not None:
        expected = _digest_bytes(expected_intent_id, "INTENT_ID")
        if args[0] != expected:
            raise GenLayerAuthorityError("GENLAYER_INTENT_MISMATCH")
    return {"intent_id": "0x" + args[0].hex(), "method": call["method"], "args": args, "raw": raw.hex()}


def _encode_uleb128(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative ULEB128 value")
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def _encode_calldata(value: Any) -> bytes:
    if value is None:
        return b"\x00"
    if value is False:
        return b"\x08"
    if value is True:
        return b"\x10"
    if isinstance(value, int) and not isinstance(value, bool):
        if value >= 0:
            return _encode_uleb128((value << 3) | 1)
        return _encode_uleb128(((-value - 1) << 3) | 2)
    if isinstance(value, bytes):
        return _encode_uleb128((len(value) << 3) | 3) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _encode_uleb128((len(raw) << 3) | 4) + raw
    if isinstance(value, list):
        return _encode_uleb128((len(value) << 3) | 5) + b"".join(_encode_calldata(item) for item in value)
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: item[0].encode("utf-8"))
        return _encode_uleb128((len(items) << 3) | 6) + b"".join(
            _encode_uleb128(len(key.encode("utf-8"))) + key.encode("utf-8") + _encode_calldata(item)
            for key, item in items
        )
    raise TypeError(f"unsupported calldata value: {type(value).__name__}")


def _rlp_encode_bytes(value: bytes) -> bytes:
    if len(value) == 1 and value[0] < 0x80:
        return value
    if len(value) <= 55:
        return bytes([0x80 + len(value)]) + value
    size = len(value).to_bytes((len(value).bit_length() + 7) // 8, "big")
    return bytes([0xB7 + len(size)]) + size + value


def encode_read_call(method: str, args: list[Any]) -> str:
    call = _encode_calldata({"args": args, "method": method})
    payload = _rlp_encode_bytes(call) + _rlp_encode_bytes(b"\x00")
    size = len(payload)
    if size <= 55:
        envelope = bytes([0xC0 + size]) + payload
    else:
        size_bytes = size.to_bytes((size.bit_length() + 7) // 8, "big")
        envelope = bytes([0xF7 + len(size_bytes)]) + size_bytes + payload
    return "0x" + envelope.hex()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        raise GenLayerAuthorityError("RPC_REDIRECT_REJECTED")


@dataclass(frozen=True)
class GenLayerProof:
    transaction_id: str
    intent_id: str
    decision: str
    gateway: str
    status: str
    execution: str
    reason: str
    action_subject: str
    action_intent: str
    action_hash: str
    target_hash: str
    payload_hash: str
    evidence_digest: str
    agent: str
    consumer: str
    value: int
    expires_at: int
    repair_deadline: int


@dataclass(frozen=True)
class GenLayerLifecycleProof:
    transaction_id: str
    intent_id: str
    method: str
    status: str
    execution: str
    evidence_digest: str | None = None
    receipt_id: str | None = None
    action_intent: str | None = None


class GenLayerAuthority:
    def __init__(self, *, rpc_url: str, gateway: str, firewall: str, rpc_origin: str = DEFAULT_RPC_ORIGIN):
        parsed = urlsplit(rpc_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise RuntimeError("AEGIS_GENLAYER_RPC_URL must be an https URL without credentials")
        self.rpc_url = rpc_url
        self.gateway = _require_address(gateway, "GATEWAY")
        self.firewall = _require_address(firewall, "FIREWALL")
        self.rpc_origin = rpc_origin
        self._opener = urllib.request.build_opener(_NoRedirect())

    @classmethod
    def from_env(cls) -> "GenLayerAuthority":
        return cls(
            rpc_url=os.environ.get("AEGIS_GENLAYER_RPC_URL", DEFAULT_RPC_URL),
            gateway=os.environ.get("AEGIS_GENLAYER_GATEWAY", DEFAULT_GATEWAY),
            firewall=os.environ.get("AEGIS_GENLAYER_FIREWALL", DEFAULT_FIREWALL),
            rpc_origin=os.environ.get("AEGIS_GENLAYER_RPC_ORIGIN", DEFAULT_RPC_ORIGIN),
        )

    def _rpc(self, method: str, params: list[dict[str, Any]]) -> Any:
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}, separators=(",", ":")).encode()
        request = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": self.rpc_origin,
                "Referer": self.rpc_origin.rstrip("/") + "/",
                "User-Agent": "aegis-genlayer/1.0",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=10) as response:
                raw = response.read(_MAX_RPC_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GenLayerAuthorityError("GENLAYER_RPC_UNAVAILABLE") from exc
        if len(raw) > _MAX_RPC_RESPONSE_BYTES:
            raise GenLayerAuthorityError("GENLAYER_RPC_RESPONSE_TOO_LARGE")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GenLayerAuthorityError("GENLAYER_RPC_INVALID_JSON") from exc
        if not isinstance(payload, dict) or payload.get("error") is not None or "result" not in payload:
            raise GenLayerAuthorityError("GENLAYER_RPC_ERROR")
        return payload["result"]

    def _read_intent(self, intent_id: str) -> dict[str, Any]:
        result = self._rpc(
            "gen_call",
            [{"type": "read", "data": encode_read_call("get_intent", [bytes.fromhex(intent_id[2:])]), "from": ZERO_ADDRESS, "to": self.firewall, "status": "finalized"}],
        )
        if not isinstance(result, dict) or result.get("status", {}).get("code") != 0 or not isinstance(result.get("data"), str):
            raise GenLayerAuthorityError("GENLAYER_STATE_READ_FAILED")
        raw = result["data"]
        if raw.startswith("0x"):
            raw = raw[2:]
        try:
            value = decode_genlayer_calldata(bytes.fromhex(raw))
        except (ValueError, TypeError) as exc:
            raise GenLayerAuthorityError("GENLAYER_STATE_DECODE_FAILED") from exc
        if not isinstance(value, dict):
            raise GenLayerAuthorityError("GENLAYER_STATE_INVALID")
        return value

    def verify_decision(
        self,
        *,
        transaction_id: str,
        intent_id: str,
        decision: str,
        expected_action_subject: str,
        expected_action_intent: str,
        expected_action_hash: str,
        expected_target_hash: str,
        expected_payload_hash: str,
        expected_evidence_digest: str,
        expected_agent: str,
        expected_consumer: str,
        expected_value: int,
        expected_expires_at: int,
        expected_repair_deadline: int,
    ) -> GenLayerProof:
        tx_id = _require_digest(transaction_id, "GENLAYER_TX")
        expected_intent = "0x" + _digest_bytes(intent_id, "INTENT_ID").hex()
        expected_subject = "0x" + _digest_bytes(expected_action_subject, "ACTION_SUBJECT").hex()
        expected_action = "0x" + _digest_bytes(expected_action_intent, "ACTION_INTENT").hex()
        expected_action_hash_value = "0x" + _digest_bytes(expected_action_hash, "ACTION_HASH").hex()
        expected_target_hash_value = "0x" + _digest_bytes(expected_target_hash, "TARGET_HASH").hex()
        expected_payload_hash_value = "0x" + _digest_bytes(expected_payload_hash, "PAYLOAD_HASH").hex()
        expected_evidence_digest_value = "0x" + _digest_bytes(expected_evidence_digest, "EVIDENCE_DIGEST").hex()
        expected_agent_address = _require_address(expected_agent, "AGENT").lower()
        expected_consumer_address = _require_address(expected_consumer, "CONSUMER")
        if isinstance(expected_value, bool) or not isinstance(expected_value, int) or expected_value < 0:
            raise GenLayerAuthorityError("VALUE_FORMAT")
        if isinstance(expected_expires_at, bool) or not isinstance(expected_expires_at, int):
            raise GenLayerAuthorityError("EXPIRES_AT_FORMAT")
        if isinstance(expected_repair_deadline, bool) or not isinstance(expected_repair_deadline, int):
            raise GenLayerAuthorityError("REPAIR_DEADLINE_FORMAT")
        if decision not in {"AUTHORIZE", "DENY"}:
            raise GenLayerAuthorityError("DECISION_FORMAT")

        status = self._rpc("gen_getTransactionStatus", [{"txId": tx_id}])
        if not isinstance(status, dict) or status.get("statusCode") != 7 or str(status.get("status", "")).upper() != "FINALIZED":
            raise GenLayerAuthorityError("GENLAYER_NOT_FINALIZED")
        receipt = self._rpc("gen_getTransactionReceipt", [{"txId": tx_id}])
        if not isinstance(receipt, dict):
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_INVALID")
        if str(receipt.get("id", "")).lower() != tx_id:
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_ID_MISMATCH")
        status_name = receipt.get("statusName")
        if receipt.get("status") != 7 or (status_name is not None and str(status_name).upper() != "FINALIZED"):
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_NOT_FINALIZED")
        if receipt.get("txExecutionResult") != 1 or receipt.get("result") != 1:
            raise GenLayerAuthorityError("GENLAYER_EXECUTION_FAILED")
        if str(receipt.get("recipient", "")).lower() != self.gateway:
            raise GenLayerAuthorityError("GENLAYER_GATEWAY_MISMATCH")
        decode_transaction_call_data(str(receipt.get("txCallData", "")), expected_intent_id=expected_intent)
        trace = self._rpc("gen_dbg_traceTransaction", [{"txID": tx_id, "round": 0}])
        if not isinstance(trace, dict) or trace.get("result_code") != 0 or not isinstance(trace.get("return_data"), str):
            raise GenLayerAuthorityError("GENLAYER_TRACE_FAILED")
        try:
            return_data = bytes.fromhex(trace["return_data"].removeprefix("0x"))
        except ValueError as exc:
            raise GenLayerAuthorityError("GENLAYER_TRACE_INVALID") from exc
        if decision.encode("ascii") not in return_data:
            raise GenLayerAuthorityError("GENLAYER_DECISION_MISMATCH")

        onchain = self._read_intent(expected_intent)
        expected_state = 3 if decision == "AUTHORIZE" else 4
        expected_reason = "CONSENSUS_AUTHORIZED" if decision == "AUTHORIZE" else "CONSENSUS_DENIED"
        action_subject = _hex_digest(onchain.get("action_subject"), "ONCHAIN_ACTION_SUBJECT")
        action_intent = _hex_digest(onchain.get("action_intent"), "ONCHAIN_ACTION_INTENT")
        action_hash = _hex_digest(onchain.get("action_hash"), "ONCHAIN_ACTION_HASH")
        target_hash = _hex_digest(onchain.get("target_hash"), "ONCHAIN_TARGET_HASH")
        payload_hash = _hex_digest(onchain.get("payload_hash"), "ONCHAIN_PAYLOAD_HASH")
        evidence_digest = _hex_digest(onchain.get("evidence_digest"), "ONCHAIN_EVIDENCE_DIGEST")
        agent = onchain.get("agent")
        if not isinstance(agent, str) or not _ADDRESS_RE.fullmatch(agent):
            raise GenLayerAuthorityError("ONCHAIN_AGENT_FORMAT")
        agent = agent.lower()
        consumer = onchain.get("consumer")
        if not isinstance(consumer, str) or consumer.lower() != expected_consumer_address:
            raise GenLayerAuthorityError("GENLAYER_CONSUMER_MISMATCH")
        value = onchain.get("value")
        if isinstance(value, bool) or not isinstance(value, int):
            raise GenLayerAuthorityError("ONCHAIN_VALUE_FORMAT")
        expires_at = onchain.get("expires_at")
        repair_deadline = onchain.get("repair_deadline")
        if (
            onchain.get("state") != expected_state
            or onchain.get("reason") != expected_reason
            or action_subject != expected_subject
            or action_intent != expected_action
            or action_hash != expected_action_hash_value
            or target_hash != expected_target_hash_value
            or payload_hash != expected_payload_hash_value
            or evidence_digest != expected_evidence_digest_value
            or agent != expected_agent_address
            or value != expected_value
            or expires_at != expected_expires_at
            or repair_deadline != expected_repair_deadline
        ):
            raise GenLayerAuthorityError("GENLAYER_DECISION_MISMATCH")
        return GenLayerProof(
            transaction_id=tx_id,
            intent_id=expected_intent,
            decision=decision,
            gateway=self.gateway,
            status="FINALIZED",
            execution="FINISHED_WITH_RETURN",
            reason=expected_reason,
            action_subject=action_subject,
            action_intent=action_intent,
            action_hash=action_hash,
            target_hash=target_hash,
            payload_hash=payload_hash,
            evidence_digest=evidence_digest,
            agent=agent,
            consumer=consumer.lower(),
            value=value,
            expires_at=expires_at,
            repair_deadline=repair_deadline,
        )

    def _verify_finalized_firewall_write(
        self,
        *,
        transaction_id: str,
        intent_id: str,
        method: str,
        expected_args: list[bytes],
        bind_first_arg_to_intent: bool = True,
    ) -> tuple[str, dict[str, Any]]:
        tx_id = _require_digest(transaction_id, "GENLAYER_TX")
        expected_intent = _digest_bytes(intent_id, "INTENT_ID")
        status = self._rpc("gen_getTransactionStatus", [{"txId": tx_id}])
        if not isinstance(status, dict) or status.get("statusCode") != 7 or str(status.get("status", "")).upper() != "FINALIZED":
            raise GenLayerAuthorityError("GENLAYER_NOT_FINALIZED")
        receipt = self._rpc("gen_getTransactionReceipt", [{"txId": tx_id}])
        if not isinstance(receipt, dict):
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_INVALID")
        if str(receipt.get("id", "")).lower() != tx_id:
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_ID_MISMATCH")
        if receipt.get("status") != 7 or (receipt.get("statusName") is not None and str(receipt.get("statusName")).upper() != "FINALIZED"):
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_NOT_FINALIZED")
        if receipt.get("txExecutionResult") != 1 or receipt.get("result") != 1:
            raise GenLayerAuthorityError("GENLAYER_EXECUTION_FAILED")
        if str(receipt.get("recipient", "")).lower() != self.firewall:
            raise GenLayerAuthorityError("GENLAYER_FIREWALL_MISMATCH")
        decoded = decode_transaction_call_data(
            str(receipt.get("txCallData", "")),
            expected_intent_id="0x" + expected_intent.hex() if bind_first_arg_to_intent else None,
            expected_method=method,
        )
        args = decoded.get("args")
        if not isinstance(args, list) or len(args) != len(expected_args) or any(left != right for left, right in zip(args, expected_args)):
            raise GenLayerAuthorityError("GENLAYER_CALLDATA_MISMATCH")
        trace = self._rpc("gen_dbg_traceTransaction", [{"txID": tx_id, "round": 0}])
        if not isinstance(trace, dict) or trace.get("result_code") != 0:
            raise GenLayerAuthorityError("GENLAYER_TRACE_FAILED")
        return tx_id, self._read_intent("0x" + expected_intent.hex())

    def verify_evidence_replacement(
        self,
        *,
        transaction_id: str,
        intent_id: str,
        evidence_digest: str,
        expected_revision: int,
    ) -> GenLayerLifecycleProof:
        tx_id, onchain = self._verify_finalized_firewall_write(
            transaction_id=transaction_id,
            intent_id=intent_id,
            method="replace_evidence",
            expected_args=[_digest_bytes(intent_id, "INTENT_ID"), _digest_bytes(evidence_digest, "EVIDENCE_DIGEST")],
        )
        if onchain.get("state") != 1 or onchain.get("reason") != "EVIDENCE_REPLACED" or onchain.get("evidence_revision") != expected_revision + 1:
            raise GenLayerAuthorityError("GENLAYER_REPAIR_STATE_MISMATCH")
        return GenLayerLifecycleProof(
            transaction_id=tx_id,
            intent_id="0x" + _digest_bytes(intent_id, "INTENT_ID").hex(),
            method="replace_evidence",
            status="FINALIZED",
            execution="FINISHED_WITH_RETURN",
            evidence_digest="0x" + _digest_bytes(evidence_digest, "EVIDENCE_DIGEST").hex(),
        )

    def verify_receipt_consumption(
        self,
        *,
        transaction_id: str,
        intent_id: str,
        receipt_id: str,
        action_intent: str,
        expected_consumer: str,
    ) -> GenLayerLifecycleProof:
        tx_id, onchain = self._verify_finalized_firewall_write(
            transaction_id=transaction_id,
            intent_id=intent_id,
            method="consume_receipt",
            expected_args=[_digest_bytes(receipt_id, "RECEIPT_ID"), _digest_bytes(action_intent, "ACTION_INTENT")],
            bind_first_arg_to_intent=False,
        )
        consumer = onchain.get("consumer")
        if not isinstance(consumer, str) or consumer.lower() != _require_address(expected_consumer, "CONSUMER"):
            raise GenLayerAuthorityError("GENLAYER_CONSUMER_MISMATCH")
        if onchain.get("state") != 6 or onchain.get("reason") != "CONSUMED" or onchain.get("receipt_id") != _digest_bytes(receipt_id, "RECEIPT_ID") or onchain.get("action_intent") != _digest_bytes(action_intent, "ACTION_INTENT"):
            raise GenLayerAuthorityError("GENLAYER_RECEIPT_STATE_MISMATCH")
        return GenLayerLifecycleProof(
            transaction_id=tx_id,
            intent_id="0x" + _digest_bytes(intent_id, "INTENT_ID").hex(),
            method="consume_receipt",
            status="FINALIZED",
            execution="FINISHED_WITH_RETURN",
            receipt_id="0x" + _digest_bytes(receipt_id, "RECEIPT_ID").hex(),
            action_intent="0x" + _digest_bytes(action_intent, "ACTION_INTENT").hex(),
        )
