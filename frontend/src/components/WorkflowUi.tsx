import { useEffect, useId, useRef, type ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Case, CaseDocument } from '@/lib/api'
import { Button } from '@/components/ui/button'

import { card, dateLabel, statusLabel } from '@/lib/workflowUi'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1.5 text-sm font-medium">{label}{children}</label>
}

export function RequestStatus({ pending, error, label = 'Loading…' }: { pending?: boolean; error?: Error | null; label?: string }) {
  return <>{pending && <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden="true" />{label}</p>}
    {error && <p role="alert" className="rounded-md border border-destructive/30 bg-card p-3 text-sm text-destructive">{error.message}</p>}</>
}

export function CaseList({ cases, admin = false }: { cases?: Case[]; admin?: boolean }) {
  if (!cases) return null
  if (!cases.length) return <p className={card}>No applications to show.</p>
  return <ul className="grid gap-3">{cases.map(item => <li key={item.id}>
    <Link to={`/${admin ? 'admin' : 'customer'}/cases/${item.id}`} className={`${card} flex flex-wrap items-center justify-between gap-3 hover:border-primary`}>
      <div><p className="font-semibold">{item.application.businessName}</p><p className="mt-1 text-xs text-muted-foreground">{item.currentStep} · {dateLabel(item.submittedAt)}</p></div>
      <p className="text-sm capitalize">{item.rejected ? 'rejected' : statusLabel(item.status)}{item.riskTier && ` · ${item.riskTier} risk`}</p>
    </Link>
  </li>)}</ul>
}

export function Documents({ documents, download, downloading }: { documents: CaseDocument[]; download: (item: CaseDocument) => void; downloading?: string }) {
  if (!documents.length) return <p className="text-sm text-muted-foreground">No documents yet.</p>
  return <ul className="divide-y">{documents.map(document => <li key={document.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
    <div className="min-w-0 break-all"><p className="text-sm font-medium">{document.filename}</p><p className="text-xs capitalize text-muted-foreground">{document.source}</p>{document.coverNote && <p className="mt-1 break-words text-xs text-muted-foreground">{document.coverNote}</p>}</div>
    <Button variant="outline" size="sm" disabled={!!downloading} onClick={() => download(document)} aria-label={`Download ${document.filename}`}>{downloading === document.id ? 'Downloading…' : 'Download'}</Button>
    {document.pricing && <details className="w-full rounded-md border p-3 text-sm">
      <summary className="cursor-pointer font-medium">Review pricing and terms</summary>
      <p className="mt-2 text-xs text-muted-foreground">Schedule {document.pricing.version} · {document.pricing.currency}</p>
      {document.pricing.products.map(product => <section key={product.name} className="mt-3">
        <h3 className="font-semibold">{product.name}</h3>
        <ul className="mt-1 list-disc space-y-1 pl-5">{product.terms.map(term => <li key={term}>{term}</li>)}</ul>
      </section>)}
    </details>}
  </li>)}</ul>
}

export function ConfirmDialog({ title, description, action, onConfirm, onClose }: {
  title: string; description: string; action: string; onConfirm: () => void; onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const id = useId()
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} aria-labelledby={id} aria-describedby={`${id}-description`}
    onCancel={event => { event.preventDefault(); onClose() }}
    className="m-auto w-[min(90vw,28rem)] rounded-xl border bg-card p-6 text-card-foreground shadow-xl backdrop:bg-black/50">
    <h2 id={id} className="text-lg font-semibold">{title}</h2>
    <p id={`${id}-description`} className="mt-2 whitespace-pre-wrap break-words text-sm text-muted-foreground">{description}</p>
    <div className="mt-5 flex flex-wrap justify-end gap-2">
      <Button autoFocus variant="outline" onClick={onClose}>Go back</Button>
      <Button className="bg-destructive text-white hover:bg-destructive/90" onClick={onConfirm}>{action}</Button>
    </div>
  </dialog>
}

export function SuccessNotice({ message, dismiss }: { message: string; dismiss: () => void }) {
  return <div className="fixed right-4 bottom-4 z-50 flex max-w-[calc(100vw-2rem)] items-center gap-3 rounded-xl border bg-card p-4 shadow-lg">
    <p role="status" className="text-sm font-medium">{message}</p>
    <Button variant="ghost" size="sm" onClick={dismiss}>Dismiss</Button>
  </div>
}
