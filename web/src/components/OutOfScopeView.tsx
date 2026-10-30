import { useState } from 'react'
import type { CampaignResult, Sample } from '../types'
import OutcomeBanner from './OutcomeBanner'

const SAMPLE_LABELS = ['Senior dog food', 'Vermont candles', 'Protein bars']

export function pickSampleChips(samples: Sample[]): Sample[] {
  const named = SAMPLE_LABELS.map((l) => samples.find((s) => s.label === l)).filter((s): s is Sample => !!s)
  return named.length ? named : samples.slice(0, 3)
}

export default function OutOfScopeView({
  result,
  samples,
  onPickSample,
}: {
  result: CampaignResult
  samples: Sample[]
  onPickSample: (s: Sample) => void
}) {
  const [showAll, setShowAll] = useState(false)
  const excluded = [...result.publishers].sort((a, b) => b.fit - a.fit)
  const shown = showAll ? excluded : excluded.slice(0, 6)
  const more = excluded.length - 6
  const chips = pickSampleChips(samples)
  return (
    <div className="pb-20">
      <OutcomeBanner variant="neutral" title="This one is outside what we can place.">
        {result.message ?? 'We could not match this to a shoppable consumer catalog.'}
      </OutcomeBanner>

      {chips.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] text-muted">Try a sample:</span>
          {chips.map((s) => (
            <button key={s.id} type="button" className="chip" onClick={() => onPickSample(s)}>
              {s.label}
            </button>
          ))}
        </div>
      )}

      {excluded.length > 0 && (
        <>
          <h5 className="m-0 mt-7 mb-2.5 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
            Excluded · {excluded.length}
          </h5>
          <div className="grid gap-x-3 sm:grid-cols-2 min-[900px]:grid-cols-3">
            {shown.map((p) => (
              <div
                key={p.publisher_id}
                data-testid="excluded"
                className="mb-2 rounded-[14px] border border-dashed border-[#d6cde6] px-3.5 py-3 text-[12.5px]"
              >
                <span className="float-right text-[11.5px] font-semibold text-bad">{p.fit.toFixed(2)}</span>
                <b className="text-[13.5px]">{p.name}</b>
                <p className="m-0 mt-1 leading-snug text-muted">{p.reason}</p>
              </div>
            ))}
          </div>
          {more > 0 && (
            <button
              type="button"
              onClick={() => setShowAll((v) => !v)}
              className="cursor-pointer rounded-[14px] border border-solid border-[#d6cde6] bg-white px-4 py-2.5 text-[12.5px] font-semibold text-violet-dark"
            >
              {showAll ? 'Show fewer ▴' : `Show ${more} more ▾`}
            </button>
          )}
        </>
      )}
    </div>
  )
}
