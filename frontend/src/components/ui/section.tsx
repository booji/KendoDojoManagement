import type { ReactNode } from "react"

interface SectionProps {
  heading: string
  children: ReactNode
}

const Section = ({ heading, children }: SectionProps) => {
  return (
    <section data-slot="section" className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">{heading}</h2>
      {children}
    </section>
  )
}

export { Section }
export type { SectionProps }
