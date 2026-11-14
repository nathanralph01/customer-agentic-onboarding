import { Header } from '@/components/landing/Header'
import { Hero } from '@/components/landing/Hero'
import { Features } from '@/components/landing/Features'
import { Testimonials } from '@/components/landing/Testimonials'
import { CallToAction, Footer } from '@/components/landing/Footer'

export default function LandingPage() {
  return <><a href="#main" className="sr-only fixed top-2 left-2 z-[60] rounded-md bg-primary p-3 text-primary-foreground focus:not-sr-only">Skip to content</a><Header /><main id="main"><Hero /><Features /><Testimonials /><CallToAction /></main><Footer /></>
}
