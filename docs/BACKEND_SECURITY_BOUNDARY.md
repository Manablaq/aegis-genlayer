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

The known redirect-provenance weakness is not used as a security primitive:
the signed envelope binds the provider, canonical resource, timestamps, and
payload digest. The target GenLayer runtime still requires independent
verification before deployment; this design does not claim that target proof.
