import { useState } from 'react'
import type { CampaignResult } from '../types'
import OutcomeBanner from './OutcomeBanner'

const OTHER = 'Other…'
const MAX_LEN = 200
// Whole-option variants only: "Other", "Other…", "Other (please specify)", "Something else".
export const OTHER_VARIANT = /^(other|something else)\s*(\(.*\))?\s*(…|\.{3})?$/i

type Pick = { kind: 'option'; value: string } | { kind: 'other'; text: string }

function BestGuess({ result }: { result: CampaignResult }) {
  const top = [...result.publishers].sort((a, b) => b.fit - a.fit).slice(0, 3)
  const persona = result.personas[0]
  const chips = result.brief
    ? [
        result.brief.product && `Product: ${result.brief.product}`,
        result.brief.categories[0] && `Category: ${result.brief.categories[0]}`,
        result.brief.audience_type !== 'unclear' && `Audience: ${result.brief.audience_type}`,
      ].filter((c): c is string => !!c)
    : []
  return (
    <aside
      aria-label="Best guess so far"
      className="rounded-card border border-line bg-white p-5 opacity-75 saturate-50"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="m-0 text-base font-semibold">Best guess so far</h3>
        <span className="rounded-full bg-warn-soft px-2.5 py-1 text-[11.5px] font-semibold text-warn">
          low confidence — not launchable
        </span>
      </div>
      {chips.length > 0 && (
        <div className="mb-3">
          <div className="mb-1 text-[11.5px] font-semibold tracking-[0.06em] text-muted uppercase">Understood</div>
          {chips.map((c) => (
            <span key={c} className="blk">
              {c}
            </span>
          ))}
        </div>
      )}
      {persona && (
        <div className="mb-3">
          <div className="mb-1 text-[11.5px] font-semibold tracking-[0.06em] text-muted uppercase">Likely persona</div>
          <span className="blk">{persona.name}</span>
        </div>
      )}
      <div className="text-[11.5px] font-semibold tracking-[0.06em] text-muted uppercase">Tentative</div>
      {top.map((p) => (
        <div key={p.publisher_id} className="mt-2 grid grid-cols-[96px_1fr_36px] items-center gap-2 text-[12.5px]">
          <span className="truncate">{p.name}</span>
          <i className="relative block h-[7px] overflow-hidden rounded-full bg-[#e9e3f5]">
            <span
              className="absolute inset-y-0 left-0 rounded-full bg-violet"
              style={{ width: `${Math.max(0, Math.min(1, p.fit)) * 100}%` }}
            />
          </i>
          <span className="text-right text-muted">{p.fit.toFixed(2)}</span>
        </div>
      ))}
      <p className="m-0 mt-4 text-[12.5px] text-muted">No budget or config until confidence clears.</p>
    </aside>
  )
}

export default function ClarifyView({
  result,
  onRebuild,
  rebuilding = false,
}: {
  result: CampaignResult
  onRebuild: (answers: Record<string, string>) => void
  rebuilding?: boolean
}) {
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const noSignal = result.outcome === 'no_signal'

  const answers: Record<string, string> = {}
  for (const [q, p] of Object.entries(picks)) {
    const v = (p.kind === 'other' ? p.text : p.value).trim()
    if (v) answers[q] = v
  }
  const canRebuild = Object.keys(answers).length > 0 && !rebuilding

  return (
    <div className="grid gap-[22px] pb-20 min-[900px]:grid-cols-[1.2fr_1fr]">
      <div className="min-w-0">
        <OutcomeBanner
          variant="amber"
          title={noSignal ? 'Nothing to go on yet.' : 'We need a bit more before spending your budget.'}
          gate={result.gate}
        >
          {noSignal ? (
            'Tell us a little about what you sell and we will build from there.'
          ) : result.gate ? (
            <>
              Confidence <b>{result.gate.confidence.toFixed(2)}</b> / {result.gate.threshold.toFixed(2)}. Answer a
              few questions and we will rebuild.
            </>
          ) : (
            result.message
          )}
        </OutcomeBanner>

        {result.clarify.map((q) => {
          const pick = picks[q.question]
          return (
            <fieldset key={q.question} className="m-0 mt-5 min-w-0 border-0 p-0">
              <legend className="mb-2 p-0 text-[14px] font-semibold">{q.question}</legend>
              <div className="flex flex-wrap gap-2">
                {[...q.options.filter((o) => !OTHER_VARIANT.test(o.trim())), OTHER].map((opt) => {
                  const isOther = opt === OTHER
                  const selected = isOther ? pick?.kind === 'other' : pick?.kind === 'option' && pick.value === opt
                  return (
                    <button
                      key={opt}
                      type="button"
                      aria-pressed={selected}
                      className={`chip ${selected ? 'border-violet! bg-violet-soft! font-semibold text-violet-dark!' : ''}`}
                      onClick={() =>
                        setPicks((s) => ({
                          ...s,
                          [q.question]: isOther
                            ? { kind: 'other', text: s[q.question]?.kind === 'other' ? (s[q.question] as { text: string }).text : '' }
                            : { kind: 'option', value: opt },
                        }))
                      }
                    >
                      {opt}
                    </button>
                  )
                })}
              </div>
              {pick?.kind === 'other' && (
                <input
                  type="text"
                  maxLength={MAX_LEN}
                  aria-label={`Your answer: ${q.question}`}
                  placeholder="Type your answer"
                  value={pick.text}
                  onChange={(e) => setPicks((s) => ({ ...s, [q.question]: { kind: 'other', text: e.target.value } }))}
                  className="mt-2 w-full rounded-xl border border-line bg-white px-3 py-2 text-[13.5px] outline-none focus:border-violet"
                />
              )}
            </fieldset>
          )
        })}

        <button
          type="button"
          className="pill pill-primary mt-6"
          disabled={!canRebuild}
          onClick={() => onRebuild(answers)}
        >
          {rebuilding ? (
            <span className="inline-flex items-center gap-2">
              <span className="spinner" aria-hidden="true" />
              Rebuilding…
            </span>
          ) : (
            'Rebuild campaign →'
          )}
        </button>
      </div>
      {!noSignal && <BestGuess result={result} />}
    </div>
  )
}
