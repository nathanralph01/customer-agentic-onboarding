import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowLeft, Bot, Check, Download, History, MessageSquare, Plus, Send, FileText, Upload, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import CustomerLayout from '@/components/CustomerLayout'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  createConversation,
  downloadDocument,
  listConversations,
  listDocuments,
  ApiError,
  sendChatMessage,
  removeDocument as deleteDocument,
  uploadDocument,
  type ChatMessage,
  type Conversation,
  type ConversationDraft,
  type OnboardingDocument,
} from '@/lib/api'

type Tab = 'chat' | 'info' | 'history'
const STORAGE_KEY = 'customer360-onboarding-conversations'

function newConversation(): ConversationDraft {
  return { id: crypto.randomUUID(), startedAt: new Date().toISOString(), answers: [] }
}

function loadConversations(): ConversationDraft[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')
    if (Array.isArray(saved)) return saved.filter((item): item is ConversationDraft =>
      item && typeof item.id === 'string' && typeof item.startedAt === 'string' &&
      !Number.isNaN(Date.parse(item.startedAt)) &&
      Array.isArray(item.answers) && item.answers.length <= 5 &&
      item.answers.every((answer: unknown) => typeof answer === 'string'))
  } catch { /* Start a fresh demo if tab storage is unavailable or invalid. */ }
  return []
}

export default function OnboardingPage({ onLogout }: { onLogout: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('chat')
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [apiError, setApiError] = useState('')
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [documents, setDocuments] = useState<Record<string, OnboardingDocument[]>>({})
  const [documentBusy, setDocumentBusy] = useState(false)
  const [documentError, setDocumentError] = useState('')
  const [documentLoadAttempt, setDocumentLoadAttempt] = useState(0)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const initialConversation = useRef<ConversationDraft | null>(null)
  const pendingMessage = useRef<{ conversationId: string; message: ChatMessage } | null>(null)
  const active = conversations.find(item => item.id === activeId) || conversations[0]

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setApiError('')
      try {
        let saved = await listConversations()
        if (!saved.length) {
          const legacy = loadConversations()
          if (legacy.length) {
            saved = await Promise.all(legacy.map(conversation => createConversation(conversation)))
            sessionStorage.removeItem(STORAGE_KEY)
          }
        }
        let ongoing = saved.find(item => !item.applicationId && item.answers.length < item.fields.length)
        if (!ongoing && !cancelled) {
          initialConversation.current ??= newConversation()
          ongoing = await createConversation(initialConversation.current)
          saved = [ongoing, ...saved.filter(item => item.id !== ongoing?.id)]
        }
        if (!cancelled) {
          setConversations(saved)
          setActiveId(ongoing?.id ?? null)
        }
      } catch (error) {
        if (!cancelled) {
          setApiError(error instanceof Error ? error.message : 'Unable to load onboarding from Atlas.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => { cancelled = true }
  }, [loadAttempt])

  const documentConversationId = tab === 'info' ? active?.id : undefined
  const documentsLoaded = documentConversationId !== undefined && documents[documentConversationId] !== undefined

  useEffect(() => {
    if (!documentConversationId || documentsLoaded) return
    let cancelled = false
    listDocuments(documentConversationId).then(items => {
      if (!cancelled) setDocuments(current => ({ ...current, [documentConversationId]: items }))
    }).catch(error => {
      if (!cancelled) setDocumentError(error instanceof Error ? error.message : 'Unable to load documents.')
    })
    return () => { cancelled = true }
  }, [documentConversationId, documentsLoaded, documentLoadAttempt])

  const activeDocuments = active ? documents[active.id] || [] : []
  const complete = active && active.answers.length === active.fields.length

  useEffect(() => {
    const log = logRef.current
    if (log && tab === 'chat' && activeId !== null) log.scrollTop = log.scrollHeight
  }, [active?.revision, activeId, tab])

  async function send(event?: FormEvent) {
    event?.preventDefault()
    if (!active || !draft.trim() || active.applicationId || complete || saving) return
    const content = draft.trim()
    const pending = pendingMessage.current
    const message = pending?.conversationId === active.id && pending.message.content === content
      ? pending.message
      : { id: crypto.randomUUID(), revision: active.revision, sequence: active.answers.length, content }
    pendingMessage.current = { conversationId: active.id, message }
    setSaving(true)
    setApiError('')
    try {
      const saved = await sendChatMessage(active.id, message)
      setConversations(current => current.map(item => item.id === saved.id ? saved : item))
      pendingMessage.current = null
      setDraft('')
      inputRef.current?.focus()
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Unable to send your message.')
      if (error instanceof ApiError && error.status === 409) {
        pendingMessage.current = null
        try {
          const latest = (await listConversations()).find(item => item.id === active.id)
          if (latest) setConversations(current => current.map(item => item.id === latest.id ? latest : item))
        } catch {
          setApiError('Unable to reload the conversation. Refresh the page and try again.')
        }
      }
    } finally {
      setSaving(false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  async function startNew() {
    const next = newConversation()
    setSaving(true)
    setApiError('')
    try {
      const saved = await createConversation(next)
      setConversations(current => [saved, ...current])
      setActiveId(saved.id)
      setDocumentError('')
      setDraft('')
      setTab('chat')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Unable to create a conversation in Atlas.')
    } finally {
      setSaving(false)
    }
  }

  async function addDocuments(files: FileList | null) {
    if (!files || !active || !documentsLoaded || documentBusy) return
    const accepted: File[] = []
    const errors: string[] = []
    for (const file of Array.from(files)) {
      if (!/\.(pdf|docx|txt|csv|png|jpe?g)$/i.test(file.name)) {
        errors.push(`${file.name}: unsupported file type.`)
      } else if (file.size === 0 || file.size > 10 * 1024 * 1024) {
        errors.push(`${file.name}: choose a non-empty file up to 10 MB.`)
      } else if (
        activeDocuments.some(item => item.filename === file.name && item.sizeBytes === file.size) ||
        accepted.some(item => item.name === file.name && item.size === file.size)
      ) {
        errors.push(`${file.name}: already attached.`)
      } else if (activeDocuments.length + accepted.length >= 10) {
        errors.push('You can attach up to 10 documents per conversation.')
        break
      } else {
        accepted.push(file)
      }
    }
    const conversationId = active.id
    setDocumentBusy(true)
    for (const file of accepted) {
      try {
        const saved = await uploadDocument(conversationId, file)
        setDocuments(current => ({
          ...current,
          [conversationId]: [...(current[conversationId] || []), saved],
        }))
      } catch (error) {
        errors.push(`${file.name}: ${error instanceof Error ? error.message : 'Upload failed.'}`)
      }
    }
    setDocumentError(errors.join(' '))
    setDocumentBusy(false)
  }

  async function removeStoredDocument(document: OnboardingDocument) {
    if (!active || documentBusy) return
    const conversationId = active.id
    setDocumentBusy(true)
    setDocumentError('')
    try {
      await deleteDocument(conversationId, document.id)
      setDocuments(current => ({
        ...current,
        [conversationId]: (current[conversationId] || []).filter(item => item.id !== document.id),
      }))
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Unable to remove the document.')
    } finally {
      setDocumentBusy(false)
    }
  }

  async function downloadStoredDocument(document: OnboardingDocument) {
    try {
      const blob = await downloadDocument(document.id)
      const url = URL.createObjectURL(blob)
      const link = window.document.createElement('a')
      link.href = url
      link.download = document.filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      setDocumentError(error instanceof Error ? error.message : 'Unable to download the document.')
    }
  }

  function handleTabKeys(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const tabs: Tab[] = ['chat', 'info', 'history']
    let next: number
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = tabs.length - 1
    else return
    event.preventDefault()
    setTab(tabs[next])
    document.getElementById(`tab-${tabs[next]}`)?.focus()
  }

  if (loading || !active) return <CustomerLayout onLogout={onLogout} onboarding>
    <main className="mx-auto w-full max-w-[1600px] px-[clamp(1.1rem,3vw,3.3rem)] py-5">
      <Link to="/customer" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-primary"><ArrowLeft className="size-4" aria-hidden="true" />Back to overview</Link>
      {apiError ? <div role="alert" className="mt-6 rounded-xl border border-destructive/40 bg-destructive/5 p-5"><p className="text-sm">{apiError}</p><Button variant="outline" className="mt-3" onClick={() => setLoadAttempt(attempt => attempt + 1)}>Retry</Button></div> : <p role="status" className="mt-6 text-sm text-muted-foreground">Loading your onboarding from Atlas…</p>}
    </main>
  </CustomerLayout>

  return <CustomerLayout onLogout={onLogout} onboarding>
    <main className="mx-auto w-full max-w-[1600px] px-[clamp(1.1rem,3vw,3.3rem)] py-5">
      <Link to="/customer" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-primary"><ArrowLeft className="size-4" aria-hidden="true" />Back to overview</Link>
      <div className="mt-3 flex items-start justify-between gap-4">
        <div><h1 className="text-2xl font-bold tracking-tight xl:text-3xl">Let’s get your business onboard</h1><p className="mt-1 text-sm text-muted-foreground">A conversation today. A new chapter for your business tomorrow.</p></div>
        <span className="rounded-full border bg-card px-3 py-1.5 text-xs font-medium text-primary">Guided demo</span>
      </div>
      <div className="mt-5 flex h-[clamp(280px,calc(100dvh-300px),560px)] min-h-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-sm">
        <div role="tablist" aria-label="Onboarding workspace" className="flex shrink-0 overflow-x-auto border-b px-4">
          {([
            { id: 'chat', label: 'Onboarding chat', icon: MessageSquare },
            { id: 'info', label: 'Company documents', icon: FileText },
            { id: 'history', label: 'Past conversations', icon: History },
          ] as const).map(({ id, label, icon: Icon }, index) => <button key={id} id={`tab-${id}`} type="button" role="tab" aria-selected={tab === id} aria-controls={`panel-${id}`} tabIndex={tab === id ? 0 : -1} onKeyDown={event => handleTabKeys(event, index)} onClick={() => setTab(id)} className={`flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-4 ${tab === id ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}><Icon className="size-4" aria-hidden="true" />{label}</button>)}
        </div>

        <section role="tabpanel" id="panel-chat" aria-labelledby="tab-chat" hidden={tab !== 'chat'} className={tab === 'chat' ? 'flex min-h-0 flex-1 flex-col' : 'hidden'}>
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
            <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-accent text-primary"><Bot className="size-5" aria-hidden="true" /></span><div><h2 className="text-sm font-semibold">Your onboarding guide</h2><p className="text-xs text-muted-foreground">Business details · Owners · Banking needs</p></div></div>
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs font-medium text-muted-foreground">{active.answers.length} of {active.fields.length} questions answered</p>
              <Button type="button" variant="outline" size="sm" onClick={startNew} disabled={saving}>
                <Plus aria-hidden="true" />Start new conversation
              </Button>
            </div>
          </div>
          <div ref={logRef} role="log" aria-label="Onboarding conversation" aria-live="polite" className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            <OnboardingTranscript conversation={active} />
            {complete && <div className="rounded-xl border bg-muted/40 p-5"><h3 className="flex items-center gap-2 font-semibold"><Check className="size-4 text-primary" aria-hidden="true" />Your business details</h3><dl className="mt-4 space-y-3">{active.answers.map((answer, index) => <div key={active.fields[index]}><dt className="text-xs font-medium text-muted-foreground">{active.fields[index]}</dt><dd className="mt-1 text-sm whitespace-pre-wrap break-words">{answer}</dd></div>)}</dl></div>}
          </div>
          <div className="shrink-0 border-t bg-muted/20 px-5 py-3">
            {active.applicationId ? <Link className={buttonVariants()} to={`/customer/cases/${active.applicationId}`}>Track submitted application</Link> : complete ? <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-muted-foreground">Your draft conversation is ready to review.</p><Link className={buttonVariants()} to="/customer/apply" state={{ answers: active.answers, conversationId: active.id }}>Review application</Link><Button variant="outline" onClick={() => setTab('info')}>Add company documents</Button></div> : <form onSubmit={send} className="flex items-end gap-3 rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring">
              <label htmlFor="chat-answer" className="sr-only">{active.fields[active.answers.length]}</label>
              <textarea ref={inputRef} id="chat-answer" rows={1} maxLength={4000} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder="Type your answer…" readOnly={saving} className="min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none" />
              <Button type="submit" disabled={!draft.trim() || saving} aria-label="Send answer" className="mb-1"><Send aria-hidden="true" /><span className="hidden sm:inline">{saving ? 'Sending…' : 'Send'}</span></Button>
            </form>}
            <p className="mt-2 text-xs text-muted-foreground">{active.agentEnabled ? 'Agent-assisted intake' : 'Guided intake'} · Use synthetic business details only · Saved in Atlas</p>
          </div>
        </section>

        <section role="tabpanel" id="panel-info" aria-labelledby="tab-info" hidden={tab !== 'info'} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          <div className="flex items-start justify-between gap-4">
            <div><h2 className="text-xl font-semibold">Company documents</h2><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Add company records, ownership details or other documents to provide context for your onboarding.</p></div>
            <span className="shrink-0 rounded-full bg-secondary px-3 py-1 text-xs text-secondary-foreground">{activeDocuments.length} / 10 files</span>
          </div>
          <div onDragOver={event => { event.preventDefault(); setDragging(true) }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }} onDrop={event => { event.preventDefault(); setDragging(false); addDocuments(event.dataTransfer.files) }} className={`mt-4 flex flex-col items-center rounded-xl border-2 border-dashed px-5 py-5 text-center ${dragging ? 'border-primary bg-accent' : 'border-border bg-muted/30'}`}>
            <Upload className="size-6 text-primary" aria-hidden="true" />
            <p className="mt-2 text-sm font-medium">Drop company documents here</p>
            <p id="document-types" className="mt-1 text-xs text-muted-foreground">PDF, DOCX, TXT, CSV, PNG or JPG · Up to 10 MB per file</p>
            <input ref={fileInputRef} type="file" multiple accept=".pdf,.docx,.txt,.csv,.png,.jpg,.jpeg" aria-label="Choose company documents" aria-describedby="document-types" className="hidden" onChange={event => { addDocuments(event.target.files); event.target.value = '' }} />
            <Button variant="outline" className="mt-3" disabled={!documentsLoaded || documentBusy || activeDocuments.length >= 10} onClick={() => fileInputRef.current?.click()}>{documentBusy ? 'Saving…' : 'Choose files'}</Button>
          </div>
          {documentError && <div className="mt-3">
            <p role="alert" className="text-sm text-destructive">{documentError}</p>
            {!documentsLoaded && <Button variant="outline" size="sm" onClick={() => { setDocumentError(''); setDocumentLoadAttempt(attempt => attempt + 1) }}>Retry documents</Button>}
          </div>}
          <p className="mt-3 text-xs text-muted-foreground">Documents are stored in Atlas and can be downloaded or removed. Document review is outside this intake step. Use synthetic documents only.</p>
          <div className="mt-5">
            <h3 className="text-sm font-semibold">Attached to this conversation</h3>
            {activeDocuments.length ? <ul className="mt-2 divide-y rounded-xl border" aria-label="Attached company documents">{activeDocuments.map(document => <li key={document.id} className="flex items-center gap-3 px-4 py-3">
              <FileText className="size-5 shrink-0 text-primary" aria-hidden="true" />
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium" title={document.filename}>{document.filename}</p><p className="mt-1 text-xs text-muted-foreground">{document.sizeBytes < 1024 * 1024 ? `${Math.ceil(document.sizeBytes / 1024)} KB` : `${(document.sizeBytes / (1024 * 1024)).toFixed(1)} MB`} · Stored in Atlas</p></div>
              <Button variant="ghost" aria-label={`Download ${document.filename}`} disabled={documentBusy} onClick={() => downloadStoredDocument(document)}><Download aria-hidden="true" /></Button>
              <Button variant="ghost" aria-label={`Remove ${document.filename}`} disabled={documentBusy} onClick={() => removeStoredDocument(document)}><X aria-hidden="true" /></Button>
            </li>)}</ul> : <p role="status" className="mt-2 text-sm text-muted-foreground">{documentsLoaded ? 'No documents added yet.' : documentError ? 'Documents unavailable.' : 'Loading documents…'}</p>}
          </div>
        </section>

        <section role="tabpanel" id="panel-history" aria-labelledby="tab-history" hidden={tab !== 'history'} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-semibold">Your conversations</h2><p className="mt-2 text-sm text-muted-foreground">Revisit or continue a conversation saved in Atlas.</p></div></div>
          <ul className="mt-6 space-y-3">{conversations.map(item => <li key={item.id}><button type="button" disabled={saving} onClick={() => { setActiveId(item.id); setDocumentError(''); setDraft(''); setTab('chat') }} className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border p-4 text-left outline-none hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-ring"><div className="min-w-0"><p className="font-medium break-words">{item.answers[0] || 'New business onboarding'}</p><p className="mt-1 text-xs text-muted-foreground">{new Date(item.startedAt).toLocaleString()} · {item.answers.length} of {item.fields.length} questions answered</p></div><span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">{item.id === active.id ? 'Current' : item.answers.length === item.fields.length ? 'Draft complete' : 'In progress'}</span></button></li>)}</ul>
        </section>
      </div>
      {apiError && <p role="alert" className="mt-3 text-sm text-destructive">{apiError}</p>}
    </main>
  </CustomerLayout>
}

function OnboardingTranscript({ conversation }: { conversation: Conversation }) {
  return conversation.prompts.slice(0, conversation.answers.length + 1).map((prompt, sequence) => {
    const turns = conversation.turns.filter(turn => turn.sequence === sequence)
    const answer = conversation.answers[sequence]
    const hasAcceptedTurn = turns.some(turn => !turn.clarification)

    return <div key={sequence} className="space-y-4">
      <BotMessage>{prompt}</BotMessage>
      {turns.map(turn => <div key={turn.id} className="space-y-4">
        <CustomerMessage>{turn.content}</CustomerMessage>
        {turn.clarification && <BotMessage>{turn.clarification}</BotMessage>}
      </div>)}
      {answer !== undefined && !hasAcceptedTurn && <CustomerMessage>{answer}</CustomerMessage>}
    </div>
  })
}

function CustomerMessage({ children }: { children: string }) {
  return <div className="ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm leading-6 whitespace-pre-wrap break-words text-primary-foreground"><span className="sr-only">You: </span>{children}</div>
}

function BotMessage({ children }: { children: string }) {
  return <div className="flex max-w-[95%] items-start gap-3 sm:max-w-[85%]"><span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-primary"><Bot className="size-4" aria-hidden="true" /></span><div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 text-sm leading-6"><span className="sr-only">Onboarding guide: </span>{children}</div></div>
}
