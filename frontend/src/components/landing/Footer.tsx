import { Button } from '@/components/ui/button'

export function CallToAction() {
  return <section aria-labelledby="cta-heading" className="px-4 pb-20 sm:px-6">
    <div className="mx-auto max-w-6xl rounded-2xl bg-primary px-6 py-14 text-center text-primary-foreground">
      <h2 id="cta-heading" className="text-3xl font-bold tracking-tight text-balance sm:text-4xl">See the full customer picture from day one</h2>
      <p className="mx-auto mt-3 max-w-xl text-primary-foreground/80">Watch an application move from first form to signed agreement.</p>
      <Button size="lg" variant="secondary" className="mt-8" title="Coming soon">Book a demo</Button>
    </div>
  </section>
}

export function Footer() {
  return <footer className="border-t"><div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:px-6">
    <p>&copy; 2026 Customer 360. Demo with synthetic data only.</p><p>Built with MongoDB Atlas, LangChain and Google Cloud.</p>
  </div></footer>
}
