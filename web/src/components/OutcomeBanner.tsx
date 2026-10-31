import type { ReactNode } from 'react'
import { clamp01 } from '../format'
import type { GateResult } from '../types'
import { ThresholdBar } from './ui'

export type BannerVariant = 'amber' | 'neutral' | 'error'

const STYLES: Record<BannerVariant, string> = {
  amber: 'border-[#F0D9B2] bg-[#FBEFDC] text-[#5B4520]',
  neutral: 'border-[#e6c7cd] bg-[#fbeff1] text-[#5a2630]',
  error: 'border-[#e6a9b3] bg-[#fdecef] text-[#7a1f30]',
}

export default function OutcomeBanner({
  variant,
  title,
  children,
  gate,
}: {
  variant: BannerVariant
  title: string
  children?: ReactNode
  gate?: GateResult | null
}) {
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={`rounded-[18px] border px-5 py-4 ${STYLES[variant]}`}
    >
      <h3 className="m-0 mb-1 text-base font-semibold">{title}</h3>
      {children && <div className="text-[13.5px] leading-normal">{children}</div>}
      {gate && (
        <ThresholdBar
          fill={clamp01(gate.confidence) * 100}
          threshold={clamp01(gate.threshold)}
          gradient="linear-gradient(90deg,#f3c98a,#c27a12)"
          className="mt-3 bg-[#f0dfbf]"
          hidden
        />
      )}
    </div>
  )
}
