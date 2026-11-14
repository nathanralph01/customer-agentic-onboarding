import { Link } from 'react-router-dom'
import { Button, buttonVariants } from '@/components/ui/button'

export function Header() {
  return <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur-sm">
    <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
      <a href="/" className="flex items-center gap-2 rounded-md font-semibold focus-visible:outline-2 focus-visible:outline-ring">
        <svg aria-hidden="true" viewBox="-3 -3 114.782 114.782" className="size-12 text-primary">
          <g transform="translate(-37.109 -210.359)" fill="none" stroke="currentColor" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M144.391,264.75c0,13.468-23.68,24.386-52.891,24.386S38.609,278.218,38.609,264.75c0-7.3,6.949-13.843,17.962-18.312" />
            <path d="M103.535,312.32c-3.635,3.408-7.719,5.321-12.035,5.321-15.187,0-27.5-23.68-27.5-52.891s12.312-52.891,27.5-52.891c7.372,0,14.066,5.579,19,14.662" />
            <path d="M49.662,244.042l6.909,2.4-2.4,6.909M112.166,219.4l-1.662,7.121-7.121-1.662" />
            <text x="91.5" y="264.75" textAnchor="middle" dominantBaseline="central" fill="currentColor" stroke="none" fontSize="18" fontWeight="700" letterSpacing="-0.5">C360</text>
          </g>
        </svg>
        <span className="text-lg tracking-tight">Customer 360</span>
      </a>
      <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
        {['Product', 'Pricing', 'Resources', 'Company'].map(item => <Button key={item} variant="ghost" title="Coming soon">{item}</Button>)}
      </nav>
      <div className="flex items-center gap-2"><Link to="/login" className={buttonVariants({ variant: 'ghost' })}>Log in</Link><Link to="/login" className={buttonVariants({ className: 'hidden sm:inline-flex' })}>Get started</Link></div>
    </div>
  </header>
}
