import { useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import LandingPage from '@/pages/LandingPage'
import LoginPage from '@/pages/LoginPage'
import CustomerHomePage from '@/pages/CustomerHomePage'
import OnboardingPage from '@/pages/OnboardingPage'

export default function App() {
  const [loggedIn, setLoggedIn] = useState(() => sessionStorage.getItem('customer-demo') === 'true')

  function handleLogin() {
    sessionStorage.setItem('customer-demo', 'true')
    setLoggedIn(true)
  }

  function handleLogout() {
    sessionStorage.removeItem('customer-demo')
    setLoggedIn(false)
  }

  return <BrowserRouter><Routes>
    <Route path="/" element={<LandingPage />} />
    <Route path="/login" element={loggedIn ? <Navigate to="/customer" replace /> : <LoginPage onLogin={handleLogin} />} />
    <Route path="/customer" element={loggedIn ? <CustomerHomePage onLogout={handleLogout} /> : <Navigate to="/login" replace />} />
    <Route path="/customer/onboarding" element={loggedIn ? <OnboardingPage onLogout={handleLogout} /> : <Navigate to="/login" replace />} />
  </Routes></BrowserRouter>
}
