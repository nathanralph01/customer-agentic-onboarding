const API_URL = (import.meta.env.VITE_API_URL || '/api/v1').replace(/\/$/, '')

export async function login(): Promise<boolean> {
  const response = await fetch(`${API_URL}/login`, { method: 'POST' })
  if (!response.ok) throw new Error('Unable to log in. Please try again.')
  const result: unknown = await response.json()
  if (result !== true) throw new Error('Login was not successful. Please try again.')
  return result
}
