# Bradbury deployment and live backend evidence

This document supersedes the earlier provisional deployment record. The
current source is the committed source at `cb02b75` (`make evidence support
rule explicit`). The network is Testnet Bradbury (`chainId 4221`,
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

## Hardened source-matched stack

The earlier stack above is retained as historical evidence. The active source
candidate uses a gateway that rejects caller-controlled authorization tokens,
binds the exact canonical evidence digest, and uses the documented structured
JSON consensus-validator pattern. Its matching firewall was deployed with the
gateway address in its constructor; the failed constructor-only deployment
(`0xffcf8c3a061c57e054c503d5a05c040bd8ca30644eebf871b3441808c62557ba`) was
not used.

| Component | Address | Transaction | Result |
| --- | --- | --- | --- |
| Decision gateway | `0xA7259b54222405a1FC12D9225916dcDB7FdbDfA0` | `0x6d73040e0e1041f492d11e67ef3ce70f8425ad797ab714e5746e76706b0391d7` | accepted, successful deployment |
| Action firewall | `0xC3C300Ac277E1E657f63AA2100A31509F2Fd2f24` | `0xd69cb5850fd83da28f6837eed095d5ff5571cc545d4232c44aac6702bd341538` | accepted, successful deployment |
| Gateway binding | — | `0x47c29e6beabc574f42356a1873019fd9b11f6d1bd2952684a1b426da2a3a31d8` | accepted; bound to the exact firewall |
| Policy `live-repair-v3` | — | `0xc981a3f47e7c3fe17b04d8ce19b256a596a38474d7368a8db82d6880927ac720` | accepted; 24-hour expiry and repair window |

The active candidate's live positive intent is
`f678c3fdbcd1d95e32a77a69ed9619244cf4361a33267123a3106cf99d316669`. Its
firewall submission is `0xdeed5169bbb5fbfe5f6a96ee0cf1405af2682c73e7d7947e3382fb1ff7566a02`.
The read-back matched the API byte-for-byte: action subject
`d07caeb1931a973306db60a34b994fb27d49953e3b7b9fc506379852736e2561`,
action-intent `77ec96fcfd7ebc68d78ce20b1b39d9ddcbc9d071794f5e2eb48661ebd3330ab2`,
evidence digest `d582c0a4e561261d684e416aa6c6e3bf379690498e49f3c0e3ad26c86300e185`,
expiry `1791193896`, and state `PENDING`.

The first gateway call used the wrong CLI argument type and failed before
contract logic (`context` arrived as a list). The corrected call sent the
canonical evidence as an explicit string and reached 5/5 agreement with
`FINISHED_WITH_RETURN`. Its decision transaction,
`0x56585b6b33da2f2865d923dbeab9f37e87864abdc16878161a253ca3efd93c08`, later
finalized as `DENY`; the firewall read-back was state `4`,
`CONSENSUS_DENIED`, with no receipt. The production evaluator accepted that
finalized proof as `GENLAYER_FINALIZED_DENIED` and preserved exact binding
parity.

The positive case was then rebuilt with a fresh, currently valid Ed25519
attestation whose payload hash equals the requested action payload and whose
statement explicitly identifies `release_payment:invoice-42`. The new intent
is `5b08d64b7da034b0f4f038922c639120933f5628a271e7b33b8a92c8e9452ec2`.
Its firewall submission is
`0x952d0bbc11bff40faa0d94bf9061fa60be95645c2e4bc7740436dbf84e0214fb` and
its gateway decision is
`0xab711c139fa505d11d556519796f968d4019d39cb7e7e78b30d1a750aebe63e5`.
Both reached 5/5 successful agreement; the decision remains `ACCEPTED` until
Bradbury finalizes it. The API evaluator must not be called until the receipt
is `FINALIZED` and the firewall reads back `AUTHORIZED` with a receipt.

The repair test intent binds action hash `0x11…11`, target hash `0x33…33`,
payload hash `0x44…44`, value `500`, evidence digest `0x55…55`, and a stable
action-intent digest. The exact subject and action-intent digest must remain
unchanged across repair and evidence replacement.

## Current source-matched stack

The latest deployment includes the explicit evidence-support rule in the
gateway prompt and is the stack configured by the production API defaults.
The prior hardened stack remains historical evidence and is not the active
configuration.

| Component | Address | Transaction | Result |
| --- | --- | --- | --- |
| Decision gateway | `0x2a274E66687AF4f8FD6B3DAeffCf02C736233000` | `0x7025e2f7e157e4f663de2dc12874ba11e15a6fe0184eb51e4ad3cad8a74344f8` | accepted, successful deployment |
| Action firewall | `0x2D8CfEFf124eBCb813CA55ad90Ceff93a6d6E523` | `0xd7433f62a78fa61c737796b4be553c8dfd41f89857d8fe4a784aedf6f4fc065a` | accepted, successful deployment |
| Gateway binding | — | `0xa806d0d09a728bc508b19dd870c439fa87d0f1f9e6cf3e70fc3b94f283a24bf1` | accepted; bound to the exact firewall |
| Policy `live-repair-v3` | — | `0x7a38f099eb309d60553d100d747f6c4e62100443c0d36338ff2384b393b150bd` | accepted; 24-hour expiry and repair window |

The current-source positive intent is
`59793097271d3d4d43f36a621817afba243f181fa87f0533f60cbabec49b29fb`.
Its firewall submission is
`0x2ac247b85af8e58f171eddc87c4deff3df92070abde629d2793bd776f8383b85`.
The canonical evidence digest is
`190273dd0d1c34cd7b720328cd0232e011c3a507eee8fb526b26b2390db7708c`, with
action-intent `868fbc7826dbb05a44e6330be00c0f21ad2f0868d05a8c8ce4342ab18e7fdd6f`
and action subject
`d07caeb1931a973306db60a34b994fb27d49953e3b7b9fc506379852736e2561`.
The corrected direct-SDK gateway decision transaction is
`0x431bb3d27a301ba0a2e4a69203fff06f6281682c85612d41cad5d826efc2f5b7`.
It reached 5/5 agreement, `FINISHED_WITH_RETURN`, and returned `AUTHORIZE`.
At the time of this record it is `ACCEPTED` and awaiting Bradbury finality;
the API evaluator and receipt-consumption tests must not run until the
receipt is `FINALIZED` and the firewall reads back `AUTHORIZED`.

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
