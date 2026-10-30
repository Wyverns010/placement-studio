import type { CampaignResult, Outcome } from '../types'
import { understoodChips } from './ReadingPanel'

function audienceChip(r: CampaignResult): string | null {
  const a = r.brief?.audience_type
  if (a === 'consumer') return 'B2C'
  if (a === 'business') return 'B2B'
  return null
}

const OUTCOME_BADGE: Record<Outcome, { text: string; cls: string }> = {
  proceed: { text: 'Proceed', cls: 'bg-ok-soft text-ok' },
  weak_fit: { text: 'Weak fit', cls: 'bg-warn-soft text-warn' },
  clarify: { text: 'Needs detail', cls: 'bg-warn-soft text-warn' },
  out_of_scope: { text: 'Out of scope', cls: 'bg-warn-soft text-warn' },
  no_signal: { text: 'No signal', cls: 'bg-warn-soft text-warn' },
}

export default function ResultHeader({
  result,
  onBack,
}: {
  result: CampaignResult
  onBack: () => void
}) {
  const chips = understoodChips(result)
  const aud = audienceChip(result)
  if (aud) chips.push(aud)
  const gate = result.gate
  const badge = OUTCOME_BADGE[result.outcome]
  const conf = gate ? Math.max(0, Math.min(1, gate.confidence)) : 0
  const thr = gate ? Math.max(0, Math.min(1, gate.threshold)) : 0
  return (
    <div className="flex flex-col gap-5 pt-7 pb-4 md:flex-row md:items-end md:justify-between md:gap-8 md:pt-9">
      <div className="min-w-0">
        <button type="button" className="pill pill-sm mb-4" onClick={onBack}>
          ← New campaign
        </button>
        <div className="text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
          Campaign for
        </div>
        <h2 className="m-0 mt-1.5 mb-2.5 max-w-[720px] text-xl leading-tight font-semibold tracking-[-0.02em] break-words sm:text-[28px]">
          “{result.input_text}”
        </h2>
        <div className="flex flex-wrap gap-y-1" aria-label="What we understood">
          {chips.map((c) => (
            <span key={c} className="blk">
              {c}
            </span>
          ))}
          {gate && <span className="blk">Model: {gate.impl === 'laya' ? 'Laya' : 'LLM'}</span>}
        </div>
      </div>
      {gate && (
        <div className="min-w-0 rounded-2xl border border-line bg-white p-3.5 md:min-w-[270px]">
          <div className="mb-2.5 flex justify-between text-[12.5px] text-muted">
            <span>Confidence gate ({gate.impl === 'laya' ? 'Laya' : 'LLM'})</span>
            <span className={`rounded-full px-[9px] py-[3px] text-[11.5px] font-semibold ${badge.cls}`}>
              {badge.text}
            </span>
          </div>
          <div className="relative h-2.5 rounded-full bg-[#e2dbef]">
            <i
              className="absolute inset-y-0 left-0 rounded-full"
              style={{ width: `${conf * 100}%`, background: 'linear-gradient(90deg,#c4b5fd,#7c3aed)' }}
            />
            <b className="absolute -top-[5px] h-5 w-0.5 bg-ink" style={{ left: `${thr * 100}%` }} />
          </div>
          <div className="mt-2 text-xs text-muted">
            {gate.confidence.toFixed(2)} — threshold {gate.threshold.toFixed(2)}
          </div>
        </div>
      )}
    </div>
  )
}
