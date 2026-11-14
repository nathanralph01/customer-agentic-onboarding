const API_URL = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '')

export type Conversation = { id: string; startedAt: string; answers: string[] }
export type OnboardingDocument = {
  id: string
  filename: string
  contentType: string
  sizeBytes: number
  createdAt: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init)
  if (!response.ok) throw new Error(`Request failed with status ${response.status}.`)
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

export function createConversation(conversation: Conversation): Promise<Conversation> {
  return request('/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(conversation),
  })
}

export function saveConversationAnswer(
  id: string,
  sequence: number,
  content: string,
): Promise<Conversation> {
  return request(`/conversations/${encodeURIComponent(id)}/answers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sequence, content }),
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
  const response = await fetch(`${API_URL}/documents/${encodeURIComponent(documentId)}/download`)
  if (!response.ok) throw new Error(`Request failed with status ${response.status}.`)
  return response.blob()
}
