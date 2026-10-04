# Aegis backend verification — 2026-10-03

The backend includes:

- a fail-closed policy and intent state machine;
- production Ed25519 provider-attestation verification;
- atomic restart-safe JSON persistence with file and parent-directory fsync;
- serialized transitions so concurrent requests cannot double-consume a
  receipt;
- token-authenticated HTTP API with public health only;
- immutable policy versions, bounded evidence, canonical action subjects,
  repair/deadline invariants, exact receipt binding, and replay protection;
- a GenLayer adapter with immutable policies, gateway-bound commitments,
  explicit terminal transitions, single-use receipts, no-redirect RPC
  handling, and local/on-chain action-binding parity checks.

## Local verification

- All 23 backend unit/integration tests pass, including Ed25519 tamper
  rejection, restart recovery, concurrent consumption, redirect ambiguity,
  repair invariants, and API authentication.
- Python compilation and `git diff --check` pass.
- The current gateway source was validated with the GenLayer RC7 toolchain
  before deployment; the deployed Bradbury source was retrieved and includes
  the exact owner-authorized `request_repair` path.

## Finalized Bradbury verification

The current repair-capable deployment is recorded in
`docs/BRADBURY_DEPLOYMENT_2026-10-02.md`. Finalized live checks prove:

- repair reaches `REPAIR_REQUIRED` without changing the action binding;
- evidence replacement increments revision and returns to `PENDING`;
- replacement reaches finalized `AUTHORIZED` and creates a bound receipt;
- an independent request reaches finalized `DENIED` without a receipt;
- the correct consumer consumes the receipt once;
- replay reaches finalized `FINISHED_WITH_ERROR` with
  `RECEIPT_CONSUMED_OR_UNKNOWN`, while the intent remains `CONSUMED`.

Local restart tests prove persisted recovery without automatic resend or
replacement. The direct caller-supplied evaluation route is retired. The
frontend now sends only finalized GenLayer transaction IDs to the canonical
verification route. A current-source positive end-to-end API proof still
requires a live on-chain intent whose full binding matches the persisted local
intent; the adapter rejects the request rather than weakening this boundary
when the binding is absent or mismatched.
