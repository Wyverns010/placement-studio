import { useState } from 'react'
import { budgetProblem, formatBudget, humanise, parseOptionalBudget, usd } from '../format'
import type { CampaignConfig, Creative, PersonaScore, PublisherScore } from '../types'
import ConfigTab from './ConfigTab'
import { Busy, StageError, type StageErr } from './ui'

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/**
 * "Recommended $6,000/mo: $41 target CPA × 50 …" → "$41 target CPA × 50 …".
 * Falls back to the whole line when it doesn't have that shape.
 */
function budgetBasis(rationale: string | undefined): string | null {
  if (!rationale) return null
  const m = /^Recommended [^:]*:\s*(.+)$/s.exec(rationale)
  // The backend's line already says "You set $Y/mo, which is used instead" for a user budget.
  return humanise((m ? m[1] : rationale).trim())
}

/** Step 3: the budget (prefilled, editable, re-requests stage 3) above the Formatted | JSON config. */
export default function ConfigStep({
  config,
  publishers,
  personas,
  creatives,
  busy,
  error,
  onRerun,
  onBudget,
}: {
  config: CampaignConfig
  publishers: PublisherScore[]
  personas: PersonaScore[]
  creatives: Creative[]
  busy: boolean
  error: StageErr | null
  onRerun?: () => void
  onBudget: (usd: number | null) => void
}) {
  const b = config.budget
  const monthly = num(b.monthly_usd)
  const recommended = num(b.recommended_usd)
  const isUser = b.source === 'user'
  const [value, setValue] = useState<number | null>(monthly)
  // Re-sync the field whenever a new config arrives (state derived from props, no effect).
  const [seen, setSeen] = useState(config)
  if (seen !== config) {
    setSeen(config)
    setValue(monthly)
  }
  const problem = budgetProblem(value)
  const changed = value != null && value !== monthly
  const basis = budgetBasis(config.rationales?.budget)

  return (
    <>
      <form
        className="mb-5 rounded-2xl border border-line bg-white px-[18px] py-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!busy && !problem && value != null) onBudget(value)
        }}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <label className="flex items-center gap-2 text-[13px] text-muted">
            Monthly budget
            <span
              className={`flex items-center rounded-lg border bg-card px-2.5 py-1.5 text-[15px] font-semibold text-ink focus-within:border-violet ${
                problem ? 'border-bad' : 'border-line'
              }`}
            >
              $
              <input
                aria-label="Monthly budget in USD"
                aria-invalid={problem ? true : undefined}
                aria-describedby="config-budget-basis"
                inputMode="numeric"
                value={formatBudget(value)}
                onChange={(e) => setValue(parseOptionalBudget(e.target.value))}
                className="w-[96px] border-0 bg-transparent pl-0.5 font-[inherit] outline-none"
              />
            </span>
          </label>
          <button type="submit" className="pill pill-sm" disabled={busy || !!problem || value == null || !changed}>
            {busy ? <Busy label="Updating…" /> : 'Update'}
          </button>
          <span
            data-testid="budget-source"
            className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${
              isUser ? 'bg-violet-soft text-violet-dark' : 'bg-ok-soft text-ok'
            }`}
          >
            {isUser ? 'Yours' : 'Recommended'}
          </span>
          {isUser && recommended != null && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onBudget(null)}
              className="cursor-pointer border-0 bg-transparent p-0 text-[12.5px] font-semibold text-violet-dark disabled:opacity-50"
            >
              Use recommended ({usd(recommended)})
            </button>
          )}
        </div>
        <p id="config-budget-basis" className="m-0 mt-2.5 text-[12.5px] leading-snug text-muted">
          {problem ? (
            <span className="text-bad">{problem}</span>
          ) : recommended != null ? (
            <span>
              {`Recommended ${usd(recommended)}${basis ? ` — based on ${basis}` : ''}`}
            </span>
          ) : (
            basis
          )}
        </p>
        {error && (
          <div className="mt-3">
            <StageError err={error} onRerun={onRerun} compact />
          </div>
        )}
      </form>
      <div className={busy ? 'opacity-60 transition-opacity' : 'transition-opacity'} aria-busy={busy || undefined}>
        <ConfigTab config={config} publishers={publishers} personas={personas} creatives={creatives} />
      </div>
    </>
  )
}
