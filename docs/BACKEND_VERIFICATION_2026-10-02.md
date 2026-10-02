# Aegis backend verification — 2026-10-02

The backend currently includes:

- a fail-closed policy and intent state machine;
- Ed25519 provider-attestation verification through the declared production
  `cryptography` dependency;
- atomic restart-safe JSON persistence;
- token-authenticated HTTP API with public health only;
- immutable policy versions, bounded evidence, canonical action subjects,
  repair/deadline invariants, exact receipt binding, and replay protection;
- a GenLayer contract adapter with immutable policy versions, gateway-bound
  decision commitments, explicit state transitions, and single-use receipts.

Verified locally:

- 12 backend unit/integration tests pass;
- Python compilation passes;
- Pyright passes with 0 errors, 0 warnings, and 0 informations;
- GenLayer AST lint passes all 3 checks.

The installed `genvm-lint` package can semantically validate the older local
artifact, but its Python 3.12 schema loader rejects the `u256` NewType used by
that artifact. The current RC8 runner bundle is not available in the local
cache, so no target-network deployment or semantic release claim is made from
that tooling result. The contract remains pinned to the known RC8 dependency
hash and must be validated with the matching RC toolchain before deployment.

No frontend work has started.
