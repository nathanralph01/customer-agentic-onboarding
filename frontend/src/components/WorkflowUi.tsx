import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { Case, CaseDocument } from '@/lib/api'
import { Button } from '@/components/ui/button'

import { card, dateLabel, statusLabel } from '@/lib/workflowUi'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="grid gap-1.5 text-sm font-medium">{label}{children}</label>
}

export function RequestStatus({ pending, error }: { pending?: boolean; error?: Error | null }) {
  return <>{pending && <p role="status" className="text-sm text-muted-foreground">Loading…</p>}
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

export function Documents({ documents, download }: { documents: CaseDocument[]; download: (item: CaseDocument) => void }) {
  if (!documents.length) return <p className="text-sm text-muted-foreground">No documents yet.</p>
  return <ul className="divide-y">{documents.map(document => <li key={document.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
    <div className="min-w-0 break-all"><p className="text-sm font-medium">{document.filename}</p><p className="text-xs capitalize text-muted-foreground">{document.source}</p>{document.coverNote && <p className="mt-1 break-words text-xs text-muted-foreground">{document.coverNote}</p>}</div>
    <Button variant="outline" size="sm" onClick={() => download(document)} aria-label={`Download ${document.filename}`}>Download</Button>
  </li>)}</ul>
}
