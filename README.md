# Aegis

Aegis is a fail-closed action firewall for autonomous AI agents. It turns a
policy-approved agent intent into a single-use execution receipt only after
the evidence and the GenLayer consensus decision satisfy the policy.

This repository is backend-only for now. The frontend is intentionally out of
scope until the contract-independent backend state machine, persistence, API,
and adversarial tests are complete.

## Backend invariants

- No privileged bypass path exists in the state machine.
- Invalid, stale, conflicting, missing, or unverifiable evidence never
  authorizes an action.
- Every receipt is bound to the exact intent, action subject, consumer, and
  expiry, and can be consumed once.
- Evidence repair increments a revision without changing the action subject
  or repair deadline.
- Restart recovery uses persisted state; it never resends a transaction.
- Redirect provenance is not trusted. Production attestations must be signed
  by an approved provider and bind the canonical resource and payload.

## Run the backend tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The HTTP service is started with:

```sh
AEGIS_API_TOKEN='replace-me' python3 -m backend.server
```

The API binds to `127.0.0.1:8081` by default. It has no frontend dependency.

HTTP routes and authentication are documented in [`docs/API.md`](docs/API.md).
The security model and finalized deployment evidence are documented in
[`docs/BACKEND_SECURITY_BOUNDARY.md`](docs/BACKEND_SECURITY_BOUNDARY.md) and
[`docs/BRADBURY_DEPLOYMENT_2026-10-02.md`](docs/BRADBURY_DEPLOYMENT_2026-10-02.md).

## GenLayer boundary

The GenLayer contract is an adapter for registering policies, submitting
intents, recording finalized decisions, and consuming receipts. The service
source is deployed on Bradbury and the finalized live behavior is recorded in
`docs/BRADBURY_DEPLOYMENT_2026-10-02.md`. The repository remains backend-only;
the frontend is the next workstream.
