# Bradbury deployment and live backend evidence

This document supersedes the earlier provisional deployment record. The
current source is the committed source at `344a09a` (`enforce complete
firewall state parity`). The network is Testnet Bradbury (`chainId 4221`,
`https://rpc-bradbury.genlayer.com`).

The deployment account is
`0x1f87Ae197af539253978d435aD45cCf28Fb95024`.

## Current repair-capable stack

| Component | Address | Transaction | Result |
| --- | --- | --- | --- |
| Decision gateway | `0x7f55B4935f5cBd6ece4060d5B080c4EcD089791D` | `0xb5e6be301fae7cbf5da4b95ce8443bc094cb63b743ee3f7e6970b7919f5cd6a1` | accepted, successful deployment |
| Action firewall | `0x263De60E6831F70082B037C450597d374C2e573D` | `0x4a1cc9975345d04c1421413c7ca87d99a973b7d0537ed0ad6c8ef3d7a60db431` | accepted, successful deployment |
| Gateway binding | — | `0xf52d3f53c2d2b6011fb4299db65e76e74d716a03d32cbe48e701ee2b4f8220cd` | accepted; firewall address matched exactly |
| Policy `live-repair` | — | `0x50b9a719e1015ebc55777e6677bce3037b72c5e7179253615338956c6fd09deb` | accepted; 24-hour expiry and repair window |
| Repair test intent | `0x99…99` | `0xb4abf9e6c418c1587e4ad6f8973d0c016380de481e1073dadec99029e0653115` | accepted; read-back was `PENDING` |

The repair test intent binds action hash `0x11…11`, target hash `0x33…33`,
payload hash `0x44…44`, value `500`, evidence digest `0x55…55`, and a stable
action-intent digest. The exact subject and action-intent digest must remain
unchanged across repair and evidence replacement.

## Repair gateway reachability proof

The corrected gateway exposes the owner-authorized `request_repair` method. It
does not mutate firewall state directly: it validates the pending intent and
emits the firewall’s existing gateway-only `mark_repair_required` message.

| Operation | Transaction | Initial result |
| --- | --- | --- |
| Request repair with `SOURCE_NOT_APPROVED` | `0xf718a5a28072fd5fe754e06d1a541c1848a32f59616c7d03f36e58ccc321a016` | accepted, 5/5 agreement; emitted `mark_repair_required` to the exact firewall |

The emitted message is finalized delivery. `ACCEPTED` is not treated as
finality. The post-finalization state must be read back as state `2`
(`REPAIR_REQUIRED`) before evidence replacement is submitted.

The repair transaction finalized as
`0xf718a5a28072fd5fe754e06d1a541c1848a32f59616c7d03f36e58ccc321a016` with
5/5 agreement. The read-back then showed state `2` and reason
`SOURCE_NOT_APPROVED`.

## Finalized rejection and replacement evidence

The independent rejection intent uses ID `0xaa…aa`. Its decision transaction
was finalized as
`0xb3abedda2857dcb83cc19eb89e178ccc823285ee2c5cf66c420f23748592f9ee` with
5/5 consensus agreement and a finalized `record_decision` message carrying
`DENY`. Its terminal state must be read back as `DENIED` with no receipt.

The replacement transaction was finalized as
`0xb4cf32b7e41ec1d052d2a7c3fffa6ec6d138077b0bc81334db1d6bc22e699afe` with
5/5 agreement. Read-back showed evidence digest `0x66…66`, revision `1`,
state `PENDING`, reason `EVIDENCE_REPLACED`, and unchanged action subject,
action-intent digest, and repair deadline.

## Current-source production API parity proof

On 2026-10-04, the production API was exercised against a fresh 24-hour
intent so the Bradbury finalization window could not outlive the intent:

| Field | Value |
| --- | --- |
| Intent | `0673514660b1a40333aa95c65bb2a58f173d5c8d8cdda0fca3ee12ef51775a1d` |
| Submit transaction | `0x5606bdb3775c560f7a37552dcef9a9ff4a29e224f1274a94d5ac2dbee67b8e06` |
| Decision transaction | `0x2af1f628ccecca7ec985788e1b2994f0f1b65e3eec70a7177ab3387060cb09dd` |
| Finalized decision | `DENY`, 5/5 agreement, finalized Bradbury receipt |
| Finalized firewall state | `DENIED` / `CONSENSUS_DENIED`, state `4` |
| Receipt | none |
| Production evaluator | HTTP `200`; exact proof and all bindings verified |
| Production persisted state | `DENIED` / `GENLAYER_FINALIZED_DENIED` |

An earlier decision transaction (`0x7584…ed76f`) was intentionally not
accepted by the backend after finality because its short-lived intent had
expired before the consensus window closed. The firewall recorded
`INTENT_EXPIRED`; no caller-supplied decision or acceptance shortcut was used.

## Release boundary

The backend source and local verification are complete, and the current
repair-capable contracts are deployed on Bradbury. The following stateful
release checks are recorded from finalized Bradbury transactions:

1. `REPAIR_REQUIRED` with reason `SOURCE_NOT_APPROVED`. **Verified.**
2. Evidence replacement returning to `PENDING`, with revision incremented and
   the action subject, action-intent digest, and repair deadline unchanged.
   **Verified.**
3. A finalized `AUTHORIZE` transition after replacement. The transaction is
   `0xc298baf9300f7603265c99415e9f727b37326e0d43099b1f17bff1ad2abd232c`,
   finalized with 5/5 agreement, and the intent reads `AUTHORIZED` with
   reason `CONSENSUS_AUTHORIZED` and receipt
   `0xc8f91ee0e8cb3690d1f57d9dd366ff9a78975db4479c500b4daee2df4de7b238`.
4. A separate finalized `DENY` transition with no receipt. The decision
   transaction is finalized and terminal state read-back is `DENIED` with no
   receipt. **Verified.**
5. Receipt consumption exactly once and finalized replay rejection. The first
   consumption transaction is
   `0x891a37968297da64e429840c7cd72beed9abc9e1849992f64e9c853581550442` and
   finalized with 5/5 agreement; the intent now reads `CONSUMED` with reason
   `CONSUMED`. The replay transaction is
   `0x1cfb5e6d096c39f81411a79b4d852de247609523cc649c6e4366edd2fbe55b14` and
   finalized with 5/5 `DISAGREE`, `FINISHED_WITH_ERROR`, and trace error
   `RECEIPT_CONSUMED_OR_UNKNOWN`; the final state remains `CONSUMED`.

All five stateful release checks above are now verified from finalized
Bradbury transactions. Timeout/restart semantics remain covered by the local
restart-safe backend tests; no automatic resend or replacement is used.

No frontend work is represented by this document.
