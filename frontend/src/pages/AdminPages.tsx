import { useState, type FormEvent, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardCheck, ClipboardList, ShieldCheck, Users } from 'lucide-react'
import { Link, NavLink, useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { CaseList, ConfirmDialog, Documents, Field, RequestStatus, SuccessNotice } from '@/components/WorkflowUi'
import { card, caseOpen, dateLabel, input, page, statusLabel } from '@/lib/workflowUi'
import type { Citation } from '@/lib/api'
import { adminApi, downloadCaseDocument, getPersona, type CaseDetail, type CaseDocument, type Risk } from '@/lib/api'

type Props = { onLogout: () => void }
type ReviewDecision = '' | 'continue' | 'pause' | 'request_info' | 'cancel'

const statuses = ['APPLIED', 'VERIFYING', 'RISK_ASSESSMENT', 'COMPLIANCE_CHECK', 'ADMIN_REVIEW', 'DOCUMENT_GENERATION', 'AWAITING_SIGNATURE', 'PROVISIONING', 'NEEDS_INFO', 'PAUSED', 'ONBOARDED', 'CANCELLED']
const scores = [{ key: 'ownership', label: 'Ownership' }, { key: 'activity', label: 'Business activity' }, { key: 'geography', label: 'Geography' }] as const

function AdminLayout({ onLogout, children }: Props & { children: ReactNode }) {
  return <div className="min-h-screen bg-muted/40">
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
        <Link to="/admin" className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-5 text-primary" aria-hidden="true" />Customer 360 Bank Workspace</Link>
        <div className="flex items-center gap-3"><span className="text-sm text-muted-foreground">{getPersona()?.name}</span><Button variant="ghost" onClick={onLogout}><Users aria-hidden="true" />Switch persona</Button></div>
      </div>
      <nav aria-label="Bank workspace" className="mx-auto flex max-w-6xl flex-wrap gap-2 px-5 pb-3 sm:px-8">
        {[{ path: '/admin', label: 'Applications', icon: ClipboardList }, { path: '/admin/reviews', label: 'Review queue', icon: ClipboardCheck }, { path: '/admin/guardrails', label: 'Guardrails', icon: ShieldCheck }].map(({ path, label, icon: Icon }) =>
          <NavLink key={path} to={path} end className={({ isActive }) => `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium ${isActive ? 'bg-accent text-primary' : 'hover:bg-muted'}`}><Icon className="size-4" aria-hidden="true" />{label}</NavLink>
        )}
      </nav>
    </header>
    <main className={page}>{children}</main>
  </div>
}

export function AdminCasesPage({ onLogout, queue = false }: Props & { queue?: boolean }) {
  const [status, setStatus] = useState('')
  const [risk, setRisk] = useState('')
  const [sector, setSector] = useState('')
  const [since, setSince] = useState('')
  const filters = new URLSearchParams(Object.entries({ status, risk, sector, since }).filter(([, value]) => !!value))
  const query = useQuery({
    queryKey: queue ? ['admin-queue'] : ['admin-cases', filters.toString()],
    queryFn: () => queue ? adminApi.queue() : adminApi.list(filters),
    refetchInterval: 4000,
  })

  return <AdminLayout onLogout={onLogout}>
    <h1 className="text-3xl font-bold">{queue ? 'Review queue' : 'Onboarding applications'}</h1>
    {queue ? <p className="text-sm text-muted-foreground">Applications waiting for risk or document review.</p> :
      <div className={`${card} grid gap-3 sm:grid-cols-2 lg:grid-cols-4`}>
        <Field label="Status"><select className={input} value={status} onChange={event => setStatus(event.target.value)}><option value="">All statuses</option>{statuses.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></Field>
        <Field label="Risk tier"><select className={input} value={risk} onChange={event => setRisk(event.target.value)}><option value="">All tiers</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></Field>
        <Field label="Sector"><input className={input} value={sector} onChange={event => setSector(event.target.value)} /></Field>
        <Field label="Submitted on or after"><input className={input} type="date" value={since} onChange={event => setSince(event.target.value)} /></Field>
      </div>}
    <RequestStatus pending={query.isPending} error={query.error} />
    <CaseList cases={query.data} admin />
  </AdminLayout>
}

function ReviewForm({ item, onSaved }: { item: CaseDetail; onSaved: (message: string) => void }) {
  const waitingCustomer = ['NEEDS_INFO', 'AWAITING_SIGNATURE'].includes(item.status)
  const [decision, setDecision] = useState<ReviewDecision>(waitingCustomer ? '' : 'continue')
  const [comments, setComments] = useState('')
  const [confirming, setConfirming] = useState(false)
  const editableRisk = !item.signedWorkflow && [2, 4].includes(item.stage) && !['PAUSED', 'NEEDS_INFO'].includes(item.status)
  const [editRisk, setEditRisk] = useState(editableRisk && item.stage === 2 && !item.risk)
  const [tier, setTier] = useState<Risk['tier']>(item.risk?.tier ?? 'low')
  const [rationale, setRationale] = useState(item.risk?.rationale ?? '')
  const [evidence, setEvidence] = useState(item.risk?.evidence.join('\n') ?? '')
  const [missing, setMissing] = useState(item.risk?.missingInputs.join('\n') ?? '')
  const [assessment, setAssessment] = useState({ ownership: item.risk?.ownership ?? 1, activity: item.risk?.activity ?? 1, geography: item.risk?.geography ?? 1 })
  const lines = (value: string) => value.split('\n').map(line => line.trim()).filter(Boolean)
  const review = useMutation({
    mutationFn: () => adminApi.review(item.id, decision, item.revision, comments, editableRisk && editRisk && decision !== 'cancel' ? {
      tier, rationale, evidence: lines(evidence), missingInputs: lines(missing), ...assessment,
    } : undefined),
    onSuccess: (saved) => onSaved(saved.rejected ? 'Application rejected.' : saved.status === 'ONBOARDED'
      ? 'Onboarding completed successfully.' : decision === 'request_info' ? 'Information request sent.'
      : decision === 'pause' ? 'Application paused.' : decision === 'cancel' ? 'Application cancelled.'
      : decision === 'continue' && item.status === 'PAUSED' ? 'Application resumed.'
      : `${item.currentStep} completed successfully.`),
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (review.isPending) return
    if (decision === 'cancel') {
      setConfirming(true)
      return
    }
    review.mutate()
  }

  const signedAction = ['Start agreement preparation', 'Generate agreement', 'Release agreement', '', 'Verify evidence and assess risk', 'Approve and complete onboarding'][item.stage]
  if (!caseOpen(item.status)) return null
  return <><form className={`${card} space-y-4`} onSubmit={submit}>
    <h2 className="text-lg font-semibold">{item.status === 'ADMIN_REVIEW' ? item.currentStep : 'Bank action'}</h2>
    {item.stage === 4 && item.risk?.tier === 'high' && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">High risk. Record the reason for continuing.</p>}
    {waitingCustomer && <p className="text-sm text-muted-foreground">Waiting for the customer to {item.status === 'NEEDS_INFO' ? 'provide information' : 'sign the agreement'}.</p>}
    <Field label="Decision"><select className={input} value={decision} required onChange={event => setDecision(event.target.value as ReviewDecision)}>
      {waitingCustomer && <option value="" disabled>Choose an action</option>}
      {!waitingCustomer && <option value="continue">{item.status === 'PAUSED' ? 'Resume' : item.signedWorkflow ? signedAction : item.stage === 8 ? 'Provision sandbox account' : item.stage === 5 ? 'Prepare sandbox agreement' : 'Continue'}</option>}
      {!['PAUSED', 'NEEDS_INFO'].includes(item.status) && <option value="pause">Pause</option>}
      {!['PAUSED', 'NEEDS_INFO'].includes(item.status) && <option value="request_info">Request information</option>}
      <option value="cancel">{item.signedWorkflow ? 'Reject application' : 'Cancel application'}</option>
    </select></Field>
    {editableRisk && decision !== 'cancel' && <>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editRisk} onChange={event => setEditRisk(event.target.checked)} />{item.risk ? 'Override the recorded assessment' : 'Enter a bank risk assessment'}</label>
      {editRisk && <fieldset className="grid gap-3 rounded-lg border p-4">
        <legend className="px-2 text-sm font-semibold">Bank risk assessment</legend>
        <Field label="Overall tier"><select className={input} value={tier} onChange={event => setTier(event.target.value as Risk['tier'])}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></Field>
        <div className="grid gap-3 sm:grid-cols-3">{scores.map(({ key, label }) => <Field key={key} label={label + ' (1–5)'}>
          <input className={input} type="number" min={1} max={5} required value={assessment[key]} onChange={event => setAssessment(current => ({ ...current, [key]: event.target.valueAsNumber }))} />
        </Field>)}</div>
        <Field label="Rationale"><textarea className={input} value={rationale} onChange={event => setRationale(event.target.value)} required maxLength={4000} /></Field>
        <Field label="Evidence references (one per line)"><textarea className={input} value={evidence} onChange={event => setEvidence(event.target.value)} required maxLength={4000} /></Field>
        <Field label="Missing inputs (one per line)"><textarea className={input} value={missing} onChange={event => setMissing(event.target.value)} maxLength={4000} /></Field>
      </fieldset>}
    </>}
    <Field label={decision === 'request_info' ? 'What should the customer provide?' : 'Reviewer comments'}>
      <textarea className={input} value={comments} onChange={event => setComments(event.target.value)} maxLength={4000} required={decision === 'cancel' && item.signedWorkflow} />
    </Field>
    <RequestStatus pending={review.isPending} label="Saving bank decision…" error={review.error} />
    <Button type="submit" disabled={review.isPending || !decision}>{review.isPending ? 'Working…' : 'Save decision'}</Button>
  </form>
    {confirming && <ConfirmDialog title={item.signedWorkflow ? 'Reject application?' : 'Cancel application?'}
      description={comments.trim() || 'This closes the application.'}
      action={item.signedWorkflow ? 'Reject application' : 'Cancel application'}
      onClose={() => setConfirming(false)} onConfirm={() => { setConfirming(false); review.mutate() }} />}
  </>
}

function CitationList({ sources }: { sources: Citation[] }) {
  return <ul className="list-inside list-disc text-sm">{sources.map(source => <li key={source.id}>
    {source.url ? <a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.citation}</a> : source.citation}
  </li>)}</ul>
}

export function AdminCasePage({ onLogout }: Props) {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const [notice, setNotice] = useState('')
  const query = useQuery({ queryKey: ['admin-case', id], queryFn: () => adminApi.detail(id), refetchInterval: 4000 })
  const download = useMutation({ mutationFn: (document: CaseDocument) => downloadCaseDocument('admin', id, document) })
  function refresh(message: string) {
    setNotice(message)
    void queryClient.invalidateQueries({ queryKey: ['admin-case', id] })
    void queryClient.invalidateQueries({ queryKey: ['admin-cases'] })
    void queryClient.invalidateQueries({ queryKey: ['admin-queue'] })
  }
  const retry = useMutation({ mutationFn: () => adminApi.retry(id), onSuccess: () => refresh('Sandbox action completed successfully.') })
  const item = query.data
  const applicationLabels = { businessName: 'Legal business name', businessActivity: 'Business activity', sector: 'Sector', registration: 'Registration', owners: 'Owners', products: 'Requested products' }

  return <AdminLayout onLogout={onLogout}>
    {notice && <SuccessNotice message={notice} dismiss={() => setNotice('')} />}
    <Link to="/admin" className="text-sm text-primary hover:underline">Back to applications</Link>
    <RequestStatus pending={query.isPending} error={query.error} />
    {item && <>
      <div><h1 className="text-3xl font-bold">{item.application.businessName}</h1><p className="mt-2 text-sm capitalize">{item.rejected ? 'rejected' : statusLabel(item.status)} · {item.currentStep}</p><p className="mt-1 text-xs text-muted-foreground">Application {item.id}</p></div>
      <div className="grid items-start gap-5 lg:grid-cols-2">
        <section className={card}>
          <h2 className="text-lg font-semibold">Application</h2>
          <dl className="mt-4 grid gap-3">{Object.entries(applicationLabels).map(([field, label]) => <div key={field}><dt className="text-xs font-medium text-muted-foreground">{label}</dt><dd className="whitespace-pre-wrap break-words text-sm">{item.application[field as keyof typeof applicationLabels]}</dd></div>)}</dl>
          {item.informationResponses.map((entry, index) => <div key={index} className="mt-4 rounded-lg bg-muted p-3 text-sm"><p className="font-medium">{entry.request}</p><p className="mt-1 whitespace-pre-wrap">{entry.response}</p></div>)}
        </section>
        <ReviewForm key={item.revision} item={item} onSaved={refresh} />
        <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Risk assessment</h2>
          {item.risk ? <>
            <p className="text-sm font-semibold capitalize">{item.risk.tier} risk · Policy v{item.risk.policyVersion} · {item.risk.source === 'agent' ? 'Agent recommendation' : 'Bank review'}</p>
            <p className="whitespace-pre-wrap text-sm">{item.risk.rationale}</p>
            <ul className="grid gap-2 text-sm sm:grid-cols-3">{scores.map(({ key, label }) => <li className="rounded-md bg-muted p-2" key={key}>{label}: {item.risk?.[key]} / 5</li>)}</ul>
            <h3 className="text-sm font-semibold">Evidence</h3>
            {item.risk.sources && <CitationList sources={item.risk.sources} />}
            <ul className="list-inside list-disc break-words text-sm">{item.risk.evidence.map((line, index) => <li key={index}>{line}</li>)}</ul>
            {item.risk.missingInputs.length > 0 && <><h3 className="text-sm font-semibold">Missing inputs</h3><ul className="list-inside list-disc text-sm">{item.risk.missingInputs.map((line, index) => <li key={index}>{line}</li>)}</ul></>}
          </> : <p className="text-sm text-muted-foreground">Assessment pending.</p>}
        </section>
        {item.verification && <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Signed agreement verification</h2>
          {item.verification.retrieval === 'atlas_vector_search' && <p className="text-xs text-muted-foreground">References retrieved with MongoDB Atlas Vector Search</p>}
          <ul className="list-inside list-disc text-sm">{item.verification.findings.map((finding, index) => <li key={index}>{finding}</li>)}</ul>
          {item.verification.missingInputs.length > 0 && <p className="text-sm">Missing evidence: {item.verification.missingInputs.join('; ')}</p>}
          <CitationList sources={item.verification.sources} />
        </section>}
        <section className={`${card} space-y-3`}><h2 className="text-lg font-semibold">Documents</h2><RequestStatus error={download.error} /><Documents documents={item.documents} downloading={download.isPending ? download.variables?.id : undefined} download={document => download.mutate(document)} /></section>
        <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Sandbox actions</h2>
          <p className="text-sm">Last checkpoint: {item.checkpoint.step} · revision {item.checkpoint.revision}</p>
          {item.actions.length ? <ul className="grid gap-2">{item.actions.map(action => <li key={action.id} className="break-words rounded-lg bg-muted p-3 text-sm">
            <p className="font-medium">{statusLabel(action.target)} · {action.state}</p><p className="text-xs">{action.reference}</p><p>{action.evidence}</p>{action.state === 'conflict' && <p className="mt-1 text-destructive">The target record needs operator review.</p>}
          </li>)}</ul> : <p className="text-sm text-muted-foreground">No sandbox actions recorded.</p>}
          <RequestStatus pending={retry.isPending} label="Retrying sandbox action…" error={retry.error} />
          {!item.signedWorkflow && ['DOCUMENT_GENERATION', 'PROVISIONING', 'VERIFYING'].includes(item.status) && item.actions.some(action => action.state !== 'verified') && <Button variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}>Retry sandbox action</Button>}
        </section>
        <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Audit history</h2>
          <ol className="divide-y">{item.history.map((entry, index) => <li key={index} className="py-2 text-sm">
            <p className="font-medium capitalize">{statusLabel(entry.action)} · {entry.role}</p>
            <p className="text-xs text-muted-foreground">{entry.from && `${statusLabel(entry.from)} → `}{statusLabel(entry.to)} · {dateLabel(entry.created_at)}</p>
            {entry.reason && <p className="mt-1 whitespace-pre-wrap break-words">{entry.reason}</p>}
          </li>)}</ol>
        </section>
      </div>
    </>}
  </AdminLayout>
}

export function GuardrailsPage({ onLogout }: Props) {
  const client = useQueryClient()
  const [notice, setNotice] = useState('')
  const [caseId, setCaseId] = useState('')
  const [rule, setRule] = useState('')
  const [reason, setReason] = useState('')
  const [decisionNotes, setDecisionNotes] = useState<Record<string, string>>({})
  const guardrails = useQuery({ queryKey: ['guardrails'], queryFn: adminApi.guardrails })
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: adminApi.proposals })
  function refresh() {
    void client.invalidateQueries({ queryKey: ['guardrails'] })
    void client.invalidateQueries({ queryKey: ['proposals'] })
  }
  const submit = useMutation({ mutationFn: () => adminApi.propose(caseId, rule, reason), onSuccess: () => {
    setCaseId(''); setRule(''); setReason(''); setNotice('Proposal submitted.'); refresh()
  } })
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => adminApi.decide(id, action, decisionNotes[id]),
    onSuccess: (_, { action }) => { setNotice(action === 'approve' ? 'Proposal approved.' : 'Proposal rejected.'); refresh() },
  })
  return <AdminLayout onLogout={onLogout}>
    {notice && <SuccessNotice message={notice} dismiss={() => setNotice('')} />}
    <h1 className="text-3xl font-bold">Guardrails</h1>
    <RequestStatus pending={guardrails.isPending || proposals.isPending} error={guardrails.error || proposals.error || decide.error} />
    <section className={`${card} space-y-3`}>
      <h2 className="text-lg font-semibold">Policy versions</h2>
      {guardrails.data?.map(policy => <div key={policy.key}>
        <h3 className="text-sm font-medium">{policy.key} · Active v{policy.activeVersion}</h3>
        <ul className="divide-y">{[...policy.versions].reverse().map(version => <li key={version.version} className="py-2 text-sm"><span className="font-semibold">v{version.version}</span> {version.rule}</li>)}</ul>
      </div>)}
    </section>
    <form className={`${card} grid gap-3`} onSubmit={event => { event.preventDefault(); submit.mutate() }}>
      <h2 className="text-lg font-semibold">Propose a guardrail</h2>
      <p className="text-sm text-muted-foreground">Link an application with a recorded risk override.</p>
      <Field label="Application ID"><input className={input} value={caseId} onChange={event => setCaseId(event.target.value)} required /></Field>
      <Field label="Proposed rule"><textarea className={input} value={rule} onChange={event => setRule(event.target.value)} maxLength={4000} required /></Field>
      <Field label="Reason for change"><textarea className={input} value={reason} onChange={event => setReason(event.target.value)} maxLength={4000} required /></Field>
      <RequestStatus pending={submit.isPending} label="Submitting proposal…" error={submit.error} />
      <Button type="submit" className="justify-self-start" disabled={submit.isPending}>Submit proposal</Button>
    </form>
    <section className="grid gap-3">
      <RequestStatus pending={decide.isPending} label="Saving proposal decision…" />
      <h2 className="text-lg font-semibold">Proposals</h2>
      {proposals.data?.length === 0 && <p className={card}>No guardrail proposals yet.</p>}
      {proposals.data?.map(proposal => <article key={proposal.id} className={`${card} grid gap-3`}>
        <p className="font-semibold capitalize">{proposal.status}</p>
        <p className="whitespace-pre-wrap break-words text-sm">{proposal.rule}</p>
        <p className="text-sm text-muted-foreground">{proposal.reason}</p>
        <p className="text-sm"><Link to={`/admin/cases/${proposal.override.caseId}`} className="text-primary underline">Supporting application</Link> · {proposal.override.reason}</p>
        {proposal.decisionReason && <p className="text-sm">Decision: {proposal.decisionReason}</p>}
        {proposal.status === 'pending' && <>
          <Field label="Decision reason"><textarea className={input} value={decisionNotes[proposal.id] ?? ''} maxLength={4000} onChange={event => setDecisionNotes(current => ({ ...current, [proposal.id]: event.target.value }))} /></Field>
          <div className="flex gap-2">{['approve', 'reject'].map(action => <Button key={action} type="button" variant={action === 'reject' ? 'outline' : 'default'} className="capitalize" disabled={decide.isPending || !decisionNotes[proposal.id]?.trim()} onClick={() => decide.mutate({ id: proposal.id, action })}>{action}</Button>)}</div>
        </>}
      </article>)}
    </section>
  </AdminLayout>
}
