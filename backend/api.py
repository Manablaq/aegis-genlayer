from __future__ import annotations

import json
import hmac
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .engine import AegisEngine, DecisionError, ValidationError
from .genlayer_authority import GenLayerAuthority, GenLayerAuthorityError
from .models import Attestation, Policy


class AegisHandler(BaseHTTPRequestHandler):
    engine: AegisEngine
    api_token: str
    allowed_origins: frozenset[str]
    genlayer_authority: GenLayerAuthority | None = None

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle browser preflight without weakening endpoint authentication."""
        path = self.path.split("?", 1)[0]
        known_path = path == "/health" or path == "/v1/policies" or path == "/v1/intents" or path.startswith("/v1/intents/") or path == "/v1/receipts/consume"
        if not known_path:
            self._send(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"ok": True, "service": "aegis-backend"})
            return
        if self.path.startswith("/v1/intents/") and not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "UNAUTHORIZED"})
            return
        if self.path.startswith("/v1/intents/"):
            intent_id = self.path.removeprefix("/v1/intents/")
            try:
                self._send(HTTPStatus.OK, self.engine.intents[intent_id].to_dict())
            except KeyError:
                self._send(HTTPStatus.NOT_FOUND, {"error": "INTENT_UNKNOWN"})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "UNAUTHORIZED"})
            return
        try:
            body = self._json()
            if self.path == "/v1/policies":
                self.engine.register_policy(_policy(body))
                self._send(HTTPStatus.CREATED, {"status": "REGISTERED"})
                return
            if self.path == "/v1/intents":
                intent = self.engine.create_intent(
                    intent_id=body["intent_id"], policy_id=body["policy_id"], policy_version=int(body["policy_version"]),
                    agent=body["agent"], action_type=body["action_type"], target=body["target"],
                    recipient=body["recipient"], value=int(body["value"]), payload_hash=body["payload_hash"],
                    attestations=[Attestation(**item) for item in body["attestations"]],
                    onchain_target_hash=_genlayer_target_hash(body),
                    expires_at=_genlayer_expires_at(body),
                )
                self._send(HTTPStatus.CREATED, intent.to_dict())
                return
            if self.path.startswith("/v1/intents/") and self.path.endswith("/evaluate"):
                self._send(HTTPStatus.GONE, {"error": "GENLAYER_FINALITY_REQUIRED"})
                return
            if self.path.startswith("/v1/intents/") and self.path.endswith("/evaluate-genlayer"):
                intent_id = self.path.removeprefix("/v1/intents/").removesuffix("/evaluate-genlayer")
                authority = getattr(self, "genlayer_authority", None)
                if authority is None:
                    self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "GENLAYER_NOT_CONFIGURED"})
                    return
                intent = self.engine.intents.get(intent_id)
                if intent is None:
                    self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "INTENT_UNKNOWN"})
                    return
                if intent.onchain_target_hash is None or intent.onchain_evidence_digest is None:
                    self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "GENLAYER_BINDING_REQUIRED"})
                    return
                policy = self.engine.policies.get(f"{intent.policy_id}:{intent.policy_version}")
                if policy is None or policy.onchain_action_hash is None:
                    self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "GENLAYER_BINDING_REQUIRED"})
                    return
                proof = authority.verify_decision(
                    transaction_id=body["genlayer_tx_id"],
                    intent_id=intent_id,
                    decision=body["decision"],
                    expected_action_subject=intent.action_subject,
                    expected_action_intent=intent.action_intent,
                    expected_action_hash=policy.onchain_action_hash,
                    expected_target_hash=intent.onchain_target_hash,
                    expected_payload_hash=intent.payload_hash,
                    expected_evidence_digest=intent.onchain_evidence_digest,
                    expected_agent=intent.agent,
                    expected_consumer=intent.recipient,
                    expected_value=intent.value,
                    expected_expires_at=intent.expires_at,
                    expected_repair_deadline=intent.repair_deadline,
                )
                updated = self.engine.evaluate_genlayer(intent_id=intent_id, consensus_decision=proof.decision)
                response = updated.to_dict()
                response["genlayer_proof"] = proof.__dict__
                self._send(HTTPStatus.OK, response)
                return
            if self.path.startswith("/v1/intents/") and self.path.endswith("/replace-evidence"):
                intent_id = self.path.removeprefix("/v1/intents/").removesuffix("/replace-evidence")
                intent = self.engine.replace_evidence(
                    intent_id=intent_id, caller=body["caller"],
                    attestations=[Attestation(**item) for item in body["attestations"]],
                )
                self._send(HTTPStatus.OK, intent.to_dict())
                return
            if self.path == "/v1/receipts/consume":
                receipt = self.engine.consume_receipt(
                    receipt_id=body["receipt_id"], consumer=body["consumer"],
                    action_intent_value=body["action_intent"],
                )
                self._send(HTTPStatus.OK, receipt.to_dict())
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
        except GenLayerAuthorityError as exc:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except (KeyError, TypeError, ValueError, ValidationError, DecisionError) as exc:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        expected = self.api_token
        if not expected:
            return False
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, f"Bearer {expected}")

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_048_576:
            raise ValueError("INVALID_BODY_LENGTH")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("JSON_OBJECT_REQUIRED")
        return value

    def _send(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")


def _policy(body: dict[str, Any]) -> Policy:
    return Policy(
        policy_id=body["policy_id"], version=int(body["version"]),
        approved_agents=frozenset(body["approved_agents"]),
        allowed_action_types=frozenset(body["allowed_action_types"]),
        allowed_recipients=frozenset(body.get("allowed_recipients", [])),
        approved_sources=dict(body["approved_sources"]), max_value=int(body["max_value"]),
        required_sources=frozenset(body["required_sources"]),
        minimum_attestations=int(body["minimum_attestations"]),
        maximum_age_seconds=int(body["maximum_age_seconds"]),
        intent_ttl_seconds=int(body["intent_ttl_seconds"]),
        repair_window_seconds=int(body["repair_window_seconds"]), active=bool(body.get("active", True)),
        onchain_action_hash=body.get("onchain_action_hash"),
    )


def _genlayer_target_hash(body: dict[str, Any]) -> str | None:
    binding = body.get("genlayer_binding")
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("GENLAYER_BINDING_OBJECT_REQUIRED")
    return binding["target_hash"]


def _genlayer_expires_at(body: dict[str, Any]) -> int | None:
    binding = body.get("genlayer_binding")
    if binding is None:
        return None
    if not isinstance(binding, dict):
        raise ValueError("GENLAYER_BINDING_OBJECT_REQUIRED")
    value = binding.get("expires_at")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("EXPIRES_AT_FORMAT")
    return value


def make_server(
    engine: AegisEngine,
    *,
    host: str = "127.0.0.1",
    port: int = 8081,
    api_token: str | None = None,
    allowed_origins: set[str] | frozenset[str] | None = None,
) -> ThreadingHTTPServer:
    token = api_token if api_token is not None else os.environ.get("AEGIS_API_TOKEN", "")
    if not token:
        raise RuntimeError("AEGIS_API_TOKEN is required")
    if allowed_origins is None:
        configured_origins = os.environ.get("AEGIS_ALLOWED_ORIGINS", "")
        allowed_origins = frozenset(
            origin.strip().rstrip("/")
            for origin in configured_origins.split(",")
            if origin.strip()
        ) or frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})
    handler = type(
        "ConfiguredAegisHandler",
        (AegisHandler,),
        {"engine": engine, "api_token": token, "allowed_origins": frozenset(allowed_origins)},
    )
    return ThreadingHTTPServer((host, port), handler)
