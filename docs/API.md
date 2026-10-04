# Aegis HTTP API

The backend exposes a small JSON API on `127.0.0.1:8081` by default. In the
production Vercel deployment the same API is available under `/api`. Set
`AEGIS_API_TOKEN` before starting the local server or as a Vercel Secret for
the deployed function. Every state-changing endpoint requires either the
server-managed wallet session described below or the operator bearer token;
`/health` remains public:

```http
Authorization: Bearer <AEGIS_API_TOKEN>
Content-Type: application/json
```

### Wallet session

The hosted app uses a wallet-authenticated session so visitors never paste an
API token. `POST /auth/challenge` accepts an EIP-1193 wallet address and chain
ID, returns a short-lived EIP-4361-style message, and sets an HttpOnly,
SameSite cookie containing a server-signed one-time challenge. The wallet signs
that exact message with `personal_sign`; `POST /auth/verify` recovers the
address, consumes the challenge cookie, and sets a one-hour HttpOnly session
cookie. The backend verifies the session on every protected request. Account
changes and logout invalidate the browser session.

Wallet-authenticated requests are identity-bound: policy registration must
approve the connected address, intent creation and evidence repair must use it
as the agent/caller, GenLayer evaluation must belong to that agent, and receipt
consumption must use it as the consumer. A wallet address is never accepted as
a bearer token. Set `AEGIS_SESSION_SECRET` to a high-entropy server-only value
to enable wallet sessions; if it is absent, the auth route fails closed.

Browser clients must be explicitly allowlisted. Set `AEGIS_ALLOWED_ORIGINS` to
a comma-separated list of exact origins, for example
`http://127.0.0.1:5173,https://aegis-genlayer.vercel.app`. The server never uses
`Access-Control-Allow-Origin: *`, and the bearer token is not accepted through
cookies or query parameters. Local development defaults to the two Vite
origins when `AEGIS_ALLOWED_ORIGINS` is unset.

The deployed function uses `DATABASE_URL` from the connected Neon resource.
Each invocation loads the strict engine snapshot inside a Postgres transaction,
locks the state row, and commits the updated snapshot before returning a
successful mutation response. Ephemeral function files are never used for
security-critical state.

## Endpoints

### `GET /health`

Unauthenticated liveness check.

```json
{"ok": true, "service": "aegis-backend"}
```

### `POST /v1/policies`

Registers an immutable policy version. The request contains the policy model:
`policy_id`, `version`, `approved_agents`, `allowed_action_types`,
`allowed_recipients`, `approved_sources`, `max_value`, `required_sources`,
`minimum_attestations`, `maximum_age_seconds`, `intent_ttl_seconds`, and
`repair_window_seconds`. A policy intended for the GenLayer path must also set
`onchain_action_hash` to the exact 32-byte action hash registered in the
firewall policy.

### `POST /v1/intents`

Creates an intent after validating the policy, action subject, and value/TTL
limits. Evidence signatures, freshness, source allowlists, and recipient
allowlists are evaluated by the subsequent consensus decision. The request
includes the intent identity, policy version, action data, payload hash, and an
`attestations` array.

To make the intent eligible for finalized GenLayer verification, include:

```json
{
  "genlayer_binding": {
    "target_hash": "<64 hex characters>",
    "expires_at": 1791098000
  }
}
```

The agent and recipient must then be the exact on-chain addresses, the policy
must carry the registered action hash, and the backend derives the firewall's
action subject, action-intent digest, and evidence digest byte-for-byte. An
intent created without this binding cannot be evaluated through the GenLayer
route. `expires_at` is optional for new intents (the policy TTL is used when it
is omitted), but when supplied it must be a future timestamp within the policy
window and must equal the value passed to `submit_intent`.

### `GET /v1/intents/{intent_id}`

Returns the persisted intent, including its immutable action subject,
action-intent digest, state, evidence revision, repair deadline, and receipt
binding when present.

### `POST /v1/intents/{intent_id}/evaluate-genlayer`

This is the only decision-application route. The request is:

```json
{
  "genlayer_tx_id": "0x<64 hex characters>",
  "decision": "AUTHORIZE"
}
```

The backend independently queries the configured Bradbury RPC with redirects
disabled. It requires protocol finality (`statusCode` 7), a finalized
successful execution, the configured decision-gateway recipient, the exact
intent ID and gateway method markers in the transaction calldata, a successful
trace returning the requested decision, and a finalized firewall read-back.
The read-back must also match the local intent's action subject, action-intent
digest, consumer address, expiry, and repair deadline. Only after all checks
pass does the backend apply the state transition and create a receipt for an
authorization.

`decision` is an expected value, not an authority input: a mismatch with the
finalized trace or firewall state is rejected. A direct caller-supplied
`/evaluate` decision is retired and returns `410 GENLAYER_FINALITY_REQUIRED`.

### `POST /v1/intents/{intent_id}/replace-evidence`

Replaces evidence only during `REPAIR_REQUIRED`, only for the authorized
agent, and only with a valid replacement. The revision increments while the
action subject, action-intent digest, and repair deadline remain unchanged.

### `POST /v1/receipts/consume`

Consumes a receipt once for its exact consumer and action-intent digest.
Replays, wrong consumers, wrong action intents, expired receipts, and unknown
receipts are rejected.

## Error behavior

Malformed or invalid requests return `422` with a stable error token. Missing
or incorrect bearer authentication returns `401`; unknown routes return `404`.
Responses are JSON, marked `Cache-Control: no-store`, and never expose a
successful authorization for unverifiable evidence.
