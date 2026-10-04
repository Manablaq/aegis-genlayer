import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode, RefObject } from 'react'
import {
  AlertCircle,
  ArrowUpRight,
  BadgeCheck,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  CircleX,
  Clock3,
  Copy,
  ExternalLink,
  FileCheck2,
  Fingerprint,
  GitBranch,
  LockKeyhole,
  LoaderCircle,
  LogOut,
  Mail,
  Menu,
  MoveDown,
  Network,
  Play,
  Receipt,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Settings2,
  WalletCards,
  Wrench,
  X,
  Zap,
} from 'lucide-react'
import {
  connectWallet,
  formatAddress,
  formatChain,
  getInjectedProvider,
  readWalletState,
  revokeWalletPermissions,
  walletErrorMessage,
} from './wallet'
import type { ProviderListener, WalletSnapshot } from './wallet'
import OperatorConsole from './OperatorConsole'

type FlowKey = 'evidence' | 'consensus' | 'receipt'
type ProofStatus = 'AUTHORIZED' | 'DENIED' | 'REPAIR_REQUIRED' | 'CONSUMED'
type SandboxStage = 'form' | 'running' | 'complete'
type SandboxForm = { action: string; target: string; amount: string }
type ViewMode = 'landing' | 'app'

const proofId = '0x2D8CfEFf124eBCb813CA55ad90Ceff93a6d6E523'
const verificationRecordUrl = 'https://github.com/Manablaq/aegis-genlayer/blob/main/docs/BRADBURY_DEPLOYMENT_2026-10-02.md'

const flowContent: Record<FlowKey, { eyebrow: string; title: string; copy: string; metric: string; detail: string }> = {
  evidence: {
    eyebrow: '01 / EVIDENCE',
    title: 'Every request starts with a bounded source.',
    copy: 'Approved origins, method, path, body and expiry are committed before an agent can ask for action.',
    metric: '0 redirect gaps',
    detail: 'Canonical request identity · exact source hash · fixed validity window',
  },
  consensus: {
    eyebrow: '02 / CONSENSUS',
    title: 'Independent validators decide the outcome.',
    copy: 'The gateway waits for finalized agreement before an action can leave the policy boundary.',
    metric: 'MAJORITY_AGREE',
    detail: 'Finalized decision · deterministic policy · repair-safe evaluation',
  },
  receipt: {
    eyebrow: '03 / RECEIPT',
    title: 'A successful action leaves one durable proof.',
    copy: 'The consuming contract binds the action to a finalized decision and rejects replays or wrong consumers.',
    metric: '1× consumable',
    detail: 'Receipt binding · single consumption · replay protection',
  },
}

const proofDetails: Record<ProofStatus, { copy: string; evidence: string }> = {
  AUTHORIZED: { copy: 'Finalized agreement permits the exact action intent.', evidence: 'MAJORITY_AGREE · FINALIZED' },
  DENIED: { copy: 'Finalized rejection blocks the action and preserves the audit trail.', evidence: 'POLICY VIOLATION · TERMINAL' },
  REPAIR_REQUIRED: { copy: 'The request remains bound while a valid evidence revision is required.', evidence: 'REVISION REQUIRED · IDENTITY PRESERVED' },
  CONSUMED: { copy: 'A receipt was bound once; replay and wrong-consumer attempts are rejected.', evidence: 'SINGLE USE · REPLAY RESISTANT' },
}

const faqs = [
  ['What does Aegis protect?', 'Aegis protects the boundary between an autonomous agent and the external actions it wants to perform. Each action is evaluated against committed evidence and a finalized decision before it can be consumed.'],
  ['Can a failed evaluation be repaired?', 'Yes. The repair path keeps the request identity stable, increments evidence revision, and requires a valid replacement before the request can continue.'],
  ['What happens if the network disappears?', 'Recovery is identity-first. A persisted request and raw response are reconciled before any retry is considered, preventing duplicate submissions or accidental replacement.'],
  ['Is this a production deployment?', 'The proof record is verified Bradbury testnet evidence, not a claim that this frontend is a production control plane. Connect your own authenticated backend endpoint before exposing tenant-specific events.'],
]

type WalletUiState = WalletSnapshot & { providerDetected: boolean; loading: boolean; error: string | null }

const emptyWalletState = (): WalletUiState => ({
  account: null,
  chainId: null,
  providerDetected: Boolean(getInjectedProvider()),
  loading: false,
  error: null,
})

const emptySandboxForm: SandboxForm = { action: 'Release an invoice', target: 'Invoice #42', amount: '250' }

function SandboxModal({ stage, form, onChange, onStart, onReset, onClose, onOperatorMode }: { stage: SandboxStage; form: SandboxForm; onChange: (key: keyof SandboxForm, value: string) => void; onStart: (event: FormEvent<HTMLFormElement>) => void; onReset: () => void; onClose: () => void; onOperatorMode: () => void }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="modal sandbox-modal" role="dialog" aria-modal="true" aria-labelledby="sandbox-title" aria-describedby="sandbox-description"><div className="sandbox-modal-top"><div className="eyebrow"><span className="eyebrow-line" /> PUBLIC SANDBOX</div><button className="modal-close" onClick={onClose} aria-label="Close sandbox dialog"><X size={20} /></button></div><div className="sandbox-mode"><span className="pulse-dot" /> SIMULATED RUN <small>No wallet, token, or data submission required</small></div>{stage === 'form' && <><h2 id="sandbox-title">Protect an action<br /><em>in seconds.</em></h2><p className="modal-copy" id="sandbox-description">Describe a harmless example action. Aegis will walk it through evidence binding, consensus, and a one-time receipt so you can see the product before connecting a real tenant.</p><form className="sandbox-form" onSubmit={onStart}><label>Action<input value={form.action} onChange={(event) => onChange('action', event.target.value)} required placeholder="Release an invoice" /></label><label>Target<input value={form.target} onChange={(event) => onChange('target', event.target.value)} required placeholder="Invoice #42" /></label><label>Amount<input value={form.amount} onChange={(event) => onChange('amount', event.target.value)} required inputMode="decimal" pattern="[0-9]+(\\.[0-9]+)?" placeholder="250" /></label><button className="button button-primary" type="submit">Run protected action <ArrowUpRight size={16} /></button></form><p className="sandbox-note"><Shield size={14} /> Sandbox only. This does not submit a blockchain transaction or call a real external service.</p></>}{stage === 'running' && <div className="sandbox-progress"><div className="sandbox-spinner"><LoaderCircle className="spin" size={30} /></div><h2 id="sandbox-title">Consensus is<br /><em>checking the boundary.</em></h2><p id="sandbox-description">Binding your action to evidence and evaluating the protected path…</p><div className="sandbox-steps"><span className="done"><Check size={14} /> Evidence bound</span><span className="active"><LoaderCircle className="spin" size={14} /> Consensus running</span><span><Receipt size={14} /> Receipt waiting</span></div></div>}{stage === 'complete' && <div className="sandbox-result"><div className="sandbox-result-icon"><CheckCircle2 size={29} /></div><div className="eyebrow">SANDBOX RESULT</div><h2 id="sandbox-title">Action <em>authorized.</em></h2><p id="sandbox-description">The simulated policy allowed <strong>{form.action}</strong> for <strong>{form.target}</strong> with a one-time receipt.</p><div className="sandbox-result-card"><div><span>DECISION</span><strong>AUTHORIZED · FINALIZED</strong></div><div><span>RECEIPT</span><code>demo-receipt-aegis-01</code></div><div><span>REPLAY POLICY</span><strong>CONSUME ONCE</strong></div></div><div className="sandbox-result-actions"><button className="button button-primary" onClick={onReset}>Try another action</button><button className="button button-ghost" onClick={onOperatorMode}>Operate a real tenant <ChevronRight size={16} /></button></div><p className="sandbox-note"><Shield size={14} /> Ready for the real flow? Connect an authenticated backend from the operator control plane.</p></div>}</div></div>
}

function WalletModal({ wallet, onClose, onConnect }: { wallet: WalletUiState; onClose: () => void; onConnect: () => void }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><div className="modal wallet-modal" role="dialog" aria-modal="true" aria-labelledby="wallet-title" aria-describedby="wallet-description"><div className="wallet-modal-header"><span className="wallet-modal-icon"><WalletCards size={21} /></span><button className="modal-close" onClick={onClose} aria-label="Close wallet dialog"><X size={20} /></button></div><div className="eyebrow"><span className="eyebrow-line" /> OPERATOR IDENTITY</div><h2 id="wallet-title">Connect your<br /><em>wallet.</em></h2><p className="modal-copy" id="wallet-description">Use a browser wallet to identify the operator account. Aegis never asks for a seed phrase or private key, and this surface does not sign transactions.</p>{wallet.error && <div className="wallet-error" role="alert"><AlertCircle size={16} /> {wallet.error}</div>}{wallet.providerDetected ? <button className="wallet-option" onClick={onConnect} disabled={wallet.loading}><span className="wallet-option-icon"><WalletCards size={18} /></span><span><strong>{wallet.loading ? 'Connecting…' : 'Browser wallet'}</strong><small>{wallet.loading ? 'Approve the account request in your wallet' : 'Detected on this device'}</small></span><ChevronRight size={18} /></button> : <div className="wallet-empty"><AlertCircle size={20} /><div><strong>No browser wallet detected</strong><p>Install a compatible wallet extension, then reload this page.</p><a href="https://metamask.io/download/" target="_blank" rel="noreferrer">Install MetaMask <ExternalLink size={14} /></a></div></div>}<div className="wallet-safety"><Shield size={16} /> Account access stays in your wallet; the API token stays in this tab.</div></div></div>
}

function AppWorkspace({ wallet, walletMenuOpen, walletMenuRef, addressCopyState, onBack, onOpenWallet, onToggleWalletMenu, onAddressCopy, onDisconnect, onOpenSandbox, walletModal, sandboxModal }: { wallet: WalletUiState; walletMenuOpen: boolean; walletMenuRef: RefObject<HTMLDivElement | null>; addressCopyState: boolean; onBack: () => void; onOpenWallet: () => void; onToggleWalletMenu: () => void; onAddressCopy: () => void; onDisconnect: () => void; onOpenSandbox: () => void; walletModal: ReactNode; sandboxModal: ReactNode }) {
  return <div className="app-shell app-shell-workspace"><header className="app-header"><button className="brand" onClick={onBack} aria-label="Back to Aegis landing page"><span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span><span>AEGIS<span className="brand-dot">.</span></span></button><div className="app-header-title"><span>AEGIS APP</span><strong>Action workspace</strong></div><div className="app-header-actions"><span className="network-pill"><span className="pulse-dot" /> BRADBURY TESTNET</span><div className="wallet-anchor" ref={walletMenuRef}>{wallet.account ? <><button className="wallet-button wallet-button-connected" onClick={onToggleWalletMenu} aria-expanded={walletMenuOpen} aria-haspopup="menu"><span className="wallet-live-dot" /><span className="wallet-network">{formatChain(wallet.chainId)}</span><span className="wallet-address">{formatAddress(wallet.account)}</span><ChevronDown size={15} /></button>{walletMenuOpen && <div className="wallet-menu" role="menu" aria-label="Wallet menu"><div className="wallet-menu-head"><span className="wallet-avatar"><WalletCards size={18} /></span><span><strong>Wallet connected</strong><small>Browser wallet</small></span></div><div className="wallet-menu-network"><span>NETWORK</span><strong>{formatChain(wallet.chainId)}</strong></div><div className="wallet-address-block"><span>ACCOUNT</span><code>{wallet.account}</code><button onClick={onAddressCopy}>{addressCopyState ? <Check size={14} /> : <Copy size={14} />} {addressCopyState ? 'Copied' : 'Copy address'}</button></div><button className="wallet-disconnect" onClick={onDisconnect}><LogOut size={15} /> Disconnect wallet</button></div>}</> : <button className="wallet-button wallet-button-connect" onClick={onOpenWallet}><WalletCards size={16} /> Connect wallet</button>}</div></div></header><main className="app-workspace-main"><section className="workspace-hero" aria-labelledby="workspace-title"><div><div className="eyebrow"><span className="eyebrow-line" /> SECURE ACTION WORKSPACE</div><h1 id="workspace-title">Operate with a<br /><em>clear receipt.</em></h1><p>Connect your wallet to identify the operator, then use the control plane to create, evaluate, repair, and consume protected actions.</p><div className="workspace-actions"><button className="button button-primary" onClick={wallet.account ? onOpenSandbox : onOpenWallet}>{wallet.account ? 'Try a sandbox action' : 'Connect wallet to start'} <ArrowUpRight size={17} /></button><button className="button button-ghost" onClick={() => document.getElementById('app-guide')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>How it works <ChevronRight size={16} /></button></div></div><div className={`workspace-identity ${wallet.account ? 'is-connected' : ''}`}><div className="workspace-identity-icon"><WalletCards size={24} /></div><span className="workspace-label">OPERATOR IDENTITY</span><strong>{wallet.account ? 'Wallet connected' : 'Wallet not connected'}</strong><small>{wallet.account ? `${formatAddress(wallet.account)} · ${formatChain(wallet.chainId)}` : 'Connect a browser wallet to continue'}</small>{wallet.account ? <span className="identity-status"><CircleCheck size={14} /> Ready to operate</span> : <button className="text-link" onClick={onOpenWallet}>Connect wallet <ArrowUpRight size={15} /></button>}</div></section><section className="workspace-guide" id="app-guide" aria-labelledby="app-guide-title"><div className="workspace-guide-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> HOW THE APP WORKS</div><h2 id="app-guide-title">From wallet<br /><em>to receipt.</em></h2></div><p>Your wallet identifies the operator. Your authenticated backend authorizes operations. GenLayer finality decides whether the exact action may proceed.</p></div><div className="workspace-steps"><article><span>01</span><WalletCards size={21} /><h3>Connect wallet</h3><p>Identify the operator account with your browser wallet. Aegis never asks for a seed phrase or private key.</p></article><article><span>02</span><Settings2 size={21} /><h3>Connect control plane</h3><p>Enter your private backend URL and bearer token. The token stays in memory and is never bundled into the frontend.</p></article><article><span>03</span><ShieldCheck size={21} /><h3>Protect an action</h3><p>Create an intent, verify finalized consensus, repair valid evidence, and consume a receipt exactly once.</p></article></div></section><OperatorConsole walletAccount={wallet.account} /></main><footer className="site-footer app-footer section-shell"><button className="brand" onClick={onBack}><span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span><span>AEGIS<span className="brand-dot">.</span></span></button><span className="footer-note">AUTHENTICATED ACTION WORKSPACE</span><button className="text-link" onClick={onBack}>Back to landing <ArrowUpRight size={15} /></button></footer>{walletModal}{sandboxModal}</div>
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value)
    return true
  } catch {
    const fallback = document.createElement('textarea')
    fallback.value = value
    fallback.setAttribute('readonly', '')
    fallback.style.position = 'fixed'
    fallback.style.opacity = '0'
    document.body.appendChild(fallback)
    fallback.select()
    const didCopy = document.execCommand('copy')
    document.body.removeChild(fallback)
    return didCopy
  }
}

function App() {
  const [view, setView] = useState<ViewMode>(() => typeof window !== 'undefined' && window.location.hash === '#app' ? 'app' : 'landing')
  const [activeFlow, setActiveFlow] = useState<FlowKey>('evidence')
  const [activeFaq, setActiveFaq] = useState<number | null>(0)
  const [activeProof, setActiveProof] = useState<ProofStatus>('AUTHORIZED')
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [isSandboxOpen, setIsSandboxOpen] = useState(false)
  const [sandboxStage, setSandboxStage] = useState<SandboxStage>('form')
  const [sandboxForm, setSandboxForm] = useState<SandboxForm>(emptySandboxForm)
  const [isWalletOpen, setIsWalletOpen] = useState(false)
  const [walletMenuOpen, setWalletMenuOpen] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [proofCopyState, setProofCopyState] = useState<'idle' | 'copied' | 'unavailable'>('idle')
  const [addressCopyState, setAddressCopyState] = useState(false)
  const [wallet, setWallet] = useState<WalletUiState>(emptyWalletState)
  const walletMenuRef = useRef<HTMLDivElement>(null)

  const dialogOpen = isPreviewOpen || isWalletOpen || isSandboxOpen

  useEffect(() => {
    const syncView = () => setView(window.location.hash === '#app' ? 'app' : 'landing')
    window.addEventListener('hashchange', syncView)
    window.addEventListener('popstate', syncView)
    return () => {
      window.removeEventListener('hashchange', syncView)
      window.removeEventListener('popstate', syncView)
    }
  }, [])

  useEffect(() => {
    const provider = getInjectedProvider()
    setWallet((current) => ({ ...current, providerDetected: Boolean(provider) }))
    if (!provider) return

    const syncState = async () => {
      try {
        const snapshot = await readWalletState(provider)
        setWallet((current) => ({ ...current, ...snapshot, error: null }))
      } catch {
        setWallet((current) => ({ ...current, error: 'Wallet state could not be read.' }))
      }
    }

    const onAccountsChanged: ProviderListener = (accounts) => {
      const account = Array.isArray(accounts) && typeof accounts[0] === 'string' ? accounts[0] : null
      setWallet((current) => ({ ...current, account, error: null }))
      if (!account) setWalletMenuOpen(false)
    }
    const onChainChanged: ProviderListener = (chainId) => {
      setWallet((current) => ({ ...current, chainId: typeof chainId === 'string' ? chainId : null }))
    }

    void syncState()
    provider.on?.('accountsChanged', onAccountsChanged)
    provider.on?.('chainChanged', onChainChanged)
    return () => {
      provider.removeListener?.('accountsChanged', onAccountsChanged)
      provider.removeListener?.('chainChanged', onChainChanged)
    }
  }, [])

  useEffect(() => {
    if (!dialogOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsPreviewOpen(false)
        setIsWalletOpen(false)
        setIsSandboxOpen(false)
        setSubmitted(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [dialogOpen])

  useEffect(() => {
    if (!walletMenuOpen) return
    const onPointerDown = (event: PointerEvent) => {
      if (!walletMenuRef.current?.contains(event.target as Node)) setWalletMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [walletMenuOpen])

  const navigateToView = (nextView: ViewMode) => {
    const nextHash = nextView === 'app' ? '#app' : ''
    if (window.location.hash !== nextHash) window.history.pushState({}, '', `${window.location.pathname}${nextHash}`)
    setView(nextView)
    setIsMenuOpen(false)
    setWalletMenuOpen(false)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setIsMenuOpen(false)
  }

  const openPreview = () => {
    setSubmitted(false)
    setWalletMenuOpen(false)
    setIsPreviewOpen(true)
  }

  const openSandbox = () => {
    setWalletMenuOpen(false)
    setSandboxForm(emptySandboxForm)
    setSandboxStage('form')
    setIsSandboxOpen(true)
  }

  useEffect(() => {
    if (!isSandboxOpen || sandboxStage !== 'running') return
    const timer = window.setTimeout(() => setSandboxStage('complete'), 950)
    return () => window.clearTimeout(timer)
  }, [isSandboxOpen, sandboxStage])

  const updateSandbox = (key: keyof SandboxForm, value: string) => setSandboxForm((current) => ({ ...current, [key]: value }))

  const startSandbox = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSandboxStage('running')
  }

  const openOperatorMode = () => {
    setIsSandboxOpen(false)
    navigateToView('app')
    window.setTimeout(() => document.getElementById('operate')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0)
  }

  const openWallet = () => {
    setWalletMenuOpen(false)
    setWallet((current) => ({ ...current, error: null }))
    setIsWalletOpen(true)
  }

  const handleConnect = async () => {
    const provider = getInjectedProvider()
    if (!provider) {
      setWallet((current) => ({ ...current, error: 'No browser wallet was detected.' }))
      return
    }
    setWallet((current) => ({ ...current, loading: true, error: null, providerDetected: true }))
    try {
      const snapshot = await connectWallet(provider)
      setWallet((current) => ({ ...current, ...snapshot, loading: false, error: null }))
      setIsWalletOpen(false)
    } catch (error) {
      setWallet((current) => ({ ...current, loading: false, error: walletErrorMessage(error) }))
    }
  }

  const handleDisconnect = async () => {
    const provider = getInjectedProvider()
    if (provider) await revokeWalletPermissions(provider)
    setWallet((current) => ({ ...current, account: null, error: null }))
    setWalletMenuOpen(false)
  }

  const handleProofCopy = async () => {
    const didCopy = await copyText(proofId)
    setProofCopyState(didCopy ? 'copied' : 'unavailable')
    window.setTimeout(() => setProofCopyState('idle'), 2200)
  }

  const handleAddressCopy = async () => {
    if (!wallet.account) return
    const didCopy = await copyText(wallet.account)
    setAddressCopyState(didCopy)
    window.setTimeout(() => setAddressCopyState(false), 1800)
  }

  const submitDemo = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitted(true)
  }

  const walletModal = isWalletOpen ? <WalletModal wallet={wallet} onClose={() => setIsWalletOpen(false)} onConnect={() => void handleConnect()} /> : null
  const sandboxModal = isSandboxOpen ? <SandboxModal stage={sandboxStage} form={sandboxForm} onChange={updateSandbox} onStart={startSandbox} onReset={() => setSandboxStage('form')} onClose={() => setIsSandboxOpen(false)} onOperatorMode={openOperatorMode} /> : null

  if (view === 'app') return <AppWorkspace wallet={wallet} walletMenuOpen={walletMenuOpen} walletMenuRef={walletMenuRef} addressCopyState={addressCopyState} onBack={() => navigateToView('landing')} onOpenWallet={openWallet} onToggleWalletMenu={() => setWalletMenuOpen((value) => !value)} onAddressCopy={() => void handleAddressCopy()} onDisconnect={() => void handleDisconnect()} onOpenSandbox={openSandbox} walletModal={walletModal} sandboxModal={sandboxModal} />

  return (
    <div className="app-shell">
      <header className="site-header" data-testid="site-header">
        <button className="brand" onClick={() => scrollTo('top')} aria-label="Aegis home"><span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span><span>AEGIS<span className="brand-dot">.</span></span></button>
        <div className="header-actions">
          <nav className={`site-nav ${isMenuOpen ? 'is-open' : ''}`} aria-label="Main navigation"><button onClick={() => navigateToView('app')}>Control plane</button><button onClick={() => scrollTo('system')}>System</button><button onClick={() => scrollTo('proof')}>Proof record</button><button onClick={() => scrollTo('faq')}>FAQ</button><button className="app-nav-link" onClick={() => navigateToView('app')}>Launch app <ArrowUpRight size={15} /></button><button className="nav-cta" onClick={openSandbox}>Try sandbox <ArrowUpRight size={15} /></button></nav>
          <div className="wallet-anchor" ref={walletMenuRef}>
            {wallet.account ? <><button className="wallet-button wallet-button-connected" onClick={() => setWalletMenuOpen((value) => !value)} aria-expanded={walletMenuOpen} aria-haspopup="menu"><span className="wallet-live-dot" /><span className="wallet-network">{formatChain(wallet.chainId)}</span><span className="wallet-address">{formatAddress(wallet.account)}</span><ChevronDown size={15} /></button>{walletMenuOpen && <div className="wallet-menu" role="menu" aria-label="Wallet menu"><div className="wallet-menu-head"><span className="wallet-avatar"><WalletCards size={18} /></span><span><strong>Wallet connected</strong><small>Browser wallet</small></span></div><div className="wallet-menu-network"><span>NETWORK</span><strong>{formatChain(wallet.chainId)}</strong></div><div className="wallet-address-block"><span>ACCOUNT</span><code>{wallet.account}</code><button onClick={handleAddressCopy}>{addressCopyState ? <Check size={14} /> : <Copy size={14} />} {addressCopyState ? 'Copied' : 'Copy address'}</button></div><button className="wallet-disconnect" onClick={handleDisconnect}><LogOut size={15} /> Disconnect wallet</button></div>}</> : <button className="wallet-button wallet-button-connect" onClick={openWallet}><WalletCards size={16} /> Connect wallet</button>}
          </div>
          <button className="menu-toggle" onClick={() => setIsMenuOpen((value) => !value)} aria-label={isMenuOpen ? 'Close menu' : 'Open menu'} aria-expanded={isMenuOpen}>{isMenuOpen ? <X size={22} /> : <Menu size={22} />}</button>
        </div>
      </header>

      <main id="top">
        <section className="hero section-shell" aria-labelledby="hero-title"><div className="hero-copy"><div className="eyebrow"><span className="eyebrow-line" /> CONSENSUS-ENFORCED ACTION CONTROL</div><h1 id="hero-title">MAKE EVERY<br /><span>ACTION</span><br />ACCOUNTABLE<span className="hero-period">.</span></h1><p className="hero-lede">Aegis is the final checkpoint for autonomous agents. Bind intent to evidence, let consensus decide, and leave a receipt that can be verified.</p><div className="hero-actions"><button className="button button-primary" onClick={() => navigateToView('app')}>Launch the app <ArrowUpRight size={17} /></button><button className="button button-ghost" onClick={openSandbox}><Play size={15} fill="currentColor" /> Try the sandbox</button></div><div className="hero-meta"><span><span className="pulse-dot" /> READY TO USE</span><span className="meta-divider" /><span>BRADBURY PROOF</span></div></div><div className="hero-art" aria-label="Aegis policy-bound firewall illustration" role="img"><div className="art-grid" /><div className="art-ribbon ribbon-one" /><div className="art-ribbon ribbon-two" /><div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" /><div className="shield-core"><Shield size={94} strokeWidth={1.1} /><div className="core-check"><Check size={23} /></div></div><div className="art-label label-top"><span className="label-kicker">POLICY BOUND</span><strong>ACTIVE</strong></div><div className="art-label label-bottom"><span className="label-kicker">RECEIPT RULE</span><strong>SINGLE-USE</strong></div><div className="art-coordinate">SOURCE<span>:</span>MATCHED / 02</div></div><button className="scroll-cue" onClick={() => scrollTo('system')} aria-label="Scroll to system overview"><MoveDown size={16} /> SCROLL TO EXPLORE</button></section>

        <section className="signal-strip" aria-label="Aegis guarantees"><div><Fingerprint size={17} /><span>ORIGIN BOUND</span></div><div><Network size={17} /><span>FINALITY REQUIRED</span></div><div><LockKeyhole size={17} /><span>REPLAY RESISTANT</span></div><div><BadgeCheck size={17} /><span>RECEIPT VERIFIED</span></div></section>

        <section className="landing-launch section-shell" aria-labelledby="landing-launch-title"><div><div className="eyebrow"><span className="eyebrow-line" /> READY TO OPERATE</div><h2 id="landing-launch-title">Everything you need<br /><em>inside the app.</em></h2><p>Launch the workspace to connect your wallet, configure the authenticated control plane, and run the complete intent lifecycle without exposing credentials in the public page.</p></div><div className="landing-launch-actions"><div className="launch-feature"><WalletCards size={19} /><span><strong>Wallet-first identity</strong><small>Connect without sharing a private key.</small></span></div><div className="launch-feature"><ShieldCheck size={19} /><span><strong>Full lifecycle controls</strong><small>Policy, create, GenLayer, repair, and consume.</small></span></div><button className="button button-primary" onClick={() => navigateToView('app')}>Launch the app <ArrowUpRight size={17} /></button></div></section>

        <section className="system-section section-shell" id="system" aria-labelledby="system-title"><div className="section-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> THE CONTROL SURFACE</div><h2 id="system-title">One protocol.<br /><em>Three hard stops.</em></h2></div><p>Security should be legible under pressure. Aegis turns an agent’s action into a visible, auditable path from request to receipt.</p></div><div className="flow-layout"><div className="flow-tabs" role="tablist" aria-label="Aegis control surface">{(Object.keys(flowContent) as FlowKey[]).map((key, index) => { const item = flowContent[key]; const Icon = key === 'evidence' ? FileCheck2 : key === 'consensus' ? Network : Receipt; return <button key={key} id={`flow-tab-${key}`} className={`flow-tab ${activeFlow === key ? 'active' : ''}`} onClick={() => setActiveFlow(key)} role="tab" aria-selected={activeFlow === key} aria-controls="flow-panel" tabIndex={activeFlow === key ? 0 : -1}><span className="tab-number">0{index + 1}</span><span className="tab-icon"><Icon size={19} /></span><span className="tab-copy"><strong>{item.eyebrow.split(' / ')[1]}</strong><small>{key === 'evidence' ? 'Bound the request' : key === 'consensus' ? 'Make the decision' : 'Consume once'}</small></span><ArrowUpRight className="tab-arrow" size={17} /></button> })}<div className="flow-side-note"><Zap size={15} /> No silent approvals. No ambiguous state.</div></div><div className="flow-panel" id="flow-panel" role="tabpanel" aria-labelledby={`flow-tab-${activeFlow}`}><div className="panel-scanline" /><div className="panel-topline"><span>{flowContent[activeFlow].eyebrow}</span><span className="panel-status"><span className="pulse-dot" /> ENFORCED</span></div><h3>{flowContent[activeFlow].title}</h3><p>{flowContent[activeFlow].copy}</p><div className="panel-bottom"><div><span className="panel-metric">{flowContent[activeFlow].metric}</span><span className="panel-detail">{flowContent[activeFlow].detail}</span></div><ShieldAlert size={43} strokeWidth={1} /></div></div></div></section>

        <section className="proof-section section-shell" id="proof" aria-labelledby="proof-title"><div className="proof-intro"><div className="eyebrow"><span className="eyebrow-line" /> VERIFIED PROOF RECORD</div><h2 id="proof-title">See the state.<br /><em>Trust the state.</em></h2><p>These are verified lifecycle states from the Bradbury deployment record. This page does not invent tenant events or claim a live stream.</p><button className="text-link" onClick={openSandbox}>Try a protected action <ArrowUpRight size={15} /></button></div><div className="proof-board"><div className="board-header"><span><span className="pulse-dot" /> VERIFIED / BRADBURY</span><span>FIREWALL 0x2D8C...E523</span></div><div className="proof-rows"><ProofRow icon={<CircleCheck />} title="AUTHORIZED" copy="Finalized agreement · action may proceed" tone="yellow" active={activeProof === 'AUTHORIZED'} onClick={() => setActiveProof('AUTHORIZED')} /><ProofRow icon={<CircleX />} title="DENIED" copy="Finalized rejection · action blocked" tone="red" active={activeProof === 'DENIED'} onClick={() => setActiveProof('DENIED')} /><ProofRow icon={<Wrench />} title="REPAIR_REQUIRED" copy="Evidence revision required before retry" tone="orange" active={activeProof === 'REPAIR_REQUIRED'} onClick={() => setActiveProof('REPAIR_REQUIRED')} /><ProofRow icon={<Clock3 />} title="CONSUMED" copy="Receipt bound once · replay rejected" tone="green" active={activeProof === 'CONSUMED'} onClick={() => setActiveProof('CONSUMED')} /></div><div className="proof-selection"><span>SELECTED STATE / {activeProof}</span><strong>{proofDetails[activeProof].copy}</strong><small>{proofDetails[activeProof].evidence}</small></div><div className="board-footer"><span>SOURCE MATCH <strong>BRADBURY DEPLOYMENT RECORD</strong></span><span>STATUS <strong>VERIFIED</strong></span></div></div></section>

        <section className="proof-id-section section-shell"><div className="proof-id-copy"><div className="eyebrow"><span className="eyebrow-line" /> VERIFIED CONTRACT</div><h2>Proof you can<br /><em>actually hold.</em></h2><p>Keep the deployed firewall identity close. Copy it, verify it, or open the source record when you need the full chain of evidence.</p><div className="proof-id-actions"><button className="button button-primary" onClick={handleProofCopy} aria-live="polite">{proofCopyState === 'copied' ? <Check size={16} /> : <Copy size={16} />} {proofCopyState === 'copied' ? 'Copied' : proofCopyState === 'unavailable' ? 'Copy unavailable' : 'Copy contract ID'}</button><a className="button button-ghost" href={verificationRecordUrl} target="_blank" rel="noreferrer">View verification record <ExternalLink size={16} /></a></div></div><div className="id-card"><div className="id-card-top"><span><Shield size={17} /> AE / FIREWALL</span><span className="verified-mark"><CheckCircle2 size={16} /> VERIFIED</span></div><div className="id-card-value">{proofId}</div><div className="id-card-bottom"><span>BRADBURY TESTNET</span><span>SOURCE MATCHED</span></div></div></section>

        <section className="faq-section section-shell" id="faq" aria-labelledby="faq-title"><div className="faq-title"><div className="eyebrow"><span className="eyebrow-line" /> QUESTIONS, ANSWERED</div><h2 id="faq-title">Clarity is<br /><em>a feature.</em></h2></div><div className="faq-list">{faqs.map(([question, answer], index) => <div className={`faq-item ${activeFaq === index ? 'open' : ''}`} key={question}><button onClick={() => setActiveFaq(activeFaq === index ? null : index)} aria-expanded={activeFaq === index} aria-controls={`faq-answer-${index}`}><span className="faq-index">0{index + 1}</span><span>{question}</span><ChevronDown size={20} /></button>{activeFaq === index && <div className="faq-answer" id={`faq-answer-${index}`}><p>{answer}</p></div>}</div>)}</div></section>

        <section className="final-cta section-shell"><div className="cta-rings" /><div className="eyebrow"><span className="eyebrow-line" /> READY WHEN YOU ARE</div><h2>Put a boundary<br /><span>around intelligence.</span></h2><p>The safest agent is the one whose next action is always explainable.</p><button className="button button-dark" onClick={() => navigateToView('app')}>Launch the app <ArrowUpRight size={17} /></button></section>
      </main>

      <footer className="site-footer section-shell"><button className="brand" onClick={() => scrollTo('top')}><span className="brand-mark"><Shield size={18} strokeWidth={2.6} /></span><span>AEGIS<span className="brand-dot">.</span></span></button><span className="footer-note">CONSENSUS-ENFORCED CONTROL FOR AUTONOMOUS AGENTS</span><div className="footer-links"><button onClick={() => scrollTo('system')}>System</button><button onClick={() => scrollTo('proof')}>Proof</button><a href="https://github.com/Manablaq/aegis-genlayer" target="_blank" rel="noreferrer" aria-label="Open Aegis on GitHub"><GitBranch size={17} /></a></div></footer>

      {isPreviewOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setIsPreviewOpen(false) }}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" aria-describedby="modal-description"><button className="modal-close" onClick={() => setIsPreviewOpen(false)} aria-label="Close preview dialog"><X size={20} /></button>{submitted ? <div className="modal-success"><CheckCircle2 size={46} /><div className="eyebrow">PREVIEW STAGED LOCALLY</div><h2>You are on the list.</h2><p>Nothing was sent from this form. Connect an authenticated backend endpoint when you are ready to receive real requests.</p><button className="button button-primary" onClick={() => { setSubmitted(false); setIsPreviewOpen(false) }}>Close</button></div> : <><div className="eyebrow"><span className="eyebrow-line" /> PRIVATE PREVIEW</div><h2 id="modal-title">Bring your agent<br /><em>inside the boundary.</em></h2><p className="modal-copy" id="modal-description">This form is local in the current frontend release. It validates the request without transmitting your personal data.</p><form onSubmit={submitDemo}><label>Name<input name="name" required placeholder="Your name" autoComplete="name" /></label><label>Work email<input name="email" type="email" required placeholder="you@company.com" autoComplete="email" /></label><button className="button button-primary" type="submit">Stage preview request <Mail size={16} /></button></form></>}</div></div>}
      {walletModal}
      {sandboxModal}
    </div>
  )
}

function ProofRow({ icon, title, copy, tone, active, onClick }: { icon: ReactNode; title: string; copy: string; tone: string; active: boolean; onClick: () => void }) {
  return <button className={`proof-row ${active ? 'active' : ''}`} onClick={onClick} aria-pressed={active}><span className={`proof-icon tone-${tone}`}>{icon}</span><span className="proof-row-copy"><strong>{title}</strong><span>{copy}</span></span><ChevronRight size={17} className="proof-arrow" /></button>
}

export default App
