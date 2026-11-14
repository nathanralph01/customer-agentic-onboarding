import { BrainCircuit, FileCheck2, Radar, Scale, ScrollText, UserCheck, type LucideIcon } from 'lucide-react'

const FEATURES: { icon: LucideIcon; title: string; text: string }[] = [
  { icon: Radar, title: 'Risk, explained', text: 'A risk map that scores each category and cites the sources behind every rating.' },
  { icon: Scale, title: 'Compliance built in', text: 'Checks against FINTRAC, PCMLTFA, PIPEDA and OSFI guidance, automatically.' },
  { icon: FileCheck2, title: 'Documents drafted for you', text: 'Agreements are generated, reviewed and ready to e-sign in one flow.' },
  { icon: UserCheck, title: 'Humans decide', text: 'Agents recommend. Your reviewers approve, pause, or ask for more information.' },
  { icon: BrainCircuit, title: 'Picks up where it left off', text: 'Customers can leave and return days later. The workflow resumes with full context.' },
  { icon: ScrollText, title: 'Guardrails that learn', text: 'Overrides become proposed rules. Nothing changes without your approval.' },
]

export function Features() {
  return <section aria-labelledby="features-heading" className="bg-muted/50 py-20">
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <h2 id="features-heading" className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">One workflow from application to account</h2>
      <p className="mt-3 max-w-2xl text-lg text-muted-foreground">Apply, verify, assess risk, check compliance, generate documents, review, sign, onboard.</p>
      <ul className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ icon: Icon, title, text }) => <li key={title} className="rounded-xl border bg-card p-6 shadow-xs">
          <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-primary"><Icon className="size-5" aria-hidden="true" /></span>
          <h3 className="mt-4 text-lg font-semibold">{title}</h3><p className="mt-2 text-muted-foreground">{text}</p>
        </li>)}
      </ul>
    </div>
  </section>
}
