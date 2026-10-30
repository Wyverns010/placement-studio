import { useState } from 'react'
import type { CampaignResult, Sample } from '../types'
import { formatBudget, parseBudget } from '../format'
import ReadingPanel from './ReadingPanel'

interface Props {
  samples: Sample[]
  text: string
  budget: number
  running: boolean
  error: string | null
  lastResult: CampaignResult | null
  onTextChange: (t: string) => void
  onBudgetChange: (n: number) => void
  onRun: () => void
  onPickSample: (s: Sample) => void
}

export default function Landing(p: Props) {
  const [showAll, setShowAll] = useState(false)
  const visible = showAll ? p.samples : p.samples.slice(0, 8)
  const canRun = !p.running && p.text.trim().length > 0 && p.budget > 0

  return (
    <section className="grid items-center gap-10 pt-10 pb-16 min-[900px]:grid-cols-[1fr_1.05fr] min-[900px]:gap-12 min-[900px]:pt-14 min-[900px]:pb-[70px]">
      <div className="min-w-0">
        <h1 className="m-0 mb-4 text-[38px] leading-[1.04] font-bold tracking-[-0.03em] sm:text-[54px] sm:leading-[1.02]">
          Describe your brand.
          <br />
          We'll find your shoppers.
        </h1>
        <p className="m-0 max-w-[460px] text-[17px] leading-normal text-muted sm:text-lg">
          One sentence in. Ranked publishers, persona-tuned creatives and a launch-ready campaign
          config out — with every decision explained.
        </p>

        <form
          className="mt-6 rounded-input border border-line bg-white p-4"
          style={{ boxShadow: '0 10px 30px -18px #3b1d7a55' }}
          onSubmit={(e) => {
            e.preventDefault()
            if (canRun) p.onRun()
          }}
        >
          <label htmlFor="brand-text" className="sr-only">
            Describe your brand
          </label>
          <textarea
            id="brand-text"
            value={p.text}
            onChange={(e) => p.onTextChange(e.target.value)}
            rows={3}
            placeholder="What do you sell, and to whom?"
            className="block h-[84px] w-full resize-none border-0 bg-transparent text-[15px] leading-normal text-ink outline-none placeholder:text-muted"
            style={{ font: '15px/1.5 Inter, sans-serif' }}
          />
          {p.error && (
            <p role="alert" className="mt-2 mb-0 text-[13px] leading-snug text-bad">
              {p.error}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <label className="flex items-center gap-1.5 text-[12.5px] text-muted">
              Monthly budget
              <span className="flex items-center rounded-lg border border-line bg-card px-2 py-1 font-semibold text-ink focus-within:border-violet">
                $
                <input
                  aria-label="Monthly budget in USD"
                  inputMode="numeric"
                  value={formatBudget(p.budget)}
                  onChange={(e) => p.onBudgetChange(parseBudget(e.target.value))}
                  className="w-[78px] border-0 bg-transparent pl-0.5 font-[inherit] text-[13px] outline-none"
                />
              </span>
            </label>
            <button type="submit" className="pill pill-primary" disabled={!canRun}>
              {p.running ? (
                <span className="inline-flex items-center gap-2">
                  <span className="spinner" aria-hidden="true" />
                  Reading your brand…
                </span>
              ) : (
                'Build campaign →'
              )}
            </button>
          </div>
        </form>

        <div className="mt-3.5 flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] text-muted">Try:</span>
          {visible.map((s) => (
            <button
              key={s.id}
              type="button"
              className="chip"
              disabled={p.running}
              onClick={() => p.onPickSample(s)}
            >
              {s.label}
            </button>
          ))}
          {p.samples.length > 8 && (
            <button
              type="button"
              className="border-0 bg-transparent p-1 text-[12.5px] font-semibold text-violet-dark"
              onClick={() => setShowAll((v) => !v)}
            >
              {showAll ? 'Show fewer' : `+${p.samples.length - 8} more`}
            </button>
          )}
        </div>
      </div>

      <ReadingPanel result={p.lastResult} />
    </section>
  )
}
