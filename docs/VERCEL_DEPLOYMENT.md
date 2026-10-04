# Vercel deployment

The production project is `aegis-genlayer` and uses the repository root as its
Vercel project root.

## Runtime layout

- `frontend/` is built with Vite into `frontend/dist`.
- `api/index.py` is the Python function entrypoint.
- `vercel.json` rewrites `/api/:path*` to the function while preserving the
  backend route path.
- `DATABASE_URL` is injected by the connected free Neon resource.
- `AEGIS_API_TOKEN` is a Vercel Secret and is never exposed to the frontend.
- `AEGIS_ALLOWED_ORIGINS` is an exact production-origin allowlist.

The function reconstructs the strict engine from a Neon JSONB snapshot for
each request, locks the state row, and writes the new snapshot before sending a
successful mutation response. This preserves receipt single-use and restart
recovery across independent serverless invocations.

## Required production configuration

The API is intentionally fail-closed. Configure `AEGIS_PROVIDER_KEYS` as a
JSON object containing the real provider IDs and Ed25519 public keys before
expecting an evidence-backed `AUTHORIZED` result. Do not put private provider
keys, bearer tokens, or database URLs in Git or `VITE_*` variables.

```sh
vercel env add AEGIS_PROVIDER_KEYS production --sensitive
vercel env add AEGIS_API_TOKEN production --sensitive
vercel env add AEGIS_ALLOWED_ORIGINS production --value https://aegis-genlayer.vercel.app
```

An empty provider-key set is safe but causes valid-looking evidence to fail
closed into `REPAIR_REQUIRED`; it is not an authorization bypass.

## Verification

```sh
curl -sS https://aegis-genlayer.vercel.app/api/health
curl -sS -H 'Authorization: Bearer <token>' \
  https://aegis-genlayer.vercel.app/api/v1/intents/<intent-id>
```
