import { Quote } from 'lucide-react'

const TESTIMONIALS = [
  { quote: 'We used to wait nine days for a business account to open. With Customer 360 our clients are onboarded before their coffee gets cold.', name: 'Priya Raman', role: 'Head of Commercial Banking, Northern Harbour Bank' },
  { quote: 'Every risk rating comes with sources I can check. My compliance team trusts it because it shows its work.', name: 'Daniel Okafor', role: 'Chief Compliance Officer, Maple Ridge Credit Union' },
  { quote: 'I started an application on Friday, was missing a document, and finished on Tuesday. It remembered everything.', name: 'Sophie Tremblay', role: 'Owner, Tremblay & Fils Construction' },
]

export function Testimonials() {
  return <section aria-labelledby="testimonials-heading" className="py-20">
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <h2 id="testimonials-heading" className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">Trusted by banks and the businesses they serve</h2>
      <p className="mt-3 text-sm text-muted-foreground">Illustrative stories. Names, organizations and testimonials are fictional.</p>
      <ul className="mt-12 grid gap-6 md:grid-cols-3">
        {TESTIMONIALS.map(t => <li key={t.name}><figure className="flex h-full flex-col rounded-xl border bg-card p-6 shadow-xs">
          <Quote className="size-6 text-primary" aria-hidden="true" /><blockquote className="mt-4 flex-1 text-lg">{t.quote}</blockquote>
          <figcaption className="mt-6 flex items-center gap-3">
            <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent font-semibold text-accent-foreground">{t.name.split(' ').map(part => part[0]).join('')}</span>
            <span><span className="block font-semibold">{t.name}</span><span className="block text-sm text-muted-foreground">{t.role}</span></span>
          </figcaption>
        </figure></li>)}
      </ul>
    </div>
  </section>
}
