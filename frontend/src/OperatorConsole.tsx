import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertCircle, Check, ChevronRight, CircleCheck, CircleX, CloudCog, Copy, FilePlus2, KeyRound, LoaderCircle, LockKeyhole, RefreshCw, RotateCcw, Send, Settings2, ShieldCheck, TerminalSquare } from 'lucide-react'
import { apiErrorMessage, checkHealth, consumeReceipt, createIntent, evaluateWithGenLayer, getIntent, registerPolicy, replaceEvidence, testConnection } from './api'
import type { BackendConfig, IntentRecord } from './api'
import { getInjectedProvider } from './wallet'
import { consumeReceiptOnChain, decideIntentOnChain, replaceEvidenceOnChain, submitIntentOnChain } from './genlayer'

type ConsoleTab = 'policy' | 'create' | 'genlayer' | 'repair' | 'consume'

import { defaultApiUrl } from './api'

function newDigest(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

function parseAttestations(value: string): unknown[] {
  const parsed: unknown = JSON.parse(value)
  if (!Array.isArray(parsed)) throw new Error('Attestations must be a JSON array.')
  return parsed
}

function requireDigest(value: string, label: string): string {
  const normalized = value.trim().replace(/^0x/i, '')
  if (!/^[0-9a-f]{64}$/i.test(normalized)) throw new Error(`${label} must be exactly 32 bytes (64 hexadecimal characters).`)
  return normalized
}

function requireAddress(value: string, label: string): string {
  const normalized = value.trim()
  if (!/^0x[0-9a-f]{40}$/i.test(normalized)) throw new Error(`${label} must be a 20-byte 0x address for the GenLayer path.`)
  return normalized
}

function requirePositiveInteger(value: string, label: string): number {
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed <= 0) throw new Error(`${label} must be a positive integer.`)
  return parsed
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  if (value !== null && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value)
}

function normalizeAttestationItems(items: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  return items.map((item) => ({
    provider_id: item['provider_id'],
    resource: item['resource'],
    published_at: item['published_at'],
    observed_at: item['observed_at'],
    expires_at: item['expires_at'],
    payload_hash: item['payload_hash'],
    signature: item['signature'],
    statement: typeof item['statement'] === 'string' ? item['statement'] : ''
  }))
}

function normalizedAttestations(intent: IntentRecord): Array<Record<string, unknown>> {
  return normalizeAttestationItems(intent.attestations)
}

async function evidenceDigest(items: Array<Record<string, unknown>>): Promise<string> {
  const envelope = canonicalJson(normalizeAttestationItems(items))
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(envelope)))].map((byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function evidenceEnvelope(intent: IntentRecord): Promise<string> {
  const envelope = canonicalJson(normalizedAttestations(intent))
  const digest = await evidenceDigest(intent.attestations)
  if (!intent.onchain_evidence_digest || digest !== intent.onchain_evidence_digest.replace(/^0x/i, '').toLowerCase()) {
    throw new Error('The evidence digest returned by the backend does not match the canonical envelope. Reload the intent before signing.')
  }
  return envelope
}

function intentStatusClass(state: string | undefined): string {
  return `intent-state state-${(state || 'UNKNOWN').toLowerCase()}`
}

function NormalOperatorSurface({ walletAccount, connection, message, onOpenSandbox, onRetry }: { walletAccount: string | null; connection: string; message: string; onOpenSandbox?: () => void; onRetry: () => void }) {
  const waiting = connection === 'testing'
  return (
    <div className="operator-shell operator-normal-surface">
      <div className="normal-surface-status">
        <span className={`status-orb ${connection}`} />
        <div>
          <strong>{waiting ? 'SIGNING IN' : walletAccount ? 'WALLET CONNECTED' : 'READY TO START'}</strong>
          <small>{message}</small>
        </div>
      </div>
      <div className="normal-surface-copy">
        <div className="eyebrow">
          <span className="eyebrow-line" /> YOUR ACTION WORKSPACE
        </div>
        <h3>{walletAccount ? 'Your secure workspace is almost ready.' : 'Protect an action in a few clicks.'}</h3>
        <p>{walletAccount ? 'Approve a fresh sign-in message to open the live controls. Aegis never asks for a transaction or private key.' : 'Connect your wallet to sign in. Your wallet identifies you; it never exposes your private key or asks you to paste an API token.'}</p>
        <div className="operator-empty-actions">
          {walletAccount ? (
            <button className="console-button console-button-primary" onClick={onRetry} disabled={waiting}>
              <KeyRound size={15} /> {waiting ? 'Checking session' : 'Sign in with wallet'}
            </button>
          ) : (
            <button className="console-button console-button-primary" onClick={() => window.dispatchEvent(new CustomEvent('aegis:open-wallet'))}>
              <KeyRound size={15} /> Connect wallet
            </button>
          )}
          {onOpenSandbox && (
            <button className="console-button console-button-ghost" onClick={onOpenSandbox}>
              Try public sandbox
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function OperatorConsole({ walletAccount, onOpenWallet, onOpenSandbox }: { walletAccount: string | null; onOpenWallet?: () => void; onOpenSandbox?: () => void }) {
  const [backendUrl, setBackendUrl] = useState(defaultApiUrl)
  const [backendToken, setBackendToken] = useState('')
  const [config, setConfig] = useState<BackendConfig | null>(null)
  const [connection, setConnection] = useState<'idle' | 'setup' | 'available' | 'testing' | 'connected' | 'error'>('idle')
  const [connectionMessage, setConnectionMessage] = useState('No backend session is active.')
  const [showSettings, setShowSettings] = useState(false)
  const [activeTab, setActiveTab] = useState<ConsoleTab>('create')
  const [intentId, setIntentId] = useState('')
  const [intent, setIntent] = useState<IntentRecord | null>(null)
  const [busy, setBusy] = useState(false)
  const [operationMessage, setOperationMessage] = useState('')
  const [operationError, setOperationError] = useState('')
  const [createForm, setCreateForm] = useState({
    intent_id: newDigest(),
    policy_id: 'vendor-payment',
    policy_version: '1',
    agent: 'agent-1',
    action_type: 'release_payment',
    target: 'invoice-42',
    recipient: 'vendor-1',
    value: '0',
    payload_hash: 'c'.repeat(64),
    attestations: '[]',
    genlayer_target_hash: '',
    genlayer_expires_at: ''
  })
  const [policyForm, setPolicyForm] = useState({
    policy_id: 'vendor-payment',
    version: '1',
    approved_agents: 'agent-1',
    allowed_action_types: 'release_payment',
    allowed_recipients: 'vendor-1',
    approved_sources: '{\n  "primary": "https://primary.example/api/",\n  "secondary": "https://secondary.example/api/"\n}',
    max_value: '10000',
    required_sources: 'primary, secondary',
    minimum_attestations: '2',
    maximum_age_seconds: '100',
    intent_ttl_seconds: '600',
    repair_window_seconds: '120',
    onchain_action_hash: ''
  })
  const [caller, setCaller] = useState(walletAccount || 'agent-1')
  const [repairAttestations, setRepairAttestations] = useState('[]')
  const [consensus, setConsensus] = useState<'AUTHORIZE' | 'DENY'>('AUTHORIZE')
  const [genlayerTxId, setGenLayerTxId] = useState('')
  const [intentSubmissionTxId, setIntentSubmissionTxId] = useState('')
  const [decisionTxId, setDecisionTxId] = useState('')
  const [receiptConsumptionTxId, setReceiptConsumptionTxId] = useState('')
  const [receiptId, setReceiptId] = useState('')
  const [consumer, setConsumer] = useState('')
  const [actionIntent, setActionIntent] = useState('')

  useEffect(() => {
    if (!walletAccount) return
    setCaller(walletAccount)
    setCreateForm((current) => (current.agent === 'agent-1' ? { ...current, agent: walletAccount } : current))
    setPolicyForm((current) => (current.approved_agents === 'agent-1' ? { ...current, approved_agents: walletAccount } : current))
  }, [walletAccount])

  useEffect(() => {
    let active = true
    const nextConfig = { baseUrl: defaultApiUrl, token: '' }
    if (!walletAccount) {
      setConfig(null)
      void checkHealth(nextConfig)
        .then(() => {
          if (active) {
            setConnection('available')
            setConnectionMessage('Backend is online. Connect your wallet to sign in and operate.')
          }
        })
        .catch(() => {
          if (active) {
            setConnection('error')
            setConnectionMessage('The app backend is unavailable right now.')
          }
        })
      return () => {
        active = false
      }
    }
    setConnection('testing')
    setConnectionMessage('Checking your wallet session…')
    void testConnection(nextConfig)
      .then(() => {
        if (active) {
          setConfig(nextConfig)
          setConnection('connected')
          setConnectionMessage('Wallet session active. You can operate your protected actions.')
        }
      })
      .catch((error) => {
        if (active) {
          setConfig(null)
          setConnection('setup')
          setConnectionMessage(apiErrorMessage(error))
        }
      })
    return () => {
      active = false
    }
  }, [walletAccount])

  const statusLabel = useMemo(() => {
    if (connection === 'testing') return 'TESTING CONNECTION'
    if (connection === 'connected') return 'BACKEND CONNECTED'
    if (connection === 'available') return 'BACKEND ONLINE · ACTIONS LOCKED'
    if (connection === 'setup') return 'SETUP REQUIRED'
    if (connection === 'error') return 'BACKEND ERROR'
    return 'BACKEND NOT CONNECTED'
  }, [connection])

  const connectBackend = async () => {
    setOperationError('')
    if (!walletAccount) {
      setConnection('setup')
      setConnectionMessage('Connect your wallet to sign in and unlock the app.')
      onOpenWallet?.()
      return
    }
    setConnection('testing')
    setConnectionMessage('Checking your wallet session…')
    setOperationError('')
    try {
      const nextConfig = { baseUrl: defaultApiUrl, token: '' }
      await testConnection(nextConfig)
      setConfig(nextConfig)
      setConnection('connected')
      setConnectionMessage('Wallet session active. You can operate your protected actions.')
      setShowSettings(false)
    } catch (error) {
      setConfig(null)
      setConnection('error')
      setConnectionMessage(apiErrorMessage(error))
    }
  }

  const runOperation = async (operation: () => Promise<void>) => {
    if (!config) {
      setShowSettings(true)
      setOperationError('Connect an authenticated backend before running a state-changing operation.')
      return
    }
    setBusy(true)
    setOperationError('')
    setOperationMessage('Waiting for the backend…')
    try {
      await operation()
    } catch (error) {
      setOperationError(apiErrorMessage(error))
      setOperationMessage('')
    } finally {
      setBusy(false)
    }
  }

  const refreshIntent = async () => {
    if (!config || !intentId.trim()) return
    setBusy(true)
    setOperationError('')
    try {
      const next = await getIntent(config, intentId.trim())
      setIntent(next)
      setOperationMessage('Intent refreshed from the backend.')
      setReceiptId(next.receipt_id || '')
      setConsumer(next.recipient)
      setActionIntent(next.action_intent)
    } catch (error) {
      setOperationError(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const targetHash = createForm.genlayer_target_hash.trim()
      const expiresAt = createForm.genlayer_expires_at.trim()
      const parsedExpiresAt = expiresAt ? Number(expiresAt) : undefined
      if (!createForm.intent_id.trim()) throw new Error('Intent ID is required.')
      if (!createForm.policy_id.trim()) throw new Error('Policy ID is required.')
      if (!Number.isSafeInteger(Number(createForm.policy_version)) || Number(createForm.policy_version) <= 0) throw new Error('Policy version must be a positive integer.')
      if (!Number.isFinite(Number(createForm.value)) || Number(createForm.value) < 0) throw new Error('Value must be a non-negative number.')
      requireDigest(createForm.payload_hash, 'Payload hash')
      if (expiresAt && (parsedExpiresAt === undefined || !Number.isSafeInteger(parsedExpiresAt) || parsedExpiresAt <= 0)) throw new Error('GenLayer expiry must be a positive integer timestamp.')
      if (expiresAt && !targetHash) throw new Error('GenLayer target hash is required when an expiry is provided.')
      if (targetHash) {
        requireDigest(targetHash, 'GenLayer target hash')
        requireAddress(createForm.agent, 'Agent')
        requireAddress(createForm.recipient, 'Recipient')
      }
      const genlayerBinding = targetHash
        ? {
            target_hash: targetHash,
            ...(parsedExpiresAt ? { expires_at: parsedExpiresAt } : {})
          }
        : undefined
      const created = await createIntent(config!, {
        ...createForm,
        policy_version: Number(createForm.policy_version),
        value: Number(createForm.value),
        attestations: parseAttestations(createForm.attestations),
        ...(genlayerBinding ? { genlayer_binding: genlayerBinding } : {})
      })
      setIntent(created)
      setIntentId(created.intent_id)
      setReceiptId(created.receipt_id || '')
      setConsumer(created.recipient)
      setActionIntent(created.action_intent)
      setIntentSubmissionTxId('')
      setDecisionTxId('')
      setReceiptConsumptionTxId('')
      setGenLayerTxId('')
      setActiveTab('genlayer')
      setOperationMessage('Intent created. Submit it to Bradbury to begin the on-chain lifecycle.')
    })
  }

  const requireGenLayerProvider = () => {
    const provider = getInjectedProvider()
    if (!provider) throw new Error('Install or unlock a browser wallet before submitting a GenLayer transaction.')
    if (!walletAccount) throw new Error('Connect the wallet that is bound as the intent agent.')
    return { provider, account: walletAccount }
  }

  const submitIntentToGenLayer = async () => {
    await runOperation(async () => {
      if (!intent) throw new Error('Create or load an intent before submitting it on-chain.')
      if (!intent.onchain_target_hash || !intent.onchain_evidence_digest) throw new Error('This intent has no GenLayer binding. Create it with a target hash and expiry.')
      const actionHash = requireDigest(policyForm.onchain_action_hash, 'On-chain action hash')
      const { provider, account } = requireGenLayerProvider()
      const result = await submitIntentOnChain({
        provider,
        account,
        intentId: intent.intent_id,
        policyId: intent.policy_id,
        actionHash,
        targetHash: intent.onchain_target_hash,
        payloadHash: intent.payload_hash,
        value: intent.value,
        expiresAt: intent.expires_at,
        evidenceDigest: intent.onchain_evidence_digest
      })
      setIntentSubmissionTxId(result.hash)
      setOperationMessage(`Intent finalized on Bradbury. Transaction: ${result.hash}`)
    })
  }

  const runGenLayerDecision = async () => {
    await runOperation(async () => {
      if (!intent) throw new Error('Create or load an intent before running consensus.')
      if (intent.state !== 'PENDING') throw new Error(`This intent is ${intent.state}; only a pending intent can be submitted to the gateway.`)
      const { provider, account } = requireGenLayerProvider()
      const context = await evidenceEnvelope(intent)
      const result = await decideIntentOnChain({
        provider,
        account,
        intentId: intent.intent_id,
        evidenceContext: context
      })
      setDecisionTxId(result.hash)
      setGenLayerTxId(result.hash)
      const next = await evaluateWithGenLayer(config!, intent.intent_id, result.hash, consensus)
      setIntent(next)
      setReceiptId(next.receipt_id || '')
      setConsumer(next.recipient)
      setActionIntent(next.action_intent)
      setOperationMessage(`Consensus finalized as ${next.state}. Decision transaction: ${result.hash}`)
    })
  }

  const submitGenLayer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const submittedTxId = genlayerTxId.trim()
      const normalizedIntentId = intentId.trim().replace(/^0x/i, '').toLowerCase()
      const normalizedTxId = submittedTxId.replace(/^0x/i, '').toLowerCase()
      if (normalizedTxId === normalizedIntentId && normalizedIntentId) {
        throw new Error('The intent ID and GenLayer transaction ID are different. Copy the finalized 0x-prefixed transaction hash from the GenLayer explorer.')
      }
      if (!/^0x[0-9a-f]{64}$/i.test(submittedTxId)) throw new Error('Use the finalized GenLayer transaction hash: it must start with 0x and contain exactly 64 hexadecimal characters.')
      if (!intentId.trim()) throw new Error('Enter an intent ID before verifying finality.')
      const next = await evaluateWithGenLayer(config!, intentId.trim(), submittedTxId, consensus)
      setIntent(next)
      setReceiptId(next.receipt_id || '')
      setConsumer(next.recipient)
      setActionIntent(next.action_intent)
      setOperationMessage(`GenLayer proof verified. Intent is ${next.state}.`)
    })
  }

  const submitPolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const sources: unknown = JSON.parse(policyForm.approved_sources)
      if (!sources || typeof sources !== 'object' || Array.isArray(sources)) throw new Error('Approved sources must be a JSON object.')
      const numericFields: Array<[string, string]> = [
        ['version', 'Version'],
        ['max_value', 'Maximum value'],
        ['minimum_attestations', 'Minimum attestations'],
        ['maximum_age_seconds', 'Maximum evidence age'],
        ['intent_ttl_seconds', 'Intent TTL'],
        ['repair_window_seconds', 'Repair window']
      ]
      for (const [key, label] of numericFields) requirePositiveInteger(policyForm[key as keyof typeof policyForm], label)
      const registered = await registerPolicy(config!, {
        policy_id: policyForm.policy_id.trim(),
        version: Number(policyForm.version),
        approved_agents: policyForm.approved_agents
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
        allowed_action_types: policyForm.allowed_action_types
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
        allowed_recipients: policyForm.allowed_recipients
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
        approved_sources: sources,
        max_value: Number(policyForm.max_value),
        required_sources: policyForm.required_sources
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
        minimum_attestations: Number(policyForm.minimum_attestations),
        maximum_age_seconds: Number(policyForm.maximum_age_seconds),
        intent_ttl_seconds: Number(policyForm.intent_ttl_seconds),
        repair_window_seconds: Number(policyForm.repair_window_seconds),
        onchain_action_hash: policyForm.onchain_action_hash.trim() || null
      })
      setOperationMessage(`Policy ${policyForm.policy_id}:${policyForm.version} ${registered.status.toLowerCase()}.`)
      setActiveTab('create')
    })
  }

  const submitRepair = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      if (!intentId.trim()) throw new Error('Enter an intent ID before replacing evidence.')
      if (!caller.trim()) throw new Error('Caller identity is required.')
      if (!intent) throw new Error('Load the intent before replacing evidence.')
      const attestations = parseAttestations(repairAttestations) as Array<Record<string, unknown>>
      const digest = await evidenceDigest(attestations)
      const { provider, account } = requireGenLayerProvider()
      const chainWrite = await replaceEvidenceOnChain({
        provider,
        account,
        intentId: intent.intent_id,
        evidenceDigest: digest
      })
      const next = await replaceEvidence(config!, intentId.trim(), caller.trim(), attestations, chainWrite.hash)
      setIntent(next)
      setOperationMessage(`Evidence revision ${next.evidence_revision} finalized on Bradbury. Transaction: ${chainWrite.hash}`)
    })
  }

  const submitConsume = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      if (!receiptId.trim() || !consumer.trim() || !actionIntent.trim()) throw new Error('Receipt ID, consumer, and action-intent digest are all required.')
      requireDigest(actionIntent, 'Action-intent digest')
      const { provider, account } = requireGenLayerProvider()
      if (consumer.trim().toLowerCase() !== account.toLowerCase()) throw new Error('The connected wallet must equal the receipt consumer.')
      const chainWrite = await consumeReceiptOnChain({
        provider,
        account,
        receiptId: receiptId.trim(),
        actionIntent: actionIntent.trim()
      })
      setReceiptConsumptionTxId(chainWrite.hash)
      const receipt = await consumeReceipt(config!, receiptId.trim(), consumer.trim(), actionIntent.trim(), chainWrite.hash)
      const next = config ? await getIntent(config, intentId.trim()) : null
      if (next) setIntent(next)
      setOperationMessage(`Receipt ${typeof receipt.receipt_id === 'string' ? receipt.receipt_id.slice(0, 12) : ''}… consumed on-chain and mirrored. Transaction: ${chainWrite.hash}`)
    })
  }

  const updateCreate = (key: keyof typeof createForm, value: string) => setCreateForm((current) => ({ ...current, [key]: value }))

  const retrySession = () => {
    onOpenWallet?.()
    window.dispatchEvent(new CustomEvent('aegis:open-wallet'))
  }

  if (!config)
    return (
      <section className="operator-section section-shell" id="operate" aria-labelledby="operate-title">
        <div className="operator-heading">
          <div>
            <div className="eyebrow">
              <span className="eyebrow-line" /> ACTION WORKSPACE
            </div>
            <h2 id="operate-title">
              Turn proof
              <br />
              <em>into action.</em>
            </h2>
          </div>
          <p>Connect your wallet to open a protected workspace. Aegis keeps backend credentials server-side and uses your signed wallet session for access.</p>
        </div>
        <NormalOperatorSurface walletAccount={walletAccount} connection={connection} message={connectionMessage} onOpenSandbox={onOpenSandbox} onRetry={retrySession} />
      </section>
    )

  return (
    <section className="operator-section section-shell" id="operate" aria-labelledby="operate-title">
      <div className="operator-heading">
        <div>
          <div className="eyebrow">
            <span className="eyebrow-line" /> OPERATOR CONTROL PLANE
          </div>
          <h2 id="operate-title">
            Turn proof
            <br />
            <em>into action.</em>
          </h2>
        </div>
        <p>Connect the authenticated Aegis API to create, evaluate, repair and consume intents. No write is attempted until the operator explicitly submits it.</p>
      </div>
      {!config && (
        <div className="operator-quickstart" aria-labelledby="quickstart-title">
          <div className="quickstart-header">
            <div className="eyebrow">
              <span className="eyebrow-line" /> HOW TO USE AEGIS
            </div>
            <h3 id="quickstart-title">
              From evidence to a<br />
              <em>one-time receipt.</em>
            </h3>
            <p>The proof record above is public and read-only. Use the authenticated control plane below when you need to operate a real intent.</p>
          </div>
          <ol className="quickstart-steps">
            <li>
              <span className="quickstart-number">01</span>
              <div>
                <strong>Connect the backend</strong>
                <p>
                  Choose <code>/api</code> for this deployment and enter the private bearer token issued by your backend operator.
                </p>
              </div>
            </li>
            <li>
              <span className="quickstart-number">02</span>
              <div>
                <strong>Register or select a policy</strong>
                <p>Use Policy for immutable allowlists, limits, approved sources, and the on-chain action hash.</p>
              </div>
            </li>
            <li>
              <span className="quickstart-number">03</span>
              <div>
                <strong>Create the intent</strong>
                <p>Bind the agent, action, recipient, payload, attestations, and—when using GenLayer—the target hash and expiry.</p>
              </div>
            </li>
            <li>
              <span className="quickstart-number">04</span>
              <div>
                <strong>Verify, repair, then consume</strong>
                <p>Verify a finalized GenLayer transaction, replace evidence only when repair is required, and consume the receipt once.</p>
              </div>
            </li>
          </ol>
          <button className="console-button console-button-primary quickstart-action" onClick={() => setShowSettings(true)}>
            <Settings2 size={15} /> Configure the control plane <ChevronRight size={15} />
          </button>
        </div>
      )}
      <div className="operator-shell">
        <div className="operator-toolbar">
          <div className="operator-status">
            <span className={`status-orb ${connection}`} />
            <div>
              <strong>{statusLabel}</strong>
              <small>{connectionMessage}</small>
            </div>
          </div>
          <div className="operator-toolbar-actions">
            <button className="console-button console-button-ghost" onClick={() => setShowSettings(true)}>
              <Settings2 size={15} /> {config ? 'Backend settings' : 'Connect backend'}
            </button>
            {config && (
              <button
                className="console-button console-button-ghost"
                onClick={() => {
                  setConfig(null)
                  setConnection('idle')
                  setConnectionMessage('Backend session cleared from memory.')
                }}
              >
                <LockKeyhole size={15} /> Clear session
              </button>
            )}
          </div>
        </div>
        {showSettings && (
          <div className="backend-settings">
            <div className="settings-title">
              <span>
                <CloudCog size={18} /> Backend access · step 2 of 2
              </span>
              <button onClick={() => setShowSettings(false)} aria-label="Close backend settings">
                ×
              </button>
            </div>
            <p>Use the API endpoint and private bearer token issued by the operator who runs your Aegis backend. Your wallet address is not a bearer token. The token stays in memory for this tab only and is never embedded in the build or stored in local storage.</p>
            <div className="settings-fields">
              <label>
                Backend URL
                <input value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)} placeholder="/api" />
              </label>
              <label>
                Bearer token
                <input value={backendToken} onChange={(event) => setBackendToken(event.target.value)} type="password" placeholder="Paste your private AEGIS_API_TOKEN" />
              </label>
            </div>
            <div className="settings-actions">
              <button className="console-button console-button-primary" onClick={() => void connectBackend()} disabled={connection === 'testing'}>
                {connection === 'testing' ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />} Test and connect
              </button>
              <span>
                <ShieldCheck size={14} /> Health + authenticated access are checked.
              </span>
              {onOpenSandbox && (
                <button className="console-button console-button-ghost" onClick={onOpenSandbox}>
                  Use public sandbox
                </button>
              )}
            </div>
          </div>
        )}
        {!config ? (
          <div className="operator-empty">
            <TerminalSquare size={23} />
            <div>
              <h3>Connect your control plane to operate.</h3>
              <p>The public proof record is already available. To create real intents, Aegis needs the private API token issued by your backend operator. No token is bundled into this public app.</p>
              <div className="operator-empty-actions">
                <button className="console-button console-button-primary" onClick={() => setShowSettings(true)}>
                  <KeyRound size={15} /> Connect backend
                </button>
                {onOpenSandbox && (
                  <button className="console-button console-button-ghost" onClick={onOpenSandbox}>
                    Try public sandbox
                  </button>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="console-grid">
            <aside className="console-sidebar">
              <div className="console-sidebar-label">CURRENT INTENT</div>
              <label className="intent-search">
                <span>Intent ID</span>
                <input value={intentId} onChange={(event) => setIntentId(event.target.value)} placeholder="64-character digest" />
                <button onClick={() => void refreshIntent()} disabled={busy || !intentId.trim()} aria-label="Refresh intent">
                  <RefreshCw size={15} className={busy ? 'spin' : ''} />
                </button>
              </label>
              <button className="console-button console-button-primary intent-refresh" onClick={() => void refreshIntent()} disabled={busy || !intentId.trim()}>
                <RefreshCw size={15} /> Refresh intent
              </button>
              {intent ? (
                <div className="intent-summary">
                  <span className={intentStatusClass(intent.state)}>{intent.state}</span>
                  <strong>{intent.action_type}</strong>
                  <small>
                    {intent.intent_id.slice(0, 12)}…{intent.intent_id.slice(-8)}
                  </small>
                  <dl>
                    <div>
                      <dt>REVISION</dt>
                      <dd>{intent.evidence_revision}</dd>
                    </div>
                    <div>
                      <dt>EXPIRES</dt>
                      <dd>{new Date(intent.expires_at * 1000).toLocaleString()}</dd>
                    </div>
                  </dl>
                </div>
              ) : (
                <div className="intent-summary-empty">
                  <FilePlus2 size={17} />
                  <span>Load an existing intent or create a new one.</span>
                </div>
              )}
            </aside>
            <div className="console-main">
              <div className="console-tabs" role="tablist" aria-label="Intent operations">
                {(['policy', 'create', 'genlayer', 'repair', 'consume'] as ConsoleTab[]).map((tab) => (
                  <button key={tab} className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)} role="tab" aria-selected={activeTab === tab}>
                    {tab === 'policy' ? 'Policy' : tab === 'create' ? 'Create' : tab === 'genlayer' ? 'GenLayer' : tab === 'repair' ? 'Repair' : 'Consume'}
                  </button>
                ))}
              </div>
              {operationError && (
                <div className="console-alert console-alert-error" role="alert">
                  <AlertCircle size={16} /> {operationError}
                </div>
              )}
              {operationMessage && (
                <div className="console-alert console-alert-success" role="status">
                  <Check size={16} /> {operationMessage}
                </div>
              )}
              {activeTab === 'policy' && (
                <form className="console-form" onSubmit={submitPolicy}>
                  <div className="form-intro">
                    <span>
                      <Settings2 size={18} /> Register policy
                    </span>
                    <small>Policies are immutable by version. Register the exact allowlists and limits your backend should enforce.</small>
                  </div>
                  <div className="form-grid">
                    {(
                      [
                        ['policy_id', 'Policy ID'],
                        ['version', 'Version'],
                        ['approved_agents', 'Approved agents (CSV)'],
                        ['allowed_action_types', 'Action types (CSV)'],
                        ['allowed_recipients', 'Recipients (CSV)'],
                        ['max_value', 'Maximum value'],
                        ['required_sources', 'Required sources (CSV)'],
                        ['minimum_attestations', 'Minimum attestations'],
                        ['maximum_age_seconds', 'Maximum evidence age (s)'],
                        ['intent_ttl_seconds', 'Intent TTL (s)'],
                        ['repair_window_seconds', 'Repair window (s)'],
                        ['onchain_action_hash', 'On-chain action hash (required for GenLayer)']
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <input
                          value={policyForm[key]}
                          onChange={(event) =>
                            setPolicyForm((current) => ({
                              ...current,
                              [key]: event.target.value
                            }))
                          }
                          required={key !== 'onchain_action_hash'}
                        />
                      </label>
                    ))}
                  </div>
                  <label>
                    Approved sources (JSON object)
                    <textarea
                      value={policyForm.approved_sources}
                      onChange={(event) =>
                        setPolicyForm((current) => ({
                          ...current,
                          approved_sources: event.target.value
                        }))
                      }
                      rows={5}
                      required
                    />
                  </label>
                  <button className="console-submit" type="submit" disabled={busy}>
                    {busy ? <LoaderCircle className="spin" size={16} /> : <Settings2 size={16} />} Register immutable policy <ChevronRight size={15} />
                  </button>
                </form>
              )}
              {activeTab === 'create' && (
                <form className="console-form" onSubmit={submitCreate}>
                  <div className="form-intro">
                    <span>
                      <FilePlus2 size={18} /> Create intent
                    </span>
                    <small>Requires a valid policy and provider-signed attestations.</small>
                  </div>
                  <div className="form-grid">
                    {(
                      [
                        ['intent_id', 'Intent ID'],
                        ['policy_id', 'Policy ID'],
                        ['policy_version', 'Policy version'],
                        ['agent', 'Agent'],
                        ['action_type', 'Action type'],
                        ['target', 'Target'],
                        ['recipient', 'Recipient'],
                        ['value', 'Value'],
                        ['payload_hash', 'Payload hash'],
                        ['genlayer_target_hash', 'GenLayer target hash (required for GenLayer)'],
                        ['genlayer_expires_at', 'GenLayer expiry (required for GenLayer)']
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <div className="input-with-action">
                          <input value={createForm[key]} onChange={(event) => updateCreate(key, event.target.value)} required={key !== 'genlayer_target_hash' && key !== 'genlayer_expires_at'} />
                          <>
                            {key === 'intent_id' && (
                              <button type="button" onClick={() => updateCreate('intent_id', newDigest())} aria-label="Generate new intent ID">
                                <RotateCcw size={14} />
                              </button>
                            )}
                          </>
                        </div>
                      </label>
                    ))}
                  </div>
                  <label>
                    Provider attestations (JSON array)
                    <textarea value={createForm.attestations} onChange={(event) => updateCreate('attestations', event.target.value)} rows={5} required placeholder='[{"provider_id":"...","resource":"https://..."}]' />
                  </label>
                  <button className="console-submit" type="submit" disabled={busy}>
                    {busy ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />} Create and persist intent <ChevronRight size={15} />
                  </button>
                </form>
              )}
              {activeTab === 'genlayer' && (
                <form className="console-form" onSubmit={submitGenLayer}>
                  <div className="form-intro">
                    <span>
                      <ShieldCheck size={18} /> Run the GenLayer lifecycle
                    </span>
                    <small>Aegis submits the exact firewall intent through your wallet, waits for Bradbury finality, then submits the bound gateway decision and verifies it server-side.</small>
                  </div>
                  <label>
                    Intent ID
                    <input value={intentId} onChange={(event) => setIntentId(event.target.value)} required />
                  </label>
                  <div className="console-alert console-alert-success" role="status">
                    <Check size={16} />
                    {intentSubmissionTxId ? `Intent finalized: ${intentSubmissionTxId}` : 'Step 1: submit the pending intent to the deployed Aegis firewall.'}
                  </div>
                  <button className="console-submit" type="button" onClick={() => void submitIntentToGenLayer()} disabled={busy || Boolean(intentSubmissionTxId)}>
                    {busy && !intentSubmissionTxId ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />} Submit intent to Bradbury <ChevronRight size={15} />
                  </button>
                  <div className="decision-options" role="radiogroup" aria-label="Expected GenLayer decision">
                    <button type="button" className={consensus === 'AUTHORIZE' ? 'selected authorize' : ''} onClick={() => setConsensus('AUTHORIZE')}>
                      <CircleCheck size={18} /> Authorize
                    </button>
                    <button type="button" className={consensus === 'DENY' ? 'selected deny' : ''} onClick={() => setConsensus('DENY')}>
                      <CircleX size={18} /> Deny
                    </button>
                  </div>
                  <button className="console-submit" type="button" onClick={() => void runGenLayerDecision()} disabled={busy || !intentSubmissionTxId}>
                    {busy && intentSubmissionTxId ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Run consensus and verify <ChevronRight size={15} />
                  </button>
                  <div className="field-help">The wallet signs both contract writes. The backend accepts the decision only after exact calldata, finalized execution, trace output, and firewall state all match.</div>
                  <details>
                    <summary>Recover an existing finalized decision</summary>
                    <label>
                      Finalized GenLayer transaction ID
                      <input value={genlayerTxId} onChange={(event) => setGenLayerTxId(event.target.value)} placeholder="0x + 64 hex characters" autoComplete="off" spellCheck={false} inputMode="text" aria-describedby="genlayer-tx-help" />
                      <small id="genlayer-tx-help" className="field-help">
                        Recovery only: paste the finalized gateway decision hash from the GenLayer explorer, not the Aegis intent ID.
                      </small>
                    </label>
                    <button className="console-submit" type="submit" disabled={busy}>
                      {busy ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Verify existing decision <ChevronRight size={15} />
                    </button>
                  </details>
                </form>
              )}
              {activeTab === 'repair' && (
                <form className="console-form" onSubmit={submitRepair}>
                  <div className="form-intro">
                    <span>
                      <RefreshCw size={18} /> Replace evidence
                    </span>
                    <small>Only valid during REPAIR_REQUIRED and only for the bound agent.</small>
                  </div>
                  <label>
                    Intent ID
                    <input value={intentId} onChange={(event) => setIntentId(event.target.value)} required />
                  </label>
                  <label>
                    Caller identity
                    <input value={caller} onChange={(event) => setCaller(event.target.value)} required />
                  </label>
                  <label>
                    Replacement attestations (JSON array)
                    <textarea value={repairAttestations} onChange={(event) => setRepairAttestations(event.target.value)} rows={7} required placeholder='[{"provider_id":"...","signature":"..."}]' />
                  </label>
                  <button className="console-submit" type="submit" disabled={busy}>
                    {busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Replace evidence <ChevronRight size={15} />
                  </button>
                </form>
              )}
              {activeTab === 'consume' && (
                <form className="console-form" onSubmit={submitConsume}>
                  <div className="form-intro">
                    <span>
                      <LockKeyhole size={18} /> Consume receipt
                    </span>
                    <small>One-time operation. Wrong consumer, digest or replay is rejected.</small>
                  </div>
                  <label>
                    Receipt ID
                    <input value={receiptId || intent?.receipt_id || ''} onChange={(event) => setReceiptId(event.target.value)} required />
                  </label>
                  <label>
                    Consumer
                    <input value={consumer || intent?.recipient || ''} onChange={(event) => setConsumer(event.target.value)} required />
                  </label>
                  <label>
                    Action-intent digest
                    <input value={actionIntent || intent?.action_intent || ''} onChange={(event) => setActionIntent(event.target.value)} required />
                  </label>
                  <button className="console-submit" type="submit" disabled={busy}>
                    {busy ? <LoaderCircle className="spin" size={16} /> : <LockKeyhole size={16} />} Consume once <ChevronRight size={15} />
                  </button>
                </form>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
