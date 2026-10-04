# Aegis

Aegis is a fail-closed action firewall for autonomous AI agents. It converts
a policy-approved intent into a single-use execution receipt only when the
policy, signed evidence, and GenLayer consensus decision all agree.

The project includes a fail-closed backend, a finalized-GenLayer verification
adapter, a responsive frontend control plane, and a production Vercel API
backed by transactional Neon Postgres state. The canonical decision path never
accepts a caller-supplied consensus token: the local intent must match the
finalized Bradbury firewall record before a receipt is created.

## Project status

| Area | Status |
| --- | --- |
| Contract-independent backend | Complete |
| API, persistence, and restart recovery | Complete |
| Adversarial and concurrency tests | Complete |
| Bradbury deployment and finalized live proof | Complete |
| Bradbury authority adapter and finality checks | Complete |
| Current-source positive API-to-Bradbury parity proof | Complete; finalized authorization and single-use receipt replay verified |
| Frontend control plane | Complete |
| Production API deployment and durable state | Complete |

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — components, lifecycle, and trust boundaries.
- [HTTP API](docs/API.md) — endpoints, authentication, and error behavior.
- [Security boundary](docs/BACKEND_SECURITY_BOUNDARY.md) — fail-closed guarantees and threat assumptions.
- [Verification report](docs/BACKEND_VERIFICATION_2026-10-02.md) — local and live verification scope.
- [Bradbury evidence](docs/BRADBURY_DEPLOYMENT_2026-10-02.md) — deployed addresses and finalized transaction evidence.
- [Submission readiness](docs/SUBMISSION_READINESS.md) — release checklist, verification commands, and deployment gates.
- [Frontend guide](frontend/README.md) — local development, interaction map, and browser QA scope.

## Security invariants

- There is no privileged bypass path in the state machine.
- Invalid, stale, conflicting, missing, or unverifiable evidence never
  authorizes an action.
- Every receipt is bound to the exact intent, action subject, consumer, and
  expiry, and can be consumed only once.
- Evidence repair increments a revision without changing the action subject,
  action-intent digest, or repair deadline.
- Restart recovery uses persisted state and never resends a transaction
  automatically.
- Redirect provenance is not trusted as authorization. Provider attestations
  bind the canonical resource, timestamps, and payload digest.

## Quick start

Create an isolated environment, install the production dependencies, and run
the backend tests:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Start the HTTP service with an explicit API token:

```sh
AEGIS_API_TOKEN='replace-with-a-secret' .venv/bin/python -m backend.server
```

The service listens on `127.0.0.1:8081` by default. Verify liveness with:

```sh
curl -sS http://127.0.0.1:8081/health
```

The production server requires `cryptography` and fails closed if the
dependency is unavailable. Keep provider keys and API tokens outside the
repository; the default state file is ignored by Git. GenLayer verification
also requires the local intent to use the same on-chain action subject,
action-intent digest, consumer address, expiry, and repair deadline as the
finalized firewall record.

Run the frontend in a second terminal:

```sh
cd frontend
npm install
npm run dev
```

The deployed frontend uses the same-origin `/api` route by default. Users sign
in with a browser wallet by approving a one-time message; the server verifies
the wallet session and never exposes the Vercel-managed API bearer token to the
frontend. `AEGIS_SESSION_SECRET` is required for this hosted wallet session and
must remain server-only. Provider public keys remain a required deployment
secret for any evidence-backed authorization;
an empty provider-key set fails closed into repair rather than fabricating an
approval.

## Repository layout

- `api/` — Vercel Python entrypoint for the production API.
- `backend/` — contract-independent engine, models, persistence, and HTTP API.
- `contracts/` — GenLayer action firewall and consensus decision gateway.
- `docs/` — architecture, API, security, verification, and deployment evidence.
- `frontend/` — Vite/React command surface with responsive interaction states.
- `tests/` — unit, integration, adversarial, restart, and concurrency tests.

## GenLayer boundary

The contracts are the on-chain enforcement layer for policy registration,
intent submission, finalized decisions, evidence repair, and single-use
receipts. The current repair-capable stack and finalized Bradbury behavior are
recorded in the deployment evidence document. The API's
`/evaluate-genlayer` route verifies those finalized records; its former direct
`/evaluate` route is intentionally retired.

The live deployment is testnet evidence, not a production-network claim. Any
future network or contract change must produce a new source-matched deployment
record and repeat the finality checks before release.

The Vercel deployment uses `vercel.json` to build `frontend/`, route `/api/*`
to the Python function, and keep state in the connected Neon Postgres resource.
The function takes a row lock around every engine snapshot, commits before a
successful response is emitted, and therefore does not rely on ephemeral
serverless filesystem state.

## Development checks

Before committing backend changes, run:

```sh
.venv/bin/python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/private/tmp/aegis-pycache .venv/bin/python -m compileall -q backend contracts tests
git diff --check
```

Changes to the state machine, receipt binding, evidence validation, or
contracts should include tests and an updated verification record when live
behavior changes.
