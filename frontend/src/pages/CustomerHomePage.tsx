import { Home, Plus, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'
import CustomerLayout from '@/components/CustomerLayout'

export default function CustomerHomePage({ onLogout }: { onLogout: () => void }) {
  return <CustomerLayout onLogout={onLogout}>
    <main id="main-content" className="px-[1.1rem] py-8 sm:px-[2.2rem] lg:px-[3.3rem] lg:py-12">
      <p className="flex items-center gap-2 text-sm font-medium text-primary"><Home className="size-4" aria-hidden="true" />Customer workspace</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">Welcome to your business hub</h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">Your next chapter starts here. Bring your business banking onboarding, documents and account information together.</p>

      <section aria-labelledby="start-heading" className="relative mt-8 overflow-hidden rounded-2xl bg-primary p-6 text-primary-foreground sm:p-9">
        <div aria-hidden="true" className="absolute -top-24 -right-20 size-80 rounded-full border-[40px] border-white/5" />
        <div className="relative max-w-xl">
          <p className="text-sm font-medium text-primary-foreground/80">LET’S GET YOU STARTED</p>
          <h2 id="start-heading" className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">A new beginning for your business</h2>
          <p className="mt-3 text-primary-foreground/85">Apply for business banking with a guided onboarding experience, from your first details to your final signature.</p>
          <Link to="/customer/onboarding" className={buttonVariants({ variant: 'secondary', size: 'lg', className: 'mt-6' })}><Plus aria-hidden="true" />Start onboarding</Link>
          <Link to="/customer/apply" className="ml-4 text-sm font-medium underline">Apply with a form</Link>
        </div>
      </section>

      <div className="mt-8 flex items-start gap-3 rounded-xl border bg-card p-5 text-sm text-muted-foreground"><ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" /><p><span className="font-medium text-foreground">Built around your business.</span> Your onboarding team will guide you through each step and let you know when anything needs your attention.</p></div>
    </main>
  </CustomerLayout>
}
