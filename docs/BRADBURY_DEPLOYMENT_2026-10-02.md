# Bradbury deployment evidence

This file records the live Bradbury testnet deployment performed from commit
`c616fe0` after the gateway proxy-call fix.

Network: `testnet-bradbury` (`chainId 4221`, RPC `https://rpc-bradbury.genlayer.com`)

Account: `0x1f87Ae197af539253978d435aD45cCf28Fb95024`

## Corrected stack

| Component | Address | Transaction | Observed result |
| --- | --- | --- | --- |
| Decision gateway | `0x29C3918d74CdB25477f7954bBeb7fC6b4CEDe590` | `0x4e716996b667ee157bdf3df36949a89bd2d9c4033114d48ce557cde1b0b3d92d` | `ACCEPTED`, 5/5 `AGREE`, successful deployment |
| Action firewall | `0xF2a952f90b638be143aF8558d8c771d005E8b202` | `0x2f89a7631bc7cc93d95448b1f47d9a4975574338d3e55b6e2fc2fde36552f3c7` | `ACCEPTED`, 5/5 `AGREE`, successful deployment |
| Gateway binding | — | `0xc5f3989f5d670ebdb967ec34f2ce430fbb1a189a3aaff96326ce35e576c0c072` | `ACCEPTED`, 5/5 `AGREE`; `get_firewall` returns the exact firewall address |
| Policy registration | `0xF2a952f90b638be143aF8558d8c771d005E8b202` | `0x1b4f053c05da513200981c368ad243a72e570a6d29d5d118306ae4b9242b9e1c` | `ACCEPTED`, 5/5 `AGREE` |
| Fresh intent | `0xF2a952f90b638be143aF8558d8c771d005E8b202` | `0x1b1fbb2afe28431cf59e04c0d65a8252b4fba585b4d8f0d5dc381a5d8fba1bcf` | `ACCEPTED`, 5/5 `AGREE`; read-back is `PENDING` with exact hashes |
| Consensus decision | `0x29C3918d74CdB25477f7954bBeb7fC6b4CEDe590` | `0x1698a1036bb635e046fd69d4558340cdc859c9c66d6627a14726855197079952` | `ACCEPTED`, successful execution; 5 validators agreed on `AUTHORIZE`; emitted `record_decision` message |

The decision receipt reports `validUntil = 1790984217`, which is
`2026-10-03 00:36:57 WAT`. The decision remains provisional until the appeal
window closes. The emitted firewall message is deliberately configured for
finalized delivery, so it must not be replaced with an on-acceptance shortcut.
After the window, finalize the decision transaction and verify that the intent
becomes `AUTHORIZED`; only then consume its receipt and verify replay rejection.

## Corrected execution proof

The gateway trace for the decision transaction contains:

- return data `AUTHORIZE`;
- no VM error or proxy lookup error;
- a message to the exact firewall address calling `record_decision`;
- the commitment bound to the exact action intent.

The previous immutable gateway deployment is obsolete. Its trace exposed the
actual defect (`gl.contract.get_at` was unavailable on Bradbury). The source
was corrected to `gl.get_contract_at`, linted, committed, and redeployed before
this evidence was collected.

## Finality boundary

The live transactions above are not yet protocol-finalized at the time this
record was written. `ACCEPTED` plus `FINISHED_WITH_RETURN` proves successful
initial consensus execution, not finality. No release claim should be made
until the finalization transaction succeeds and the post-message state is read
back from Bradbury.
