import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Building2, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { listPersonas, type Persona } from '@/lib/api'

export default function LoginPage({ onLogin }: { onLogin: (persona: Persona) => void }) {
  const { data, isPending, error, refetch } = useQuery({ queryKey: ['personas'], queryFn: listPersonas })

  return <main className="flex min-h-screen items-center justify-center bg-muted/40 px-4 py-12">
    <div className="w-full max-w-lg rounded-2xl border bg-card p-8 shadow-sm">
      <Link to="/" className="font-semibold text-primary hover:underline">Customer 360</Link>
      <h1 className="mt-7 text-3xl font-bold tracking-tight">Choose a demo persona</h1>
      <p className="mt-2 text-sm text-muted-foreground">Use synthetic data in the customer and bank workspaces.</p>
      <div className="mt-6 grid gap-3">
        {isPending && <p role="status">Loading personas…</p>}
        {error && <><p role="alert" className="text-destructive">{error.message}</p><Button variant="outline" onClick={() => refetch()}>Try again</Button></>}
        {data?.map(persona => {
          const Icon = persona.role === 'customer' ? Building2 : ShieldCheck
          return <button key={persona.id} type="button" onClick={() => onLogin(persona)} className="flex items-center gap-4 rounded-xl border p-4 text-left hover:border-primary hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">
            <Icon className="size-6 text-primary" aria-hidden="true" />
            <span className="flex-1"><strong className="block">{persona.name}</strong><span className="text-sm text-muted-foreground">{persona.role === 'admin' ? 'Bank reviewer' : 'Business customer'}</span></span>
            <ArrowRight className="size-4" aria-hidden="true" />
          </button>
        })}
      </div>
    </div>
  </main>
}
