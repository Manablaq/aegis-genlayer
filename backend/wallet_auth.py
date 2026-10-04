from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Any


ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
CHALLENGE_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 3600


class WalletAuthError(ValueError):
    pass


def normalize_address(value: str) -> str:
    if not isinstance(value, str) or not ADDRESS_RE.fullmatch(value.strip()):
        raise WalletAuthError("WALLET_ADDRESS_INVALID")
    return value.strip().lower()


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _encode(value: dict[str, Any], secret: str) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode(value: str, secret: str) -> dict[str, Any]:
    try:
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise WalletAuthError("WALLET_COOKIE_INVALID")
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise WalletAuthError("WALLET_COOKIE_INVALID") from exc
    if not isinstance(decoded, dict):
        raise WalletAuthError("WALLET_COOKIE_INVALID")
    return decoded


def create_challenge(*, address: str, chain_id: str, origin: str, secret: str, now: int | None = None) -> dict[str, Any]:
    normalized = normalize_address(address)
    if not secret:
        raise WalletAuthError("WALLET_AUTH_NOT_CONFIGURED")
    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + CHALLENGE_TTL_SECONDS
    nonce = secrets.token_urlsafe(24)
    domain = origin.removeprefix("https://").removeprefix("http://").rstrip("/")
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{normalized}\n\n"
        "Sign in to Aegis to operate your protected action workspace.\n\n"
        f"URI: {origin}\n"
        "Version: 1\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {_timestamp(issued_at)}\n"
        f"Expiration Time: {_timestamp(expires_at)}"
    )
    record = {
        "address": normalized,
        "chain_id": chain_id,
        "origin": origin,
        "message": message,
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    return {"challenge": _encode(record, secret), **record}


def verify_challenge(*, challenge_cookie: str, address: str, message: str, signature: str, secret: str, now: int | None = None) -> str:
    if not secret:
        raise WalletAuthError("WALLET_AUTH_NOT_CONFIGURED")
    record = _decode(challenge_cookie, secret)
    current = int(time.time()) if now is None else now
    if not isinstance(record.get("expires_at"), int) or current >= record["expires_at"]:
        raise WalletAuthError("WALLET_CHALLENGE_EXPIRED")
    normalized = normalize_address(address)
    if record.get("address") != normalized or record.get("message") != message:
        raise WalletAuthError("WALLET_CHALLENGE_MISMATCH")
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct

        recovered = Account.recover_message(encode_defunct(text=message), signature=signature)
    except ImportError as exc:
        raise WalletAuthError("WALLET_AUTH_NOT_CONFIGURED") from exc
    except Exception as exc:
        raise WalletAuthError("WALLET_SIGNATURE_INVALID") from exc
    if normalize_address(recovered) != normalized:
        raise WalletAuthError("WALLET_SIGNATURE_INVALID")
    return _encode({"address": normalized, "issued_at": current, "expires_at": current + SESSION_TTL_SECONDS}, secret)


def session_address(cookie: str | None, secret: str, now: int | None = None) -> str | None:
    if not cookie or not secret:
        return None
    try:
        record = _decode(cookie, secret)
        current = int(time.time()) if now is None else now
        if not isinstance(record.get("expires_at"), int) or current >= record["expires_at"]:
            return None
        return normalize_address(record["address"])
    except WalletAuthError:
        return None

