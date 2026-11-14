import type * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

// Shared with future link-style actions.
// eslint-disable-next-line react-refresh/only-export-components
export const buttonVariants = cva('cursor-pointer inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0', {
  variants: {
    variant: {
      default: 'bg-primary text-primary-foreground shadow-xs hover:bg-primary/90',
      outline: 'border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground',
      secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
      ghost: 'hover:bg-accent hover:text-accent-foreground',
    },
    size: { default: 'h-9 px-4 py-2', sm: 'h-8 px-3', lg: 'h-11 px-6 text-base' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
})

type ButtonProps = React.ComponentProps<'button'> & VariantProps<typeof buttonVariants>

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button type="button" className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
