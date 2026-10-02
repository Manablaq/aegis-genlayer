# Aegis backend verification — 2026-10-02

The backend currently includes:

- a fail-closed policy and intent state machine;
- Ed25519 provider-attestation verification through the declared production
  `cryptography` dependency;
- atomic restart-safe JSON persistence with file and parent-directory fsync;
- serialized state transitions so concurrent requests cannot double-consume a
  receipt;
- token-authenticated HTTP API with public health only;
- immutable policy versions, bounded evidence, canonical action subjects,
  repair/deadline invariants, exact receipt binding, and replay protection;
- a GenLayer contract adapter with immutable policy versions, gateway-bound
  decision commitments, explicit state transitions, and single-use receipts.

Verified locally:

- 16 backend unit/integration tests pass, including the production Ed25519
  verifier and tamper rejection;
- Python compilation passes;
- Pyright passes with 0 errors, 0 warnings, and 0 informations;
- GenLayer AST lint passes all 3 checks;
- semantic GenLayer validation passes with the downloaded `v0.3.0-rc7`
  runner;
- ABI schema extraction passes;
- strict contract type-checking passes with 0 errors and 0 warnings.

The contract remains pinned to the known RC8 dependency hash. The available
linter reports that `v0.3.0-rc7` is newer than that dependency and validates the
source successfully, but this is still local toolchain evidence—not proof of a
Bradbury/Studio deployment or finalized on-chain behavior.

The production `cryptography` dependency and its `cffi` runtime dependency are
installed and the real Ed25519 path has been smoke-tested. The server still
fails closed when the production dependency is absent; the static verifier is
never selected by `backend.server`.

No frontend work has started.
