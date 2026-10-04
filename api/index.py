from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from backend.api import AegisHandler
from backend.engine import AegisEngine, Ed25519Verifier
from backend.genlayer_authority import GenLayerAuthority
from backend.postgres_store import PostgresStateStore


def _origins() -> frozenset[str]:
    configured = os.environ.get("AEGIS_ALLOWED_ORIGINS", "")
    return frozenset(origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip())


def _provider_keys() -> dict[str, str]:
    value = json.loads(os.environ.get("AEGIS_PROVIDER_KEYS", "{}"))
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise RuntimeError("AEGIS_PROVIDER_KEYS must be a JSON object of provider IDs to public keys")
    return value


class handler(AegisHandler):  # noqa: N801
    """Vercel Python entrypoint for the same authenticated Aegis API."""

    api_token = os.environ.get("AEGIS_API_TOKEN", "")
    allowed_origins = _origins()
    wallet_session_secret = os.environ.get("AEGIS_SESSION_SECRET", "")
    genlayer_authority = GenLayerAuthority.from_env()
    _store: PostgresStateStore | None = None

    @classmethod
    def _state_store(cls) -> PostgresStateStore:
        if cls._store is None:
            cls._store = PostgresStateStore(os.environ.get("DATABASE_URL", ""))
        return cls._store

    def _route_path(self) -> None:
        """Recover the API path passed through the /api/:path* rewrite."""
        parsed = urlsplit(self.path)
        routed = parse_qs(parsed.query).get("path", [""])[0]
        if routed:
            self.path = routed

    def _send(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        # Buffer responses so the state transaction commits before any success
        # bytes are sent to the caller.
        self._pending_response = (status, value)

    def _dispatch(self, method: Callable[[], None]) -> None:
        self._route_path()
        self._pending_response: tuple[HTTPStatus, dict[str, Any]] | None = None
        try:
            with self._state_store().transaction() as transaction:
                engine = AegisEngine(verifier=Ed25519Verifier(_provider_keys()))
                engine._restore(transaction.snapshot)
                self.engine = engine
                method()
                transaction.replace(engine.snapshot())
                pending = self._pending_response
            if pending is None:
                AegisHandler._send(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "NO_RESPONSE"})
            else:
                AegisHandler._send(self, *pending)
        except Exception:
            # Do not expose database, key, or stack details to callers.
            AegisHandler._send(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "STATE_UNAVAILABLE"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._route_path()
        path = self.path.split("?", 1)[0]
        known_path = path in {"/health", "/auth/challenge", "/auth/verify", "/auth/logout", "/v1/policies", "/v1/intents", "/v1/receipts/consume"} or path.startswith("/v1/intents/")
        if not known_path:
            AegisHandler._send(self, HTTPStatus.NOT_FOUND, {"error": "NOT_FOUND"})
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch(lambda: AegisHandler.do_GET(self))

    def do_POST(self) -> None:  # noqa: N802
        self._route_path()
        if self.path.split("?", 1)[0] in {"/auth/challenge", "/auth/verify", "/auth/logout"}:
            self._pending_response = None
            AegisHandler.do_POST(self)
            pending = self._pending_response
            if pending is None:
                AegisHandler._send(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "NO_RESPONSE"})
            else:
                AegisHandler._send(self, *pending)
            return
        self._dispatch(lambda: AegisHandler.do_POST(self))
