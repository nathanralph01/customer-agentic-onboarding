import type { ReactNode } from 'react'
import { Building2, CircleHelp, ClipboardList, FileText, Home, LogOut, Plus, Settings2, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

const OPTIONS = [
  { icon: ClipboardList, title: 'Past onboardings', description: 'Find previous applications and completed onboarding details.' },
  { icon: FileText, title: 'Documents', description: 'Keep your uploaded files and banking agreements in one place.' },
  { icon: Building2, title: 'Business profile', description: 'Manage your company details and business information.' },
  { icon: Users, title: 'People & access', description: 'Review business owners, representatives and account access.' },
  { icon: Settings2, title: 'Account settings', description: 'Manage your contact details and communication preferences.' },
  { icon: CircleHelp, title: 'Help & support', description: 'Find guidance and contact your onboarding team.' },
]

export default function CustomerLayout({ children, onLogout, onboarding = false }: { children: ReactNode; onLogout: () => void; onboarding?: boolean }) {
  return <div className="min-h-screen bg-muted/40">
    <header className="border-b bg-card">
      <div className="flex w-full flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <Link to="/customer" className="flex items-center gap-2 font-semibold tracking-tight"><span className="flex size-9 items-center justify-center rounded-lg bg-primary text-xs font-bold text-primary-foreground">C360</span><span>Customer 360</span></Link>
        <div className="flex items-center gap-3">
          <span className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground">Customer demo</span>
          <Button variant="ghost" onClick={onLogout}><LogOut aria-hidden="true" />Log out</Button>
        </div>
      </div>
    </header>
    <div className="grid w-full md:min-h-[calc(100vh-73px)] md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="border-b bg-card px-4 py-6 md:border-r md:border-b-0 md:px-5 md:py-8">
        <nav aria-label="Customer workspace">
          <p className="mb-4 px-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Your workspace</p>
          <Link to="/customer" aria-current={onboarding ? undefined : 'page'} className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-3 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring ${onboarding ? 'text-muted-foreground hover:bg-muted' : 'bg-accent text-primary'}`}><Home className="size-5" aria-hidden="true" />Overview</Link>
          <Link to="/customer/onboarding" aria-current={onboarding ? 'page' : undefined} className={`mt-1 flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring ${onboarding ? 'bg-accent text-primary' : 'text-muted-foreground hover:bg-muted'}`}><Plus className="size-5" aria-hidden="true" />Start onboarding</Link>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2 md:grid-cols-1">
            {OPTIONS.map(({ icon: Icon, title, description }) => <li key={title}>
              <button type="button" disabled title={description} className="flex w-full cursor-default items-center gap-3 rounded-lg px-3 py-3 text-left text-sm text-muted-foreground">
                <Icon className="size-5 shrink-0" aria-hidden="true" />
                <span>{title}</span>
              </button>
            </li>)}
          </ul>
          <p className="mt-5 border-t px-3 pt-5 text-xs leading-5 text-muted-foreground">More workspace features are coming soon.</p>
        </nav>
      </aside>
      <div className="min-w-0">
        {children}
        <footer className="px-[1.1rem] pb-8 text-xs text-muted-foreground sm:px-[2.2rem] lg:px-[3.3rem]">Customer 360 · Demo workspace with synthetic data only.</footer>
      </div>
    </div>
  </div>
}
