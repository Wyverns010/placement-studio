import { pct } from '../format'
// Small presentational pieces shared by more than one view.
import type { PublisherScore } from '../types'

export function Chips({ items }: { items: string[] }) {
  return (
    <>
      {items.map((t) => (
        <span key={t} className="blk">
          {t}
        </span>
      ))}
    </>
  )
}

export function Busy({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="spinner" aria-hidden="true" />
      {label}
    </span>
  )
}

/** Confidence track: a fill up to `fill` percent (none when null) and a tick at `threshold` (0-1). */
export function ThresholdBar({
  fill,
  threshold,
  gradient,
  className = 'bg-[#e2dbef]',
  fillClassName = '',
  tickTitle,
  hidden,
}: {
  fill: number | null
  threshold: number
  gradient: string
  className?: string
  fillClassName?: string
  tickTitle?: string
  hidden?: boolean
}) {
  return (
    <div className={`relative h-2.5 rounded-full ${className}`} aria-hidden={hidden || undefined}>
      {fill != null && (
        <i
          className={`${fillClassName}absolute inset-y-0 left-0 rounded-full`}
          style={{ width: `${fill}%`, background: gradient }}
        />
      )}
      <b className="absolute -top-[5px] h-5 w-0.5 bg-ink" style={{ left: `${threshold * 100}%` }} title={tickTitle} />
    </div>
  )
}

export function ExcludedCard({ pub }: { pub: PublisherScore }) {
  return (
    <div
      data-testid="excluded"
      className="mb-2 rounded-[14px] border border-dashed border-[#d6cde6] px-3.5 py-3 text-[12.5px]"
    >
      <span className="float-right text-[11.5px] font-semibold text-bad">{pct(pub.fit)}</span>
      <b className="text-[13.5px]">{pub.name}</b>
      <p className="m-0 mt-1 leading-snug text-muted">{pub.reason}</p>
    </div>
  )
}

export interface StageErr {
  message: string
  /** 403: the stage-1 result changed or expired, so the fix is to run stage 1 again. */
  expired: boolean
}

/** Inline error for a stage-2/3 request; offers "Run it again" when the campaign expired. */
export function StageError({ err, onRerun, compact }: { err: StageErr; onRerun?: () => void; compact?: boolean }) {
  return (
    <div
      role="alert"
      className={`rounded-xl border border-[#e6a9b3] bg-[#fdecef] text-[#7a1f30] ${
        compact ? 'px-3 py-2 text-[12.5px]' : 'px-4 py-3 text-[13.5px]'
      } leading-snug`}
    >
      {err.message}
      {err.expired && onRerun && (
        <button type="button" className="pill pill-sm ml-2 align-middle" onClick={onRerun}>
          Run it again
        </button>
      )}
    </div>
  )
}
