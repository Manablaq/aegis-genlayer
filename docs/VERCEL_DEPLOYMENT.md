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
- `AEGIS_GENLAYER_RPC_URL` defaults to `https://rpc-bradbury.genlayer.com`.
- `AEGIS_GENLAYER_RPC_ORIGIN` defaults to the Bradbury explorer origin used by
  the public RPC gateway.
- `AEGIS_GENLAYER_GATEWAY` and `AEGIS_GENLAYER_FIREWALL` default to the
  source-matched repair-capable Bradbury addresses in
  `backend/genlayer_authority.py`.

The function reconstructs the strict engine from a Neon JSONB snapshot for
each request, locks the state row, and writes the new snapshot before sending a
successful mutation response. This preserves receipt single-use and restart
recovery across independent serverless invocations.

## Required production configuration

The API is intentionally fail-closed. Configure `AEGIS_PROVIDER_KEYS` as a
JSON object containing the real provider IDs and Ed25519 public keys before
expecting an evidence-backed intent to pass the local evidence gate. This is
separate from GenLayer authority: the canonical decision route verifies the
finalized Bradbury transaction and firewall state itself, and does not accept
a provider public key as a substitute for chain finality. Do not put private
provider keys, bearer tokens, or database URLs in Git or `VITE_*` variables.

```sh
vercel env add AEGIS_PROVIDER_KEYS production --sensitive
vercel env add AEGIS_API_TOKEN production --sensitive
vercel env add AEGIS_ALLOWED_ORIGINS production --value https://aegis-genlayer.vercel.app
```

An empty provider-key set is safe but causes valid-looking evidence to fail
closed into `REPAIR_REQUIRED`; it is not an authorization bypass.

The local intent must be created from the same on-chain binding that the
finalized transaction changed. In particular, GenLayer verification requires
the local action subject, action-intent digest, consumer address, expiry, and
repair deadline to equal the finalized firewall read-back. A transaction for a
different intent or a locally fabricated action record is rejected.

## Verification

```sh
curl -sS https://aegis-genlayer.vercel.app/api/health
curl -sS -H 'Authorization: Bearer <token>' \
  https://aegis-genlayer.vercel.app/api/v1/intents/<intent-id>

curl -sS -X POST \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  https://aegis-genlayer.vercel.app/api/v1/intents/<intent-id>/evaluate-genlayer \
  --data '{"genlayer_tx_id":"0x<finalized-tx>","decision":"AUTHORIZE"}'
```
