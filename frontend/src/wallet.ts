export type ProviderListener = (...args: unknown[]) => void

export interface Eip1193Provider {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>
  on?: (event: string, listener: ProviderListener) => void
  removeListener?: (event: string, listener: ProviderListener) => void
}

declare global {
  interface Window {
    ethereum?: Eip1193Provider & { providers?: Eip1193Provider[] }
  }
}

export interface WalletSnapshot {
  account: string | null
  chainId: string | null
}

export function getInjectedProvider(): Eip1193Provider | null {
  if (typeof window === 'undefined' || !window.ethereum) return null
  const providers = window.ethereum.providers
  return providers?.[0] ?? window.ethereum
}

export async function readWalletState(provider: Eip1193Provider): Promise<WalletSnapshot> {
  const [accounts, chainId] = await Promise.all([
    provider.request({ method: 'eth_accounts' }),
    provider.request({ method: 'eth_chainId' }),
  ])

  return {
    account: Array.isArray(accounts) && typeof accounts[0] === 'string' ? accounts[0] : null,
    chainId: typeof chainId === 'string' ? chainId : null,
  }
}

export async function connectWallet(provider: Eip1193Provider): Promise<WalletSnapshot> {
  const accounts = await provider.request({ method: 'eth_requestAccounts' })
  const chainId = await provider.request({ method: 'eth_chainId' })
  const account = Array.isArray(accounts) && typeof accounts[0] === 'string' ? accounts[0] : null

  if (!account) throw new Error('The wallet did not return an account.')

  return { account, chainId: typeof chainId === 'string' ? chainId : null }
}

export async function revokeWalletPermissions(provider: Eip1193Provider): Promise<void> {
  try {
    await provider.request({ method: 'wallet_revokePermissions', params: [{ eth_accounts: {} }] })
  } catch {
    // Some providers do not implement permission revocation. The app still
    // clears its local session and listens for the provider's next change.
  }
}

export function formatAddress(address: string): string {
  return address.length > 12 ? `${address.slice(0, 6)}…${address.slice(-4)}` : address
}

export function formatChain(chainId: string | null): string {
  if (!chainId) return 'Network unavailable'
  const knownNetworks: Record<string, string> = {
    '0x1': 'Ethereum',
    '0x89': 'Polygon',
    '0xa4b1': 'Arbitrum',
    '0x2105': 'Base',
    '0x107d': 'Bradbury',
  }
  return knownNetworks[chainId.toLowerCase()] ?? `Chain ${chainId}`
}

export function walletErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'code' in error && (error as { code?: number }).code === 4001) {
    return 'The connection request was rejected in your wallet.'
  }
  if (error instanceof Error && error.message) return error.message
  return 'The wallet could not be connected. Check the wallet extension and try again.'
}
