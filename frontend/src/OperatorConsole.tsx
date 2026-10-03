import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import {
  AlertCircle,
  Check,
  ChevronRight,
  CircleCheck,
  CircleX,
  CloudCog,
  Copy,
  FilePlus2,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  Send,
  Settings2,
  ShieldCheck,
  TerminalSquare,
} from 'lucide-react'
import {
  apiErrorMessage,
  consumeReceipt,
  createIntent,
  evaluateIntent,
  getIntent,
  registerPolicy,
  replaceEvidence,
  testConnection,
} from './api'
import type { BackendConfig, IntentRecord } from './api'

type ConsoleTab = 'policy' | 'create' | 'evaluate' | 'repair' | 'consume'

const defaultUrl = import.meta.env.VITE_AEGIS_API_URL || 'http://127.0.0.1:8081'

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

function intentStatusClass(state: string | undefined): string {
  return `intent-state state-${(state || 'UNKNOWN').toLowerCase()}`
}

export default function OperatorConsole({ walletAccount }: { walletAccount: string | null }) {
  const [backendUrl, setBackendUrl] = useState(defaultUrl)
  const [backendToken, setBackendToken] = useState('')
  const [config, setConfig] = useState<BackendConfig | null>(null)
  const [connection, setConnection] = useState<'idle' | 'testing' | 'connected' | 'error'>('idle')
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
  })
  const [caller, setCaller] = useState(walletAccount || 'agent-1')
  const [repairAttestations, setRepairAttestations] = useState('[]')
  const [consensus, setConsensus] = useState<'AUTHORIZE' | 'DENY'>('AUTHORIZE')
  const [receiptId, setReceiptId] = useState('')
  const [consumer, setConsumer] = useState('')
  const [actionIntent, setActionIntent] = useState('')

  const statusLabel = useMemo(() => {
    if (connection === 'testing') return 'TESTING CONNECTION'
    if (connection === 'connected') return 'BACKEND CONNECTED'
    if (connection === 'error') return 'BACKEND ERROR'
    return 'BACKEND NOT CONNECTED'
  }, [connection])

  const connectBackend = async () => {
    setConnection('testing')
    setConnectionMessage('Checking health and authenticated access…')
    setOperationError('')
    try {
      const nextConfig = { baseUrl: backendUrl.trim(), token: backendToken }
      await testConnection(nextConfig)
      setConfig(nextConfig)
      setConnection('connected')
      setConnectionMessage('Authenticated backend session is active. The bearer token remains in memory only.')
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
      const created = await createIntent(config!, {
        ...createForm,
        policy_version: Number(createForm.policy_version),
        value: Number(createForm.value),
        attestations: parseAttestations(createForm.attestations),
      })
      setIntent(created)
      setIntentId(created.intent_id)
      setReceiptId(created.receipt_id || '')
      setConsumer(created.recipient)
      setActionIntent(created.action_intent)
      setActiveTab('evaluate')
      setOperationMessage('Intent created and persisted. Review it before evaluation.')
    })
  }

  const submitEvaluate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const next = await evaluateIntent(config!, intentId.trim(), consensus)
      setIntent(next)
      setReceiptId(next.receipt_id || '')
      setConsumer(next.recipient)
      setActionIntent(next.action_intent)
      setOperationMessage(`Evaluation returned ${next.state}.`)
    })
  }

  const submitPolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const sources: unknown = JSON.parse(policyForm.approved_sources)
      if (!sources || typeof sources !== 'object' || Array.isArray(sources)) throw new Error('Approved sources must be a JSON object.')
      const registered = await registerPolicy(config!, {
        policy_id: policyForm.policy_id.trim(),
        version: Number(policyForm.version),
        approved_agents: policyForm.approved_agents.split(',').map((value) => value.trim()).filter(Boolean),
        allowed_action_types: policyForm.allowed_action_types.split(',').map((value) => value.trim()).filter(Boolean),
        allowed_recipients: policyForm.allowed_recipients.split(',').map((value) => value.trim()).filter(Boolean),
        approved_sources: sources,
        max_value: Number(policyForm.max_value),
        required_sources: policyForm.required_sources.split(',').map((value) => value.trim()).filter(Boolean),
        minimum_attestations: Number(policyForm.minimum_attestations),
        maximum_age_seconds: Number(policyForm.maximum_age_seconds),
        intent_ttl_seconds: Number(policyForm.intent_ttl_seconds),
        repair_window_seconds: Number(policyForm.repair_window_seconds),
      })
      setOperationMessage(`Policy ${policyForm.policy_id}:${policyForm.version} ${registered.status.toLowerCase()}.`)
      setActiveTab('create')
    })
  }

  const submitRepair = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const next = await replaceEvidence(config!, intentId.trim(), caller.trim(), parseAttestations(repairAttestations))
      setIntent(next)
      setOperationMessage(`Evidence revision ${next.evidence_revision} persisted.`)
    })
  }

  const submitConsume = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    await runOperation(async () => {
      const receipt = await consumeReceipt(config!, receiptId.trim(), consumer.trim(), actionIntent.trim())
      const next = config ? await getIntent(config, intentId.trim()) : null
      if (next) setIntent(next)
      setOperationMessage(`Receipt ${typeof receipt.receipt_id === 'string' ? receipt.receipt_id.slice(0, 12) : ''}… consumed once.`)
    })
  }

  const updateCreate = (key: keyof typeof createForm, value: string) => setCreateForm((current) => ({ ...current, [key]: value }))

  return <section className="operator-section section-shell" id="operate" aria-labelledby="operate-title">
    <div className="operator-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> OPERATOR CONTROL PLANE</div><h2 id="operate-title">Turn proof<br /><em>into action.</em></h2></div><p>Connect the authenticated Aegis API to create, evaluate, repair and consume intents. No write is attempted until the operator explicitly submits it.</p></div>
    <div className="operator-shell">
      <div className="operator-toolbar"><div className="operator-status"><span className={`status-orb ${connection}`} /><div><strong>{statusLabel}</strong><small>{connectionMessage}</small></div></div><div className="operator-toolbar-actions"><button className="console-button console-button-ghost" onClick={() => setShowSettings(true)}><Settings2 size={15} /> {config ? 'Backend settings' : 'Connect backend'}</button>{config && <button className="console-button console-button-ghost" onClick={() => { setConfig(null); setConnection('idle'); setConnectionMessage('Backend session cleared from memory.') }}><LockKeyhole size={15} /> Clear session</button>}</div></div>
      {showSettings && <div className="backend-settings"><div className="settings-title"><span><CloudCog size={18} /> Backend access</span><button onClick={() => setShowSettings(false)} aria-label="Close backend settings">×</button></div><p>Enter a private API endpoint and bearer token. The token is held in memory for this tab only and is never embedded in the build or stored in local storage.</p><div className="settings-fields"><label>Backend URL<input value={backendUrl} onChange={(event) => setBackendUrl(event.target.value)} placeholder="https://api.example.com" /></label><label>Bearer token<input value={backendToken} onChange={(event) => setBackendToken(event.target.value)} type="password" placeholder="AEGIS_API_TOKEN" /></label></div><div className="settings-actions"><button className="console-button console-button-primary" onClick={() => void connectBackend()} disabled={connection === 'testing'}>{connection === 'testing' ? <LoaderCircle className="spin" size={15} /> : <KeyRound size={15} />} Test and connect</button><span><ShieldCheck size={14} /> Health + authenticated access are checked.</span></div></div>}
      {!config ? <div className="operator-empty"><TerminalSquare size={23} /><div><h3>Control plane is not connected.</h3><p>The public proof surface remains read-only until you connect your own authenticated backend. This is intentional: no bearer token is bundled into the Vercel frontend.</p><button className="text-link" onClick={() => setShowSettings(true)}>Configure the control plane <ChevronRight size={15} /></button></div></div> : <div className="console-grid"><aside className="console-sidebar"><div className="console-sidebar-label">CURRENT INTENT</div><label className="intent-search"><span>Intent ID</span><input value={intentId} onChange={(event) => setIntentId(event.target.value)} placeholder="64-character digest" /><button onClick={() => void refreshIntent()} disabled={busy || !intentId.trim()} aria-label="Refresh intent"><RefreshCw size={15} className={busy ? 'spin' : ''} /></button></label><button className="console-button console-button-primary intent-refresh" onClick={() => void refreshIntent()} disabled={busy || !intentId.trim()}><RefreshCw size={15} /> Refresh intent</button>{intent ? <div className="intent-summary"><span className={intentStatusClass(intent.state)}>{intent.state}</span><strong>{intent.action_type}</strong><small>{intent.intent_id.slice(0, 12)}…{intent.intent_id.slice(-8)}</small><dl><div><dt>REVISION</dt><dd>{intent.evidence_revision}</dd></div><div><dt>EXPIRES</dt><dd>{new Date(intent.expires_at * 1000).toLocaleString()}</dd></div></dl></div> : <div className="intent-summary-empty"><FilePlus2 size={17} /><span>Load an existing intent or create a new one.</span></div>}</aside><div className="console-main"><div className="console-tabs" role="tablist" aria-label="Intent operations">{(['policy', 'create', 'evaluate', 'repair', 'consume'] as ConsoleTab[]).map((tab) => <button key={tab} className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)} role="tab" aria-selected={activeTab === tab}>{tab === 'policy' ? 'Policy' : tab === 'create' ? 'Create' : tab === 'evaluate' ? 'Evaluate' : tab === 'repair' ? 'Repair' : 'Consume'}</button>)}</div>{operationError && <div className="console-alert console-alert-error" role="alert"><AlertCircle size={16} /> {operationError}</div>}{operationMessage && <div className="console-alert console-alert-success" role="status"><Check size={16} /> {operationMessage}</div>}{activeTab === 'policy' && <form className="console-form" onSubmit={submitPolicy}><div className="form-intro"><span><Settings2 size={18} /> Register policy</span><small>Policies are immutable by version. Register the exact allowlists and limits your backend should enforce.</small></div><div className="form-grid">{([['policy_id', 'Policy ID'], ['version', 'Version'], ['approved_agents', 'Approved agents (CSV)'], ['allowed_action_types', 'Action types (CSV)'], ['allowed_recipients', 'Recipients (CSV)'], ['max_value', 'Maximum value'], ['required_sources', 'Required sources (CSV)'], ['minimum_attestations', 'Minimum attestations'], ['maximum_age_seconds', 'Maximum evidence age (s)'], ['intent_ttl_seconds', 'Intent TTL (s)'], ['repair_window_seconds', 'Repair window (s)']] as const).map(([key, label]) => <label key={key}>{label}<input value={policyForm[key]} onChange={(event) => setPolicyForm((current) => ({ ...current, [key]: event.target.value }))} required /></label>)}</div><label>Approved sources (JSON object)<textarea value={policyForm.approved_sources} onChange={(event) => setPolicyForm((current) => ({ ...current, approved_sources: event.target.value }))} rows={5} required /></label><button className="console-submit" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Settings2 size={16} />} Register immutable policy <ChevronRight size={15} /></button></form>}{activeTab === 'create' && <form className="console-form" onSubmit={submitCreate}><div className="form-intro"><span><FilePlus2 size={18} /> Create intent</span><small>Requires a valid policy and provider-signed attestations.</small></div><div className="form-grid">{([['intent_id', 'Intent ID'], ['policy_id', 'Policy ID'], ['policy_version', 'Policy version'], ['agent', 'Agent'], ['action_type', 'Action type'], ['target', 'Target'], ['recipient', 'Recipient'], ['value', 'Value'], ['payload_hash', 'Payload hash']] as const).map(([key, label]) => <label key={key}>{label}<div className="input-with-action"><input value={createForm[key]} onChange={(event) => updateCreate(key, event.target.value)} required /><>{key === 'intent_id' && <button type="button" onClick={() => updateCreate('intent_id', newDigest())} aria-label="Generate new intent ID"><RotateCcw size={14} /></button>}</></div></label>)}</div><label>Provider attestations (JSON array)<textarea value={createForm.attestations} onChange={(event) => updateCreate('attestations', event.target.value)} rows={5} required placeholder='[{"provider_id":"...","resource":"https://..."}]' /></label><button className="console-submit" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />} Create and persist intent <ChevronRight size={15} /></button></form>}{activeTab === 'evaluate' && <form className="console-form" onSubmit={submitEvaluate}><div className="form-intro"><span><ShieldCheck size={18} /> Evaluate intent</span><small>Submit the consensus decision returned by your authorized decision path.</small></div><label>Intent ID<input value={intentId} onChange={(event) => setIntentId(event.target.value)} required /></label><div className="decision-options" role="radiogroup" aria-label="Consensus decision"><button type="button" className={consensus === 'AUTHORIZE' ? 'selected authorize' : ''} onClick={() => setConsensus('AUTHORIZE')}><CircleCheck size={18} /> Authorize</button><button type="button" className={consensus === 'DENY' ? 'selected deny' : ''} onClick={() => setConsensus('DENY')}><CircleX size={18} /> Deny</button></div><button className="console-submit" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <ShieldCheck size={16} />} Submit evaluation <ChevronRight size={15} /></button></form>}{activeTab === 'repair' && <form className="console-form" onSubmit={submitRepair}><div className="form-intro"><span><RefreshCw size={18} /> Replace evidence</span><small>Only valid during REPAIR_REQUIRED and only for the bound agent.</small></div><label>Intent ID<input value={intentId} onChange={(event) => setIntentId(event.target.value)} required /></label><label>Caller identity<input value={caller} onChange={(event) => setCaller(event.target.value)} required /></label><label>Replacement attestations (JSON array)<textarea value={repairAttestations} onChange={(event) => setRepairAttestations(event.target.value)} rows={7} required placeholder='[{"provider_id":"...","signature":"..."}]' /></label><button className="console-submit" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Replace evidence <ChevronRight size={15} /></button></form>}{activeTab === 'consume' && <form className="console-form" onSubmit={submitConsume}><div className="form-intro"><span><LockKeyhole size={18} /> Consume receipt</span><small>One-time operation. Wrong consumer, digest or replay is rejected.</small></div><label>Receipt ID<input value={receiptId || intent?.receipt_id || ''} onChange={(event) => setReceiptId(event.target.value)} required /></label><label>Consumer<input value={consumer || intent?.recipient || ''} onChange={(event) => setConsumer(event.target.value)} required /></label><label>Action-intent digest<input value={actionIntent || intent?.action_intent || ''} onChange={(event) => setActionIntent(event.target.value)} required /></label><button className="console-submit" type="submit" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <LockKeyhole size={16} />} Consume once <ChevronRight size={15} /></button></form>}</div></div>}
    </div>
  </section>
}
