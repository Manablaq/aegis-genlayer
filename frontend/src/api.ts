export interface BackendConfig {
  baseUrl: string
  token: string
}

export interface IntentRecord {
  intent_id: string
  policy_id: string
  policy_version: number
  agent: string
  action_type: string
  target: string
  recipient: string
  value: number
  payload_hash: string
  created_at: number
  expires_at: number
  repair_deadline: number
  action_subject: string
  action_intent: string
  evidence_revision: number
  state: string
  reason: string
  attestations: Array<Record<string, unknown>>
  receipt_id: string | null
}

export class BackendApiError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code)
    this.name = 'BackendApiError'
  }
}

function endpoint(config: BackendConfig, path: string): string {
  const base = config.baseUrl.trim().replace(/\/$/, '')
  if (!base) throw new Error('BACKEND_URL_REQUIRED')
  return `${base}${path}`
}

async function requestJson<T>(config: BackendConfig, path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  if (authenticated) {
    if (!config.token.trim()) throw new Error('BACKEND_TOKEN_REQUIRED')
    headers.set('Authorization', `Bearer ${config.token.trim()}`)
  }

  let response: Response
  try {
    response = await fetch(endpoint(config, path), { ...init, headers, cache: 'no-store' })
  } catch {
    throw new Error('BACKEND_UNREACHABLE')
  }

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const code = typeof payload === 'object' && payload !== null && 'error' in payload && typeof payload.error === 'string'
      ? payload.error
      : `HTTP_${response.status}`
    throw new BackendApiError(response.status, code)
  }
  return payload as T
}

export async function testConnection(config: BackendConfig): Promise<void> {
  await requestJson<{ ok: boolean }>(config, '/health', {}, false)
  try {
    await requestJson<IntentRecord>(config, `/v1/intents/${'0'.repeat(64)}`)
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) return
    throw error
  }
}

export function checkHealth(config: BackendConfig): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(config, '/health', {}, false)
}

export function getIntent(config: BackendConfig, intentId: string): Promise<IntentRecord> {
  return requestJson<IntentRecord>(config, `/v1/intents/${encodeURIComponent(intentId)}`)
}

export function createIntent(config: BackendConfig, body: Record<string, unknown>): Promise<IntentRecord> {
  return requestJson<IntentRecord>(config, '/v1/intents', { method: 'POST', body: JSON.stringify(body) })
}

export function registerPolicy(config: BackendConfig, body: Record<string, unknown>): Promise<{ status: string }> {
  return requestJson<{ status: string }>(config, '/v1/policies', { method: 'POST', body: JSON.stringify(body) })
}

export function evaluateWithGenLayer(config: BackendConfig, intentId: string, genlayerTxId: string, decision: 'AUTHORIZE' | 'DENY'): Promise<IntentRecord> {
  return requestJson<IntentRecord>(config, `/v1/intents/${encodeURIComponent(intentId)}/evaluate-genlayer`, {
    method: 'POST',
    body: JSON.stringify({ genlayer_tx_id: genlayerTxId, decision }),
  })
}

export function replaceEvidence(config: BackendConfig, intentId: string, caller: string, attestations: unknown[]): Promise<IntentRecord> {
  return requestJson<IntentRecord>(config, `/v1/intents/${encodeURIComponent(intentId)}/replace-evidence`, {
    method: 'POST',
    body: JSON.stringify({ caller, attestations }),
  })
}

export function consumeReceipt(config: BackendConfig, receiptId: string, consumer: string, actionIntent: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(config, '/v1/receipts/consume', {
    method: 'POST',
    body: JSON.stringify({ receipt_id: receiptId, consumer, action_intent: actionIntent }),
  })
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof BackendApiError) {
    if (error.status === 401) return 'The backend rejected the bearer token.'
    if (error.status === 404) return 'The requested intent does not exist.'
    return `Backend rejected the operation: ${error.code}`
  }
  if (error instanceof Error) {
    if (error.message === 'BACKEND_UNREACHABLE') return 'The backend could not be reached. Check its URL and CORS policy.'
    if (error.message === 'BACKEND_TOKEN_REQUIRED') return 'Enter the backend bearer token before connecting.'
    if (error.message === 'BACKEND_URL_REQUIRED') return 'Enter the backend URL before connecting.'
    return error.message
  }
  return 'The backend operation failed.'
}
