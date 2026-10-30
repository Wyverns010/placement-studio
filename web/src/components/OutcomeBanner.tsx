import type { ReactNode } from 'react'
import type { GateResult } from '../types'

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
  const conf = gate ? Math.max(0, Math.min(1, gate.confidence)) : 0
  const thr = gate ? Math.max(0, Math.min(1, gate.threshold)) : 0
  return (
    <div
      role={variant === 'error' ? 'alert' : 'status'}
      className={`rounded-[18px] border px-5 py-4 ${STYLES[variant]}`}
    >
      <h3 className="m-0 mb-1 text-base font-semibold">{title}</h3>
      {children && <div className="text-[13.5px] leading-normal">{children}</div>}
      {gate && (
        <div className="relative mt-3 h-2.5 rounded-full bg-[#f0dfbf]" aria-hidden="true">
          <i
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${conf * 100}%`, background: 'linear-gradient(90deg,#f3c98a,#c27a12)' }}
          />
          <b className="absolute -top-[5px] h-5 w-0.5 bg-ink" style={{ left: `${thr * 100}%` }} />
        </div>
      )}
    </div>
  )
}
