# Aegis backend security boundary

The backend has two layers:

1. `backend/engine.py` is the contract-independent reference state machine.
   It validates policy constraints, provider attestations, evidence freshness,
   consensus decision tokens, receipt binding, repair transitions, expiry, and
   restart persistence.
2. `contracts/aegis_action_firewall.py` is the GenLayer state/receipt adapter.
   Policy versions are immutable, intent subjects are fixed at creation, only
   the immutable decision gateway can finalize a decision, and receipts are
   single-use.

The decision gateway is an explicit trust boundary: it must itself be a
GenLayer-finalized component and must commit to the exact action intent and
decision token. The Aegis contract does not accept arbitrary caller-supplied
authorization, upgrade calls, emergency bypasses, or unbound receipt IDs.

Provider evidence is expected to use Ed25519 signatures over the canonical
attestation envelope. The production HTTP server requires `cryptography` and
uses `Ed25519Verifier`; the test suite uses `StaticVerifier` only as an
explicit test double. A missing production crypto dependency fails startup.

The HTTP API does not expose a caller-supplied consensus decision. The former
direct evaluation route returns `GENLAYER_FINALITY_REQUIRED`. The canonical
GenLayer route requires protocol finality, successful execution, the exact
gateway, a structured `decide` call, a matching decision trace, and a
finalized firewall read-back. It additionally compares the read-back action
subject, action-intent digest, consumer, expiry, and repair deadline with the
persisted local intent before applying the off-chain mirror transition.

Redirect provenance is not used as a security primitive: the signed envelope
binds the provider, canonical resource, timestamps, and payload digest. The
current Bradbury deployment and finalized state-transition evidence are
recorded in `docs/BRADBURY_DEPLOYMENT_2026-10-02.md`.
