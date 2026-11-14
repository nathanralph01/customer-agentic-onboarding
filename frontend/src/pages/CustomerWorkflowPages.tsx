import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import CustomerLayout from '@/components/CustomerLayout'
import { Button, buttonVariants } from '@/components/ui/button'
import { CaseList, ConfirmDialog, Documents, Field, RequestStatus } from '@/components/WorkflowUi'
import { card, caseOpen, dateLabel, input, page, statusLabel } from '@/lib/workflowUi'
import { ApiError, customerApi, downloadCaseDocument, type Application, type CaseDocument } from '@/lib/api'

type Props = { onLogout: () => void }

const fields: { key: keyof Application; label: string }[][] = [
  [{ key: 'businessName', label: 'Legal business name' }, { key: 'businessActivity', label: 'Business activity' }, { key: 'sector', label: 'Industry or sector' }, { key: 'registration', label: 'Country and province or state of registration' }],
  [{ key: 'owners', label: 'Owners and ownership percentages' }],
  [{ key: 'products', label: 'Requested banking products (comma separated)' }],
]

export function ApplicationPage({ onLogout }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const draft = location.state as { answers?: string[]; conversationId?: string } | null
  const [name = '', activity = '', registration = '', owners = '', products = ''] = draft?.answers ?? []
  const [form, setForm] = useState<Application>({ businessName: name, businessActivity: activity, registration, owners, products, sector: '' })
  const [step, setStep] = useState(0)
  const [showErrors, setShowErrors] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<keyof Application, string>>>({})
  const [validationNotice, setValidationNotice] = useState('')
  const missingFields = fields[step].filter(({ key }) => !form[key].trim())
  const [applicationId] = useState(() => crypto.randomUUID())
  const submit = useMutation({
    mutationFn: () => customerApi.submit({ ...form, id: applicationId, conversationId: draft?.conversationId }),
    onSuccess: saved => navigate(`/customer/cases/${saved.id}`, { replace: true }),
    onError: error => {
      if (!(error instanceof ApiError) || error.status !== 422) return
      const issues = Object.fromEntries(error.fields.map(issue => [issue.field, issue.message]))
      const invalidStep = fields.findIndex(group => group.some(({ key }) => key in issues))
      setFieldErrors(issues)
      if (invalidStep >= 0) setStep(invalidStep)
      setValidationNotice(error.fields.length ? fields.flat()
        .filter(({ key }) => key in issues)
        .map(({ key, label }) => `${label} — ${issues[key]}`).join('\n')
        : error.message)
    },
  })

  function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (missingFields.length) {
      setShowErrors(true)
      event.currentTarget.querySelector<HTMLTextAreaElement>(`[name="${missingFields[0].key}"]`)?.focus()
      return
    }
    setShowErrors(false)
    if (step < fields.length - 1) setStep(step + 1)
    else if (!submit.isPending) submit.mutate()
  }

  return <CustomerLayout onLogout={onLogout} onboarding>
    <main className={page}>
      <div><h1 className="text-3xl font-bold">Business banking application</h1><p className="mt-2 text-sm text-muted-foreground">Step {step + 1} of {fields.length} · {['Business details', 'Ownership', 'Products'][step]}</p></div>
      <form key={step} noValidate onSubmit={next} className={`${card} max-w-2xl space-y-4`}>
        {fields[step].map(({ key, label }) => {
          const error = fieldErrors[key] || (showErrors && !form[key].trim() ? 'This field is required.' : '')
          const invalid = !!error
          return <div key={key}>
            <Field label={label}>
              <textarea name={key} className={input} required maxLength={4000}
                aria-invalid={invalid || undefined} aria-describedby={invalid ? `${key}-error` : undefined}
                rows={key === 'owners' || key === 'businessActivity' ? 3 : 1} value={form[key]}
                readOnly={submit.isPending}
                onChange={event => {
                  setFieldErrors(current => ({ ...current, [key]: undefined }))
                  setForm(current => ({ ...current, [key]: event.target.value }))
                }} />
            </Field>
            {key === 'products' && <p className="mt-1 text-sm text-muted-foreground">Choose Business account, Payments, or Credit facility. Payments and Credit facility require a Business account.</p>}
            {invalid && <p id={`${key}-error`} className="mt-1 text-sm text-destructive">{error}</p>}
          </div>
        })}
        {showErrors && missingFields.length > 0 && <p role="alert" className="text-sm text-destructive">Complete the required fields to continue.</p>}
        <RequestStatus pending={submit.isPending} label="Validating application…" error={submit.error instanceof ApiError && submit.error.status === 422 ? null : submit.error} />
        <div className="flex flex-wrap gap-3">
          {step > 0 && <Button type="button" variant="outline" onClick={() => { setShowErrors(false); setStep(step - 1) }} disabled={submit.isPending}>Back</Button>}
          <Button type="submit" disabled={submit.isPending}>{submit.isPending ? 'Submitting…' : step === fields.length - 1 ? 'Submit application' : 'Continue'}</Button>
        </div>
      </form>
      {validationNotice && <ConfirmDialog title="Invalid value" description={validationNotice} action="Fix application" onClose={() => setValidationNotice('')} />}
    </main>
  </CustomerLayout>
}

export function CustomerCasesPage({ onLogout }: Props) {
  const query = useQuery({ queryKey: ['customer-cases'], queryFn: customerApi.list, refetchInterval: 4000 })
  return <CustomerLayout onLogout={onLogout}>
    <main className={page}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-3xl font-bold">Your applications</h1><Link to="/customer/apply" className={buttonVariants()}>New application</Link></div>
      <RequestStatus pending={query.isPending} error={query.error} />
      <CaseList cases={query.data} />
    </main>
  </CustomerLayout>
}

export function CustomerCasePage({ onLogout }: Props) {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [response, setResponse] = useState('')
  const [signer, setSigner] = useState('')
  const query = useQuery({ queryKey: ['customer-case', id], queryFn: () => customerApi.detail(id), refetchInterval: 4000 })
  const documents = useQuery({ queryKey: ['case-documents', id], queryFn: () => customerApi.documents(id), enabled: !!query.data, refetchInterval: 4000 })
  const summary = useQuery({ queryKey: ['summary', id], queryFn: () => customerApi.summary(id), enabled: query.data?.status === 'ONBOARDED' })
  const mutation = useMutation({
    mutationFn: async (action: 'info' | 'sign' | 'return' | File) => {
      if (action === 'info') return customerApi.information(id, response)
      if (action === 'sign') return customerApi.sign(id, signer)
      if (action === 'return') return customerApi.returnAgreement(id)
      return customerApi.upload(id, action)
    },
    onSuccess: (_, action) => {
      if (action === 'info') setResponse('')
      if (action === 'sign') setSigner('')
      void queryClient.invalidateQueries({ queryKey: ['customer-case', id] })
      void queryClient.invalidateQueries({ queryKey: ['case-documents', id] })
      void queryClient.invalidateQueries({ queryKey: ['customer-cases'] })
    },
  })
  const download = useMutation({ mutationFn: (document: CaseDocument) => downloadCaseDocument('customer', id, document) })
  const item = query.data

  return <CustomerLayout onLogout={onLogout}>
    <main className={page}>
      <Link to="/customer/cases" className="text-sm font-medium text-primary hover:underline">Back to applications</Link>
      <RequestStatus pending={query.isPending} error={query.error} />
      {item && <>
        <div><h1 className="text-3xl font-bold">{item.application.businessName}</h1><p className="mt-2 text-xs text-muted-foreground">Application {item.id}</p><p className="mt-2 text-sm font-semibold capitalize">{item.rejected ? 'rejected' : statusLabel(item.status)}</p></div>
        <section className={card}>
          <h2 className="text-lg font-semibold">Onboarding progress</h2>
          <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {item.steps.map((label, index) => <li key={label} aria-current={index === item.stage && caseOpen(item.status) ? 'step' : undefined} className={`rounded-lg border p-3 text-sm ${index === item.stage && caseOpen(item.status) ? 'border-primary bg-accent' : ''}`}>
              <p className="font-medium">{label}</p><p className="text-xs text-muted-foreground">{index < item.completed ? 'Complete' : item.status === 'CANCELLED' ? 'Closed' : index === item.stage ? 'Current step' : 'Upcoming'}</p>
            </li>)}
          </ol>
          <p className="mt-4 text-sm">{item.estimatedCompletion ? `Estimated completion: ${dateLabel(item.estimatedCompletion)}` : item.estimatedMinutes !== null ? `About ${item.estimatedMinutes} minutes of processing after the current handoff.` : ''}</p>
          <p className="mt-2 text-sm text-muted-foreground">{item.contact.name} · <a className="underline" href={`mailto:${item.contact.email}`}>{item.contact.email}</a> · <a className="underline" href={`tel:${item.contact.phone}`}>{item.contact.phone}</a></p>
        </section>
        <RequestStatus pending={mutation.isPending} label={mutation.variables === 'info' ? 'Sending information…' : mutation.variables === 'sign'
          ? 'Saving signature…' : mutation.variables === 'return' ? 'Returning signed agreement…' : 'Uploading document…'} error={mutation.error || download.error} />
        {item.requestedInformation && <form className={`${card} space-y-3`} onSubmit={event => { event.preventDefault(); mutation.mutate('info') }}>
          <h2 className="text-lg font-semibold">Information requested</h2>
          <p className="whitespace-pre-wrap text-sm">{item.requestedInformation}</p>
          <Field label="Your response"><textarea className={input} value={response} onChange={event => setResponse(event.target.value)} maxLength={4000} required /></Field>
          <Button type="submit" disabled={!response.trim() || mutation.isPending}>Send information</Button>
        </form>}
        <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Application documents</h2>
          {item.requiredDocuments.length > 0 && <p className="text-sm text-muted-foreground">Requested documents: {item.requiredDocuments.join(', ')}.</p>}
          <RequestStatus pending={documents.isPending} error={documents.error} />
          {documents.data && <Documents documents={documents.data} downloading={download.isPending ? download.variables?.id : undefined} download={document => download.mutate(document)} />}
          {caseOpen(item.status) && !(item.signedWorkflow && item.stage === 5) && <>
            <input ref={fileInput} type="file" accept=".pdf,.docx,.txt,.csv,.png,.jpg,.jpeg" aria-label="Upload supporting document" className="sr-only" tabIndex={-1} onChange={event => {
              const file = event.target.files?.[0]
              if (file) mutation.mutate(file)
              event.target.value = ''
            }} />
            <Button variant="outline" disabled={mutation.isPending} onClick={() => fileInput.current?.click()}>Upload document</Button>
          </>}
        </section>
        {item.status === 'AWAITING_SIGNATURE' && item.signedWorkflow && item.agreementSigned && <section className={`${card} space-y-3`}>
          <h2 className="text-lg font-semibold">Return your signed agreement</h2>
          <p className="text-sm text-muted-foreground">Your sandbox signature is saved. Return the signed agreement for bank review.</p>
          <Button disabled={mutation.isPending} onClick={() => mutation.mutate('return')}>Return signed agreement</Button>
        </section>}
        {item.status === 'AWAITING_SIGNATURE' && !item.agreementSigned && <form className={`${card} space-y-3`} onSubmit={event => { event.preventDefault(); mutation.mutate('sign') }}>
          <h2 className="text-lg font-semibold">Sign the sandbox agreement</h2>
          <p className="text-sm text-muted-foreground">Review the agreement above, then enter the synthetic signer’s name.</p>
          <Field label="Signer’s name"><input className={input} value={signer} onChange={event => setSigner(event.target.value)} required maxLength={4000} /></Field>
          <Button type="submit" disabled={!signer.trim() || mutation.isPending}>Sign agreement</Button>
        </form>}
        {item.status === 'ONBOARDED' && <section className={`${card} space-y-2`}>
          <h2 className="text-lg font-semibold">Sandbox account</h2>
          <RequestStatus pending={summary.isPending} error={summary.error} />
          {summary.data && <><p className="text-sm">{summary.data.accountReference} · {summary.data.status}</p>
            <p className="text-sm">{summary.data.products.join(', ')}</p>
            <ul className="list-inside list-disc text-sm">{summary.data.benefits.map(benefit => <li key={benefit}>{benefit}</li>)}</ul>
            <p className="text-sm text-muted-foreground">{summary.data.access}</p></>}
        </section>}
      </>}
    </main>
  </CustomerLayout>
}
