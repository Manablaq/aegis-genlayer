from __future__ import annotations

import json
import hmac
import os
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .engine import AegisEngine, DecisionError, ValidationError, _attestation_fingerprint
from .genlayer_authority import GenLayerAuthority, GenLayerAuthorityError
from .models import Attestation, Policy
from .wallet_auth import WalletAuthError, create_challenge, normalize_address, session_address, verify_challenge


class AegisHandler(BaseHTTPRequestHandler):
    engine: AegisEngine
    api_token: str
    allowed_origins: frozenset[str]
    wallet_session_secret: str = ""
    genlayer_authority: GenLayerAuthority | None = None

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle browser preflight without weakening endpoint authentication."""
        path = self.path.split("?", 1)[0]
        known_path = path in {"/health", "/auth/challenge", "/auth/verify", "/auth/logout", "/v1/policies", "/v1/intents", "/v1/receipts/consume"} or path.startswith("/v1/intents/")
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
        path = self.path.split("?", 1)[0]
        if path == "/auth/challenge":
            self._wallet_challenge()
            return
        if path == "/auth/verify":
            self._wallet_verify()
            return
        if path == "/auth/logout":
            self._clear_wallet_session()
            return
        if not self._authorized():
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "UNAUTHORIZED"})
            return
        wallet = self._wallet_identity()
        try:
            body = self._json()
            if self.path == "/v1/policies":
                self._require_policy_owner(body, wallet)
                self.engine.register_policy(_policy(body))
                self._send(HTTPStatus.CREATED, {"status": "REGISTERED"})
                return
            if self.path == "/v1/intents":
                self._require_agent(body.get("agent"), wallet)
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
                self._require_agent(intent.agent, wallet)
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
                self._require_agent(body.get("caller"), wallet)
                authority = getattr(self, "genlayer_authority", None)
                intent_before = self.engine.intents.get(intent_id)
                if authority is None or intent_before is None or intent_before.onchain_target_hash is None:
                    self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "GENLAYER_BINDING_REQUIRED"})
                    return
                attestations = [Attestation(**item) for item in body["attestations"]]
                proof = authority.verify_evidence_replacement(
                    transaction_id=body["genlayer_tx_id"],
                    intent_id=intent_id,
                    evidence_digest=_attestation_fingerprint(attestations),
                    expected_revision=intent_before.evidence_revision,
                )
                intent = self.engine.replace_evidence(
                    intent_id=intent_id, caller=body["caller"],
                    attestations=attestations,
                )
                response = intent.to_dict()
                response["genlayer_proof"] = proof.__dict__
                self._send(HTTPStatus.OK, response)
                return
            if self.path == "/v1/receipts/consume":
                self._require_agent(body.get("consumer"), wallet)
                authority = getattr(self, "genlayer_authority", None)
                receipt_before = self.engine.receipts.get(body.get("receipt_id"))
                if authority is None or receipt_before is None:
                    self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "GENLAYER_BINDING_REQUIRED"})
                    return
                proof = authority.verify_receipt_consumption(
                    transaction_id=body["genlayer_tx_id"],
                    intent_id=receipt_before.intent_id,
                    receipt_id=body["receipt_id"],
                    action_intent=body["action_intent"],
                    expected_consumer=body["consumer"],
                )
                receipt = self.engine.consume_receipt(
                    receipt_id=body["receipt_id"], consumer=body["consumer"],
                    action_intent_value=body["action_intent"],
                )
                response = receipt.to_dict()
                response["genlayer_proof"] = proof.__dict__
                self._send(HTTPStatus.OK, response)
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
        except GenLayerAuthorityError as exc:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except WalletAuthError as exc:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})
        except (KeyError, TypeError, ValueError, ValidationError, DecisionError) as exc:
            self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _authorized(self) -> bool:
        expected = self.api_token
        if not expected:
            supplied = self.headers.get("Authorization", "")
            if supplied:
                return False
        else:
            supplied = self.headers.get("Authorization", "")
            if hmac.compare_digest(supplied, f"Bearer {expected}"):
                return True
        return self._wallet_identity() is not None

    def _wallet_identity(self) -> str | None:
        return session_address(self._cookie("aegis_session"), self.wallet_session_secret)

    def _require_policy_owner(self, body: dict[str, Any], wallet: str | None) -> None:
        if wallet is None:
            return
        agents = body.get("approved_agents", [])
        if not isinstance(agents, list) or wallet not in {normalize_address(agent) for agent in agents if isinstance(agent, str) and agent.startswith("0x")}:
            raise WalletAuthError("WALLET_NOT_APPROVED_AGENT")

    def _require_agent(self, value: Any, wallet: str | None) -> None:
        if wallet is None:
            return
        if not isinstance(value, str) or not value.lower() == wallet:
            raise WalletAuthError("WALLET_AGENT_MISMATCH")

    def _wallet_challenge(self) -> None:
        try:
            self._require_origin()
            body = self._json()
            address = normalize_address(body["address"])
            chain_id = body["chain_id"]
            if not isinstance(chain_id, str) or not chain_id:
                raise WalletAuthError("WALLET_CHAIN_REQUIRED")
            challenge = create_challenge(
                address=address,
                chain_id=chain_id,
                origin=self._request_origin(),
                secret=self.wallet_session_secret,
            )
            self._set_cookie("aegis_challenge", challenge["challenge"], max_age=300)
            self._send(HTTPStatus.OK, {key: challenge[key] for key in ("message", "address", "chain_id", "expires_at")})
        except (KeyError, TypeError, WalletAuthError) as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE if str(exc) == "WALLET_AUTH_NOT_CONFIGURED" else HTTPStatus.UNPROCESSABLE_ENTITY
            self._send(status, {"error": str(exc)})

    def _wallet_verify(self) -> None:
        try:
            self._require_origin()
            body = self._json()
            address = normalize_address(body["address"])
            message = body["message"]
            signature = body["signature"]
            if not isinstance(message, str) or not isinstance(signature, str):
                raise WalletAuthError("WALLET_SIGNATURE_INVALID")
            session = verify_challenge(
                challenge_cookie=self._cookie("aegis_challenge") or "",
                address=address,
                message=message,
                signature=signature,
                secret=self.wallet_session_secret,
            )
            self._set_cookie("aegis_session", session, max_age=3600)
            self._set_cookie("aegis_challenge", "", max_age=0)
            self._send(HTTPStatus.OK, {"authenticated": True, "address": address})
        except (KeyError, TypeError, WalletAuthError) as exc:
            status = HTTPStatus.SERVICE_UNAVAILABLE if str(exc) == "WALLET_AUTH_NOT_CONFIGURED" else HTTPStatus.UNPROCESSABLE_ENTITY
            self._send(status, {"error": str(exc)})

    def _clear_wallet_session(self) -> None:
        self._set_cookie("aegis_session", "", max_age=0)
        self._set_cookie("aegis_challenge", "", max_age=0)
        self._send(HTTPStatus.OK, {"authenticated": False})

    def _require_origin(self) -> None:
        origin = self.headers.get("Origin", "")
        if self.allowed_origins and origin and origin not in self.allowed_origins:
            raise WalletAuthError("ORIGIN_NOT_ALLOWED")

    def _request_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        if origin:
            return origin.rstrip("/")
        return f"https://{self.headers.get('Host', 'aegis.local')}"

    def _cookie(self, name: str) -> str | None:
        header = self.headers.get("Cookie", "")
        if not header:
            return None
        cookies = SimpleCookie()
        cookies.load(header)
        morsel = cookies.get(name)
        return morsel.value if morsel is not None else None

    def _set_cookie(self, name: str, value: str, *, max_age: int) -> None:
        if not hasattr(self, "_response_cookies"):
            self._response_cookies: list[str] = []
        secure = self.headers.get("Origin", "").startswith("https://") or self.headers.get("X-Forwarded-Proto", "") == "https"
        attributes = [f"{name}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
        if secure:
            attributes.append("Secure")
        self._response_cookies.append("; ".join(attributes))

    def _send(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        for cookie in getattr(self, "_response_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")

    def _json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_048_576:
            raise ValueError("INVALID_BODY_LENGTH")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("JSON_OBJECT_REQUIRED")
        return value

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
        {
            "engine": engine,
            "api_token": token,
            "allowed_origins": frozenset(allowed_origins),
            "wallet_session_secret": os.environ.get("AEGIS_SESSION_SECRET", ""),
        },
    )
    return ThreadingHTTPServer((host, port), handler)
