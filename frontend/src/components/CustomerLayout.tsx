import type { ReactNode } from 'react'
import { ClipboardList, Home, Plus, Users } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { getPersona } from '@/lib/api'

const navigation = [
  { to: '/customer', icon: Home, label: 'Overview' },
  { to: '/customer/onboarding', icon: Plus, label: 'Start onboarding' },
  { to: '/customer/cases', icon: ClipboardList, label: 'Track onboarding' },
]

export default function CustomerLayout({ children, onLogout, onboarding = false }: { children: ReactNode; onLogout: () => void; onboarding?: boolean }) {
  return <div className="min-h-screen bg-muted/40">
    <header className="border-b bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <Link to="/customer" className="flex items-center gap-2 font-semibold tracking-tight"><span className="flex size-9 items-center justify-center rounded-lg bg-primary text-xs font-bold text-primary-foreground">C360</span>Customer 360</Link>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{getPersona()?.name}</span>
          <Button variant="ghost" onClick={onLogout}><Users aria-hidden="true" />Switch persona</Button>
        </div>
      </div>
    </header>
    <div className="grid md:min-h-[calc(100vh-73px)] md:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="border-b bg-card p-4 md:border-r md:border-b-0 md:py-8">
        <nav aria-label="Customer workspace" className="grid gap-1">
          {navigation.map(({ to, icon: Icon, label }) => <NavLink key={to} to={to} end={to === '/customer'} className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-semibold focus-visible:ring-2 focus-visible:ring-ring ${isActive || (onboarding && to.endsWith('/onboarding')) ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-muted'}`
          }><Icon className="size-5" aria-hidden="true" />{label}</NavLink>)}
        </nav>
      </aside>
      <div className="min-w-0">{children}</div>
    </div>
  </div>
}
