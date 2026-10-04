# Submission readiness

This document is the release checklist for the Aegis repository. A submission
is ready only when the source tree, tests, deployment, and documentation all
describe the same wallet-authenticated product.

## Product surface

- The public landing page explains the evidence, consensus, finality, repair,
  and one-time receipt model.
- The public sandbox is explicitly simulated and never submits a transaction
  or calls an external service.
- The app workspace uses a browser wallet for sign-in. It never requests a
  seed phrase, private key, or user-pasted bearer token.
- Authenticated operators can register policies, create intents, verify
  finalized GenLayer decisions, replace evidence during `REPAIR_REQUIRED`,
  refresh persisted state, and consume a receipt once.
- GenLayer verification accepts a finalized transaction hash from the
  explorer, not the Aegis intent ID. The hash is `0x` followed by 64
  hexadecimal characters.

## Required checks

Run these from the repository root before submission:

```sh
cd frontend
npm ci
npm run typecheck
npm run build

cd ..
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPYCACHEPREFIX=/private/tmp/aegis-pycache \
  .venv/bin/python -m compileall -q api backend contracts tests
git diff --check
```

The backend suite covers lifecycle transitions, finalized GenLayer parity,
repair and replacement, restart recovery, replay protection, concurrency, and
HTTP authentication behavior. The frontend build is the same build used by
the Vercel configuration.

## Deployment checks

- `main` is clean and synchronized with `origin/main`.
- The latest Vercel production deployment is `READY` and points to the latest
  `main` commit.
- `GET /api/health` returns `{"ok":true,"service":"aegis-backend"}`.
- `POST /api/auth/challenge` returns a short-lived wallet challenge for an
  allowed origin.
- Production secrets remain Vercel-managed and are not present in Git,
  `VITE_*` variables, or the static frontend bundle.

## Security boundary

The release does not rely on a caller-supplied consensus decision. The
backend independently verifies GenLayer finality, exact calldata, decision
trace, firewall state parity, identity binding, expiry, and receipt binding
before authorizing an intent. Failed or unverifiable evidence cannot become a
successful authorization.

The live Bradbury deployment is testnet evidence. A future network or contract
change requires a new source-matched deployment record and a fresh verification
pass before release.
