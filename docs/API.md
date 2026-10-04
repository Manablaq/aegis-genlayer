# Aegis HTTP API

The backend exposes a small JSON API on `127.0.0.1:8081` by default. In the
production Vercel deployment the same API is available under `/api`. Set
`AEGIS_API_TOKEN` before starting the local server or as a Vercel Secret for
the deployed function. Every endpoint except `/health` requires:

```http
Authorization: Bearer <AEGIS_API_TOKEN>
Content-Type: application/json
```

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
`repair_window_seconds`.

### `POST /v1/intents`

Creates an intent after validating the policy, action subject, and value/TTL
limits. Evidence signatures, freshness, source allowlists, and recipient
allowlists are evaluated by the subsequent consensus decision. The request
includes the intent identity, policy version, action data, payload hash, and an
`attestations` array.

### `GET /v1/intents/{intent_id}`

Returns the persisted intent, including its immutable action subject,
action-intent digest, state, evidence revision, repair deadline, and receipt
binding when present.

### `POST /v1/intents/{intent_id}/evaluate`

Records a consensus decision. `consensus_decision` must be `AUTHORIZE` or
`DENY`; invalid or conflicting decisions fail closed.

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
