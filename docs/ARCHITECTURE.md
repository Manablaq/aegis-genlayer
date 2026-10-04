# Aegis architecture

Aegis separates policy enforcement, evidence verification, consensus, and
execution receipts so that no single caller can turn an unverified intent into
an authorized action.

## System layers

```text
Provider attestations
        │  Ed25519 signatures over canonical envelopes
        ▼
backend/engine.py ── JsonStore locally / Postgres row lock on Vercel
        │
        │  authenticated JSON API
        ▼
backend/api.py / backend/server.py
        │
        │  finalized decision commitment
        ▼
AegisDecisionGateway ── finalized GenLayer consensus
        │
        │  gateway-only state transition
        ▼
AegisActionFirewall ── policy, intent, repair, expiry, receipt rules
        │
        ▼
Single-use execution receipt ── exact consumer and action-intent binding
```

### Contract-independent engine

`backend/engine.py` is the reference state machine used by the API and tests.
It validates policy versions, action subjects, canonical evidence, freshness,
allowlisted sources and recipients, consensus tokens, receipt binding, and
terminal transitions. `backend/store.py` persists local state atomically and
fsyncs both the file and its parent directory. The Vercel adapter in
`backend/postgres_store.py` uses a single JSONB snapshot row with
`SELECT ... FOR UPDATE`; every successful mutation commits the updated
snapshot before its response is sent.

### HTTP API

`backend/api.py` exposes the authenticated JSON boundary. Health is public;
mutating routes and intent reads require the bearer token configured through
`AEGIS_API_TOKEN`. The complete route contract is in [API.md](API.md).

### GenLayer contracts

The decision gateway reads the exact pending intent, asks the nondeterministic
consensus primitive for one of two decision tokens, and emits a commitment to
the firewall. The firewall accepts decision messages only from the bound
gateway. The repair gateway path is owner-authorized and emits the existing
gateway-only repair transition; it cannot write firewall state directly.

## Intent lifecycle

```text
                 ┌──────────────────┐
                 │      PENDING     │
                 └───────┬──────┬───┘
                         │      │
              invalid evidence  │ finalized decision
                         │      │
                         ▼      ├──────────────► DENIED
                 REPAIR_REQUIRED │
                         │      └──────────────► AUTHORIZED
                         │                              │
                 replacement evidence                   │ valid receipt
                         │                              ▼
                         └──────────────► PENDING   CONSUMED

             expiry from a non-terminal state ───────► EXPIRED
```

The action subject, action-intent digest, and repair deadline are fixed at
intent creation. Evidence replacement can increment only the evidence
revision and evidence digest. A receipt is created only by a finalized
authorization and can be consumed once by the exact consumer for the exact
action-intent digest.

## Trust boundaries

1. Provider evidence is untrusted until its Ed25519 signature, canonical
   payload, source allowlist, timestamps, and freshness pass validation.
2. The consensus gateway is not allowed to invent an intent; it reads the
   firewall’s pending record and commits to that record’s exact action intent.
3. The firewall is the on-chain authority for state transitions and receipt
   binding. Caller identity, gateway binding, policy limits, expiry, and
   replay checks are enforced on-chain.
4. Receipt consumers are untrusted callers. Wrong consumers, wrong action
   intents, expired receipts, missing receipts, and replays fail closed.

## Failure and recovery model

- Invalid evidence enters `REPAIR_REQUIRED` only through the authorized repair
  path; policy violations are denied rather than repaired.
- Expiry is terminal and cannot be reversed by replacement or evaluation.
- Restart recovery reloads persisted state and never automatically resends an
  unknown transaction.
- Consensus `ACCEPTED` is not treated as final. On-chain evidence records only
  finalized state transitions as release proof.

## Deployment scope

The current repair-capable contracts are deployed and behaviorally verified on
Testnet Bradbury. Addresses, transaction identifiers, and the finalized live
checks are maintained in
[BRADBURY_DEPLOYMENT_2026-10-02.md](BRADBURY_DEPLOYMENT_2026-10-02.md).
The frontend and API are deployed together on Vercel. The frontend reaches the
API through same-origin `/api/*` rewrites; bearer authentication remains
explicit and provider-key configuration remains fail-closed.
