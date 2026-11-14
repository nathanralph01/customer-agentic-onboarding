import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { login } from '@/lib/api'

export default function LoginPage({ onLogin }: { onLogin: () => void }) {
  const navigate = useNavigate()
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  async function handleLogin() {
    setPending(true)
    setError('')
    try {
      await login()
      onLogin()
      navigate('/customer', { replace: true })
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Unable to log in. Please try again.')
    } finally {
      setPending(false)
    }
  }

  return <main className="flex min-h-screen items-center justify-center px-4 py-12">
    <div className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-sm">
      <Link to="/" className="font-semibold text-primary underline-offset-4 hover:underline">Customer 360</Link>
      <span className="mt-8 flex size-12 items-center justify-center rounded-xl bg-accent text-primary"><Building2 aria-hidden="true" /></span>
      <h1 className="mt-5 text-3xl font-bold tracking-tight">Welcome back</h1>
      <p className="mt-3 text-muted-foreground">Enter your customer workspace to manage your business banking onboarding.</p>
      <div className="my-6 rounded-lg border bg-muted/50 p-4 text-sm"><p className="font-medium">Customer demo</p><p className="mt-1 text-muted-foreground">No password needed. Login is mocked for this demo.</p></div>
      {error && <p role="alert" className="mb-4 text-sm text-destructive">{error}</p>}
      <Button className="w-full" size="lg" disabled={pending} onClick={handleLogin}>{pending ? 'Logging in…' : 'Log in as customer'}<ArrowRight aria-hidden="true" /></Button>
      <Link to="/" className="mt-5 block text-center text-sm text-muted-foreground underline-offset-4 hover:underline">Back to website</Link>
    </div>
  </main>
}
