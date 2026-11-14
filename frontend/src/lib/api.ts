const API_URL = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '')

export type ConversationDraft = { id: string; startedAt: string; answers: string[] }
export type ChatTurn = { id: string; sequence: number; content: string; clarification: string }
export type Conversation = ConversationDraft & {
  fields: string[]
  prompts: string[]
  turns: ChatTurn[]
  revision: number
  agentEnabled: boolean
  applicationId?: string | null
}
export type ChatMessage = Omit<ChatTurn, 'clarification'> & { revision: number }

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}
export type OnboardingDocument = {
  id: string
  filename: string
  contentType: string
  sizeBytes: number
  createdAt: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path.startsWith('/conversations') ? actorPath(path, 'customer') : path}`, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, typeof body?.detail === 'string'
      ? body.detail
      : `Request failed with status ${response.status}.`)
  }
  return response.json() as Promise<T>
}

export async function login(): Promise<boolean> {
  const result: unknown = await request('/login', { method: 'POST' })
  if (result !== true) throw new Error('Login was not successful. Please try again.')
  return result
}

export function listConversations(): Promise<Conversation[]> {
  return request('/conversations')
}

export function createConversation(conversation: ConversationDraft): Promise<Conversation> {
  return request('/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(conversation),
  })
}

export function discardConversation(id: string): Promise<{ deleted: boolean }> {
  return request(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function sendChatMessage(id: string, message: ChatMessage): Promise<Conversation> {
  return request(`/conversations/${encodeURIComponent(id)}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(message),
  })
}

export function listDocuments(conversationId: string): Promise<OnboardingDocument[]> {
  return request(`/conversations/${encodeURIComponent(conversationId)}/documents`)
}

export function uploadDocument(
  conversationId: string,
  file: File,
): Promise<OnboardingDocument> {
  const form = new FormData()
  form.append('file', file)
  return request(`/conversations/${encodeURIComponent(conversationId)}/documents`, {
    method: 'POST',
    body: form,
  })
}

export function removeDocument(
  conversationId: string,
  documentId: string,
): Promise<{ deleted: boolean }> {
  return request(
    `/conversations/${encodeURIComponent(conversationId)}/documents/${encodeURIComponent(documentId)}`,
    { method: 'DELETE' },
  )
}

export async function downloadDocument(documentId: string): Promise<Blob> {
  const response = await fetch(`${API_URL}${actorPath(`/documents/${encodeURIComponent(documentId)}/download`, 'customer')}`)
  if (!response.ok) throw new Error(`Request failed with status ${response.status}.`)
  return response.blob()
}

export type Persona = { id: string; name: string; role: 'customer' | 'admin'; customerId: string | null }
export type Application = { businessName: string; businessActivity: string; registration: string; owners: string; products: string; sector: string }
export type Case = {
  signedWorkflow?: boolean; agreementSigned?: boolean; rejected?: boolean
  id: string; status: string; stage: number; revision: number; currentStep: string; completed: number
  steps: string[]; application: Application; submittedAt: string; requiredDocuments: string[]
  requestedInformation: string; estimatedMinutes: number | null; estimatedCompletion: string | null
  informationResponses: { request: string; response: string; createdAt: string }[]
  contact: { name: string; email: string; phone: string }; riskTier?: string
}
export type Citation = { id: string; citation: string; url?: string | null }
export type Risk = {
  source?: string; sources?: Citation[]
  tier: 'low' | 'medium' | 'high'; rationale: string; evidence: string[]; missingInputs: string[]
  ownership: number; activity: number; geography: number; policyVersion?: number
}
export type CaseDocument = OnboardingDocument & { source: string; coverNote?: string | null; pricing?: { version: string; currency: string; products: { name: string; terms: string[] }[] } | null }
export type CaseDetail = Case & {
  verification?: { retrieval?: string; findings: string[]; missingInputs: string[]; sources: Citation[] };
  risk: Risk | null; documents: CaseDocument[]; checkpoint: { step: string; revision: number }
  history: { action: string; from: string | null; to: string; role: string; reason: string; created_at: string }[]
  actions: { id: string; target: string; state: string; reference?: string; evidence?: string }[]
}
export type Account = { accountReference: string; status: string; products: string[]; benefits: string[]; access: string }
export type Guardrail = { key: string; activeVersion: number; versions: { version: number; rule: string }[] }
export type Proposal = { id: string; rule: string; reason: string; status: string; override: { reason: string; caseId: string }; decisionReason?: string }

export function listPersonas() { return request<Persona[]>('/demo/users') }

function activePersona(): Persona | null {
  try {
    return JSON.parse(sessionStorage.getItem('customer360-persona') || 'null') as Persona | null
  } catch {
    return null
  }
}

export function getPersona() { return activePersona() }

function actorPath(path: string, role: Persona['role']) {
  const actor = activePersona()
  const params = new URLSearchParams()
  const id = role === 'admin' ? actor?.id : actor?.customerId
  if (id) params.set(`${role}_id`, id)
  return params.size ? `${path}${path.includes('?') ? '&' : '?'}${params}` : path
}

const customerCases = '/customer/onboardings'
const adminCases = '/admin/onboardings'

function jsonPost(data: object): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }
}

export const customerApi = {
  list: () => request<Case[]>(actorPath(customerCases, 'customer')),
  detail: (id: string) => request<Case>(actorPath(`${customerCases}/${id}`, 'customer')),
  submit: (data: Application & { id: string; conversationId?: string }) =>
    request<Case>(actorPath(customerCases, 'customer'), jsonPost(data)),
  information: (id: string, response: string) =>
    request<Case>(actorPath(`${customerCases}/${id}/information`, 'customer'), jsonPost({ response })),
  sign: (id: string, signer: string) =>
    request<Case>(actorPath(`${customerCases}/${id}/sign`, 'customer'), jsonPost({ signer })),
  returnAgreement: (id: string) =>
    request<Case>(actorPath(`${customerCases}/${id}/return-agreement`, 'customer'), { method: 'POST' }),
  documents: (id: string) => request<CaseDocument[]>(actorPath(`${customerCases}/${id}/documents`, 'customer')),
  upload(id: string, file: File) {
    const body = new FormData()
    body.append('file', file)
    return request<CaseDocument>(actorPath(`${customerCases}/${id}/documents`, 'customer'), { method: 'POST', body })
  },
  summary: (id: string) => request<Account>(actorPath(`${customerCases}/${id}/summary`, 'customer')),
}

export const adminApi = {
  list: (filters: URLSearchParams) => request<Case[]>(actorPath(`${adminCases}?${filters}`, 'admin')),
  queue: () => request<Case[]>(actorPath('/admin/reviews', 'admin')),
  detail: (id: string) => request<CaseDetail>(actorPath(`${adminCases}/${id}`, 'admin')),
  review: (id: string, decision: string, revision: number, comments: string, risk?: Risk) =>
    request<Case>(actorPath(`${adminCases}/${id}/review`, 'admin'), jsonPost({ decision, revision, comments, risk })),
  retry: (id: string) => request<Case>(actorPath(`/admin/workflow/runs/${id}/retry`, 'admin'), { method: 'POST' }),
  guardrails: () => request<Guardrail[]>(actorPath('/admin/guardrails', 'admin')),
  proposals: () => request<Proposal[]>(actorPath('/admin/guardrail-proposals', 'admin')),
  propose: (onboardingId: string, rule: string, reason: string) =>
    request(actorPath('/admin/guardrail-proposals', 'admin'), jsonPost({ onboardingId, rule, reason })),
  decide: (id: string, decision: string, comments: string) =>
    request(actorPath(`/admin/guardrail-proposals/${id}/decision`, 'admin'), jsonPost({ decision, comments })),
}

export async function downloadCaseDocument(role: Persona['role'], id: string, document: CaseDocument) {
  const path = role === 'admin' ? adminCases : customerCases
  const result = await fetch(`${API_URL}${actorPath(`${path}/${id}/documents/${document.id}`, role)}`)
  if (!result.ok) throw new ApiError(result.status, 'Unable to download the document.')
  const url = URL.createObjectURL(await result.blob())
  const link = window.document.createElement('a')
  link.href = url
  link.download = document.filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
