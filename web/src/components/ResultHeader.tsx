import type { CampaignResult, Outcome } from '../types'
import { clamp01 } from '../format'
import { VIOLET, briefChips } from './ReadingPanel'
import { Chips, ThresholdBar } from './ui'

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
  displayText,
  onBack,
}: {
  result: CampaignResult
  displayText?: string
  onBack: () => void
}) {
  const chips = briefChips(result.brief)
  const aud = audienceChip(result)
  if (aud) chips.push(aud)
  const gate = result.gate
  const badge = OUTCOME_BADGE[result.outcome]
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
          “{displayText ?? result.input_text}”
        </h2>
        <div className="flex flex-wrap gap-y-1" aria-label="What we understood">
          <Chips items={chips} />
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
          <ThresholdBar fill={clamp01(gate.confidence) * 100} threshold={clamp01(gate.threshold)} gradient={VIOLET} />
          <div className="mt-2 text-xs text-muted">
            {gate.confidence.toFixed(2)} — threshold {gate.threshold.toFixed(2)}
          </div>
        </div>
      )}
    </div>
  )
}
