import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import LandingPage from '@/pages/LandingPage'
import LoginPage from '@/pages/LoginPage'
import CustomerHomePage from '@/pages/CustomerHomePage'
import OnboardingPage from '@/pages/OnboardingPage'
import { ApplicationPage, CustomerCasePage, CustomerCasesPage } from '@/pages/CustomerWorkflowPages'
import { AdminCasePage, AdminCasesPage, GuardrailsPage } from '@/pages/AdminPages'
import { getPersona, type Persona } from '@/lib/api'

const queryClient = new QueryClient()

function WorkspaceRoutes() {
  const [persona, setPersona] = useState(getPersona)
  const navigate = useNavigate()

  function selectPersona(selected: Persona) {
    sessionStorage.setItem('customer360-persona', JSON.stringify(selected))
    queryClient.clear()
    setPersona(selected)
    navigate(selected.role === 'admin' ? '/admin' : '/customer', { replace: true })
  }

  function switchPersona() {
    sessionStorage.removeItem('customer360-persona')
    queryClient.clear()
    setPersona(null)
    navigate('/login')
  }

  const customer = persona?.role === 'customer'
  const admin = persona?.role === 'admin'
  const login = <Navigate to="/login" replace />

  return <Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/login" element={<LoginPage onLogin={selectPersona} />} />
    <Route path="/customer" element={customer ? <CustomerHomePage onLogout={switchPersona} /> : login} />
    <Route path="/customer/onboarding" element={customer ? <OnboardingPage onLogout={switchPersona} /> : login} />
    <Route path="/customer/apply" element={customer ? <ApplicationPage onLogout={switchPersona} /> : login} />
    <Route path="/customer/cases" element={customer ? <CustomerCasesPage onLogout={switchPersona} /> : login} />
    <Route path="/customer/cases/:id" element={customer ? <CustomerCasePage onLogout={switchPersona} /> : login} />
    <Route path="/admin" element={admin ? <AdminCasesPage onLogout={switchPersona} /> : login} />
    <Route path="/admin/reviews" element={admin ? <AdminCasesPage queue onLogout={switchPersona} /> : login} />
    <Route path="/admin/cases/:id" element={admin ? <AdminCasePage onLogout={switchPersona} /> : login} />
    <Route path="/admin/guardrails" element={admin ? <GuardrailsPage onLogout={switchPersona} /> : login} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}

export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter><WorkspaceRoutes /></BrowserRouter></QueryClientProvider>
}
