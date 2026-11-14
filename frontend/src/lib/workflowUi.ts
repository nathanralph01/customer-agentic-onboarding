export const input = 'w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
export const card = 'rounded-xl border bg-card p-5'
export const page = 'mx-auto max-w-6xl space-y-6 px-5 py-8 sm:px-8'
export const statusLabel = (value: string) => value.toLowerCase().replaceAll('_', ' ')
export const dateLabel = (value: string) => new Date(value).toLocaleString()
export const caseOpen = (status: string) => status !== 'ONBOARDED' && status !== 'CANCELLED'
