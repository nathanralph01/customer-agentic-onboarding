import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ArrowLeft, Bot, Check, History, MessageSquare, Plus, Send, FileText, Upload, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import CustomerLayout from '@/components/CustomerLayout'
import { Button } from '@/components/ui/button'

const QUESTIONS = [
  'What is the legal name of your business?',
  'What does your business do, and which industry does it operate in?',
  'Where is your business registered? Please include the country and province or state.',
  'Who owns your business? Please list the owners and their ownership percentages.',
  'Which banking products are you interested in? For example, a business account, payments or a credit facility.',
]
const FIELDS = ['Business name', 'Business activity', 'Registration location', 'Business owners', 'Banking products']
const WELCOME = 'Hi, I’m your onboarding guide. I’ll help you gather your business details, one question at a time. Let’s get started. '
type Conversation = { id: string; startedAt: string; answers: string[] }
type Tab = 'chat' | 'info' | 'history'
const STORAGE_KEY = 'customer360-onboarding-conversations'

function newConversation(): Conversation {
  return { id: crypto.randomUUID(), startedAt: new Date().toISOString(), answers: [] }
}

function loadConversations(): Conversation[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')
    if (Array.isArray(saved)) return saved.filter((item): item is Conversation =>
      item && typeof item.id === 'string' && typeof item.startedAt === 'string' &&
      !Number.isNaN(Date.parse(item.startedAt)) &&
      Array.isArray(item.answers) && item.answers.length <= QUESTIONS.length &&
      item.answers.every((answer: unknown) => typeof answer === 'string'))
  } catch { /* Start a fresh demo if tab storage is unavailable or invalid. */ }
  return []
}

export default function OnboardingPage({ onLogout }: { onLogout: () => void }) {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const saved = loadConversations()
    return saved.length ? saved : [newConversation()]
  })
  const [activeId, setActiveId] = useState(() => conversations[0].id)
  const [tab, setTab] = useState<Tab>('chat')
  const [draft, setDraft] = useState('')
  const [storageError, setStorageError] = useState(false)
  const [documents, setDocuments] = useState<Record<string, { id: string; file: File }[]>>({})
  const [documentError, setDocumentError] = useState('')
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const active = conversations.find(item => item.id === activeId) || conversations[0]
  const activeDocuments = documents[active.id] || []
  const complete = active.answers.length === QUESTIONS.length

  function saveConversations(next: Conversation[]) {
    setConversations(next)
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      setStorageError(false)
    } catch { setStorageError(true) }
  }

  useEffect(() => {
    const log = logRef.current
    if (log && tab === 'chat') log.scrollTop = log.scrollHeight
  }, [active.answers.length, activeId, tab])

  function updateActive(update: Partial<Conversation>) {
    saveConversations(conversations.map(item => item.id === active.id ? { ...item, ...update } : item))
  }

  function send(event?: FormEvent) {
    event?.preventDefault()
    if (!draft.trim() || complete) return
    updateActive({ answers: [...active.answers, draft.trim()] })
    setDraft('')
    inputRef.current?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send()
    }
  }

  function startNew() {
    const next = newConversation()
    saveConversations([next, ...conversations])
    setActiveId(next.id)
    setDocumentError('')
    setDraft('')
    setTab('chat')
  }

  function addDocuments(files: FileList | null) {
    if (!files) return
    const accepted: { id: string; file: File }[] = []
    const errors: string[] = []
    for (const file of Array.from(files)) {
      if (!/\.(pdf|docx|txt|csv|png|jpe?g)$/i.test(file.name)) {
        errors.push(`${file.name}: unsupported file type.`)
      } else if (file.size === 0 || file.size > 10 * 1024 * 1024) {
        errors.push(`${file.name}: choose a non-empty file up to 10 MB.`)
      } else if (activeDocuments.some(item => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified)) {
        errors.push(`${file.name}: already attached.`)
      } else if (activeDocuments.length + accepted.length >= 10) {
        errors.push('You can attach up to 10 documents per conversation.')
        break
      } else {
        accepted.push({ id: crypto.randomUUID(), file })
      }
    }
    setDocuments(current => ({ ...current, [active.id]: [...(current[active.id] || []), ...accepted] }))
    setDocumentError(errors.join(' '))
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
          <div className="flex shrink-0 items-center justify-between gap-3 border-b px-5 py-3">
            <div className="flex items-center gap-3"><span className="flex size-10 items-center justify-center rounded-xl bg-accent text-primary"><Bot className="size-5" aria-hidden="true" /></span><div><h2 className="text-sm font-semibold">Your onboarding guide</h2><p className="text-xs text-muted-foreground">Business details · Owners · Banking needs</p></div></div>
            <p className="text-xs font-medium text-muted-foreground">{active.answers.length} of {QUESTIONS.length} questions answered</p>
          </div>
          <div ref={logRef} role="log" aria-label="Onboarding conversation" aria-live="polite" className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            <BotMessage>{WELCOME}{QUESTIONS[0]}</BotMessage>
            {active.answers.map((answer, index) => <div key={`${active.id}-${index}`} className="space-y-4">
              <div className="ml-auto max-w-[85%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm leading-6 whitespace-pre-wrap break-words text-primary-foreground"><span className="sr-only">You: </span>{answer}</div>
              <BotMessage>{index + 1 < QUESTIONS.length ? `Thank you. ${QUESTIONS[index + 1]}` : 'Thanks, you’ve gathered the key details! You can review your answers below or attach company documents in the Company documents tab. This demo has not submitted an application or started verification.'}</BotMessage>
            </div>)}
            {complete && <div className="rounded-xl border bg-muted/40 p-5"><h3 className="flex items-center gap-2 font-semibold"><Check className="size-4 text-primary" aria-hidden="true" />Your business details</h3><dl className="mt-4 space-y-3">{active.answers.map((answer, index) => <div key={FIELDS[index]}><dt className="text-xs font-medium text-muted-foreground">{FIELDS[index]}</dt><dd className="mt-1 text-sm whitespace-pre-wrap break-words">{answer}</dd></div>)}</dl></div>}
          </div>
          <div className="shrink-0 border-t bg-muted/20 px-5 py-3">
            {complete ? <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-muted-foreground">Your draft conversation is ready to review.</p><Button variant="outline" onClick={() => setTab('info')}>Add company documents</Button></div> : <form onSubmit={send} className="flex items-end gap-3 rounded-xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring">
              <label htmlFor="chat-answer" className="sr-only">{QUESTIONS[active.answers.length]}</label>
              <textarea ref={inputRef} id="chat-answer" rows={1} maxLength={4000} value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder="Type your answer…" className="min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none" />
              <Button type="submit" disabled={!draft.trim()} aria-label="Send answer" className="mb-1"><Send aria-hidden="true" /><span className="hidden sm:inline">Send</span></Button>
            </form>}
            <p className="mt-2 text-xs text-muted-foreground">Scripted demo · Use synthetic business details only · Saved for this browser tab</p>
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
            <Button variant="outline" className="mt-3" disabled={activeDocuments.length >= 10} onClick={() => fileInputRef.current?.click()}>Choose files</Button>
          </div>
          {documentError && <p role="alert" className="mt-3 text-sm text-destructive">{documentError}</p>}
          <p className="mt-3 text-xs text-muted-foreground">Demo attachments stay on this page until you leave or refresh. Files are not uploaded or read by the scripted assistant yet. Use synthetic documents only.</p>
          <div className="mt-5">
            <h3 className="text-sm font-semibold">Attached to this conversation</h3>
            {activeDocuments.length ? <ul className="mt-2 divide-y rounded-xl border" aria-label="Attached company documents">{activeDocuments.map(({ id, file }) => <li key={id} className="flex items-center gap-3 px-4 py-3">
              <FileText className="size-5 shrink-0 text-primary" aria-hidden="true" />
              <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium" title={file.name}>{file.name}</p><p className="mt-1 text-xs text-muted-foreground">{file.size < 1024 * 1024 ? `${Math.ceil(file.size / 1024)} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`} · Attached locally</p></div>
              <Button variant="ghost" aria-label={`Remove ${file.name}`} onClick={() => { setDocuments(current => ({ ...current, [active.id]: (current[active.id] || []).filter(item => item.id !== id) })); setDocumentError('') }}><X aria-hidden="true" /></Button>
            </li>)}</ul> : <p className="mt-2 text-sm text-muted-foreground">No documents added yet.</p>}
          </div>
        </section>

        <section role="tabpanel" id="panel-history" aria-labelledby="tab-history" hidden={tab !== 'history'} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-5">
          <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="text-xl font-semibold">Your conversations</h2><p className="mt-2 text-sm text-muted-foreground">Revisit or continue a conversation from this browser tab.</p></div><Button onClick={startNew}><Plus aria-hidden="true" />New conversation</Button></div>
          <ul className="mt-6 space-y-3">{conversations.map(item => <li key={item.id}><button type="button" onClick={() => { setActiveId(item.id); setDocumentError(''); setDraft(''); setTab('chat') }} className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border p-4 text-left outline-none hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-2 focus-visible:ring-ring"><div className="min-w-0"><p className="font-medium break-words">{item.answers[0] || 'New business onboarding'}</p><p className="mt-1 text-xs text-muted-foreground">{new Date(item.startedAt).toLocaleString()} · {item.answers.length} of {QUESTIONS.length} questions answered</p></div><span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">{item.id === active.id ? 'Current' : item.answers.length === QUESTIONS.length ? 'Draft complete' : 'In progress'}</span></button></li>)}</ul>
        </section>
      </div>
      {storageError && <p role="status" className="mt-3 text-sm text-muted-foreground">Browser storage is unavailable. Keep this page open to retain your conversations.</p>}
    </main>
  </CustomerLayout>
}

function BotMessage({ children }: { children: string | string[] }) {
  return <div className="flex max-w-[95%] items-start gap-3 sm:max-w-[85%]"><span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent text-primary"><Bot className="size-4" aria-hidden="true" /></span><div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-3 text-sm leading-6"><span className="sr-only">Onboarding guide: </span>{children}</div></div>
}
