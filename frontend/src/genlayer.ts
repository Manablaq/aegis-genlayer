import type { Eip1193Provider } from './wallet'

export const BRADBURY_CHAIN_ID = 4221
export const AEGIS_GATEWAY_ADDRESS = '0x2a274E66687AF4f8FD6B3DAeffCf02C736233000' as const
export const AEGIS_FIREWALL_ADDRESS = '0x2D8CfEFf124eBCb813CA55ad90Ceff93a6d6E523' as const

type BradburyClient = ReturnType<typeof import('genlayer-js')['createClient']>

export interface FinalizedGenLayerWrite {
  hash: `0x${string}`
  receipt: Awaited<ReturnType<BradburyClient['waitForTransactionReceipt']>>
}

function bytes32(value: string, label: string): Uint8Array {
  const normalized = value.trim().replace(/^0x/i, '')
  if (!/^[0-9a-f]{64}$/i.test(normalized)) throw new Error(`${label} must be exactly 32 bytes.`)
  const result = new Uint8Array(32)
  for (let index = 0; index < 32; index += 1) result[index] = Number.parseInt(normalized.slice(index * 2, index * 2 + 2), 16)
  return result
}

function requireAccount(account: string): `0x${string}` {
  if (!/^0x[0-9a-f]{40}$/i.test(account)) throw new Error('The connected wallet address is invalid.')
  return account as `0x${string}`
}

function isSuccessful(receipt: FinalizedGenLayerWrite['receipt']): boolean {
  return receipt.txExecutionResultName === 'FINISHED_WITH_RETURN'
}

async function clientFor(provider: Eip1193Provider, account: string): Promise<BradburyClient> {
  const [{ createClient }, { testnetBradbury }] = await Promise.all([import('genlayer-js'), import('genlayer-js/chains')])
  const client = createClient({
    chain: testnetBradbury,
    account: requireAccount(account),
    provider: provider as never
  })
  const chainId = await provider.request({ method: 'eth_chainId' })
  if (chainId !== `0x${BRADBURY_CHAIN_ID.toString(16)}`) await client.connect('testnetBradbury')
  return client
}

async function writeAndFinalize(client: BradburyClient, args: Parameters<BradburyClient['writeContract']>[0], label: string): Promise<FinalizedGenLayerWrite> {
  const { TransactionStatus } = await import('genlayer-js/types')
  const hash = await client.writeContract(args)
  const receipt = await client.waitForTransactionReceipt({
    hash,
    status: TransactionStatus.FINALIZED,
    interval: 5_000,
    retries: 360
  })
  if (!isSuccessful(receipt)) throw new Error(`${label} finalized with a contract execution error.`)
  return { hash, receipt }
}

export async function submitIntentOnChain({ provider, account, intentId, policyId, actionHash, targetHash, payloadHash, value, expiresAt, evidenceDigest }: { provider: Eip1193Provider; account: string; intentId: string; policyId: string; actionHash: string; targetHash: string; payloadHash: string; value: number; expiresAt: number; evidenceDigest: string }): Promise<FinalizedGenLayerWrite> {
  const client = await clientFor(provider, account)
  return writeAndFinalize(
    client,
    {
      address: AEGIS_FIREWALL_ADDRESS,
      functionName: 'submit_intent',
      args: [bytes32(intentId, 'Intent ID'), policyId, bytes32(actionHash, 'On-chain action hash'), bytes32(targetHash, 'Target hash'), bytes32(payloadHash, 'Payload hash'), BigInt(value), BigInt(expiresAt), bytes32(evidenceDigest, 'Evidence digest')],
      value: 0n
    },
    'Intent submission'
  )
}

export async function decideIntentOnChain({ provider, account, intentId, evidenceContext }: { provider: Eip1193Provider; account: string; intentId: string; evidenceContext: string }): Promise<FinalizedGenLayerWrite> {
  const client = await clientFor(provider, account)
  return writeAndFinalize(
    client,
    {
      address: AEGIS_GATEWAY_ADDRESS,
      functionName: 'decide',
      args: [bytes32(intentId, 'Intent ID'), evidenceContext],
      value: 0n
    },
    'Consensus decision'
  )
}

export async function replaceEvidenceOnChain({ provider, account, intentId, evidenceDigest }: { provider: Eip1193Provider; account: string; intentId: string; evidenceDigest: string }): Promise<FinalizedGenLayerWrite> {
  const client = await clientFor(provider, account)
  return writeAndFinalize(
    client,
    {
      address: AEGIS_FIREWALL_ADDRESS,
      functionName: 'replace_evidence',
      args: [bytes32(intentId, 'Intent ID'), bytes32(evidenceDigest, 'Evidence digest')],
      value: 0n
    },
    'Evidence replacement'
  )
}

export async function consumeReceiptOnChain({ provider, account, receiptId, actionIntent }: { provider: Eip1193Provider; account: string; receiptId: string; actionIntent: string }): Promise<FinalizedGenLayerWrite> {
  const client = await clientFor(provider, account)
  return writeAndFinalize(
    client,
    {
      address: AEGIS_FIREWALL_ADDRESS,
      functionName: 'consume_receipt',
      args: [bytes32(receiptId, 'Receipt ID'), bytes32(actionIntent, 'Action-intent digest')],
      value: 0n
    },
    'Receipt consumption'
  )
}
