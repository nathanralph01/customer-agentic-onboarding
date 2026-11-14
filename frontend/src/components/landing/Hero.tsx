import { ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { RotatingGlobe } from './RotatingGlobe'

const STATS = [
  { value: '12 min', label: 'average time to onboard' },
  { value: '9 in 10', label: 'applications reviewed without rework' },
  { value: '100%', label: 'decisions with a full audit trail' },
]

export function Hero() {
  return <section aria-labelledby="hero-heading" className="relative isolate overflow-hidden">
    <div aria-hidden="true" className="absolute inset-0 -z-10 bg-[radial-gradient(60%_50%_at_75%_40%,oklch(0.93_0.05_255),transparent)]" />
    <div className="mx-auto grid max-w-6xl items-center gap-8 px-4 py-16 sm:px-6 md:grid-cols-2 md:py-24">
      <div>
        <p className="mb-4 inline-flex items-center rounded-full border bg-card px-3 py-1 text-sm font-medium text-primary">Agentic onboarding for business banking</p>
        <h1 id="hero-heading" className="text-4xl font-bold tracking-tight text-balance sm:text-6xl">Customer <span className="text-primary">360</span></h1>
        <p className="mt-4 text-2xl font-medium text-balance sm:text-3xl">Onboard business customers in minutes, not days.</p>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">AI agents assess risk, check Canadian regulations and draft the paperwork. Your team reviews every decision, with sources, before anything reaches the customer.</p>
        <div className="mt-8 flex flex-wrap gap-3"><Button size="lg" title="Coming soon">Start onboarding<ArrowRight aria-hidden="true" /></Button><Button size="lg" variant="outline" title="Coming soon">Book a demo</Button></div>
      </div>
      <div className="mx-auto w-full max-w-lg"><RotatingGlobe /></div>
    </div>
    <dl className="mx-auto grid max-w-6xl gap-6 px-4 sm:grid-cols-3 sm:px-6">
      {STATS.map(stat => <div key={stat.value} className="flex flex-col rounded-xl border bg-card p-5"><dt className="order-2 text-sm text-muted-foreground">{stat.label}</dt><dd className="text-3xl font-bold text-primary">{stat.value}</dd></div>)}
    </dl>
    <p className="mx-auto max-w-6xl px-4 pt-3 pb-12 text-xs text-muted-foreground sm:px-6">Illustrative demo metrics using synthetic data.</p>
  </section>
}
