import { useState } from 'react'
import { publisherById, reachLabel } from '../catalog'
import { pct, titleCase, usd } from '../format'
import type { CampaignConfig, PublisherScore } from '../types'

const FACTORS: { key: string; label: string }[] = [
  { key: 'category', label: 'Category' },
  { key: 'audience', label: 'Audience' },
  { key: 'income', label: 'Income / price' },
  { key: 'aov', label: 'AOV fit' },
]

export function statsLine(publisherId: string): string {
  const c = publisherById(publisherId)
  if (!c) return ''
  return `${titleCase(c.category).toLowerCase()} · AOV ${usd(c.avg_order_value_usd)} · ${reachLabel(c.monthly_impressions)}`
}

function PublisherCard({
  pub,
  rank,
  config,
}: {
  pub: PublisherScore
  rank: number
  config: CampaignConfig | null
}) {
  const [open, setOpen] = useState(false)
  const line = config?.line_items.find((l) => l.publisher_id === pub.publisher_id)
  return (
    <article
      className="mb-3 grid grid-cols-[30px_1fr_auto] gap-x-3.5 gap-y-1 rounded-2xl border border-line bg-white px-4 py-4 sm:px-[18px]"
      aria-label={pub.name}
    >
      <div className="grid h-[30px] w-[30px] place-items-center rounded-full bg-violet-soft text-sm font-bold text-violet-dark">
        {rank}
      </div>
      <div className="min-w-0">
        <h4 className="m-0 flex flex-wrap items-center gap-2 text-base font-semibold">
          {pub.name}
          {pub.stretch && (
            <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">
              Stretch
            </span>
          )}
        </h4>
        <div className="mt-[3px] text-xs text-muted">{statsLine(pub.publisher_id)}</div>
      </div>
      <div className="text-right">
        <b className="text-[26px] leading-none tracking-[-0.02em]">{pub.fit.toFixed(2)}</b>
        <small className="block text-[11.5px] text-muted">fit score</small>
      </div>
      <div className="col-start-2 col-end-4 min-w-0">
        <p className="m-0 text-[13px] leading-normal text-[#3b3850]">{pub.reason}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {FACTORS.map((f) => {
            const fac = pub.factors.find((x) => x.name === f.key)
            const score = fac?.score ?? 0
            return (
              <div
                key={f.key}
                className="text-[11px] text-muted"
                title={`${f.label}: ${score.toFixed(2)}`}
              >
                {f.label}
                <i className="relative mt-1 block h-[5px] overflow-hidden rounded-full bg-[#e9e3f5]">
                  <span
                    data-testid="factor-bar"
                    className="absolute inset-y-0 left-0 rounded-full bg-violet"
                    style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }}
                  />
                </i>
              </div>
            )
          })}
        </div>
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="cursor-pointer border-0 bg-transparent p-0 text-xs font-semibold text-violet-dark"
          >
            Details {open ? '▴' : '▾'}
          </button>
          {line && (
            <span className="text-[13px] font-semibold">
              {usd(line.budget_usd)} · {pct(line.share)}
            </span>
          )}
        </div>
        {open && (
          <ul className="m-0 mt-2.5 list-none space-y-1.5 border-t border-dashed border-[#dcd3ec] p-0 pt-2.5 text-xs text-[#3b3850]">
            {pub.factors.map((f) => (
              <li key={f.name} className="flex justify-between gap-3">
                <span>
                  <b className="font-semibold">{titleCase(f.name)}</b> — {f.note}
                </span>
                <span className="shrink-0 font-semibold text-violet-dark">{f.score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  )
}

export default function PublishersTab({
  publishers,
  config,
}: {
  publishers: PublisherScore[]
  config: CampaignConfig | null
}) {
  const [showAll, setShowAll] = useState(false)
  const recommended = publishers.filter((p) => p.recommended)
  const excluded = publishers.filter((p) => !p.recommended).sort((a, b) => b.fit - a.fit)
  const shown = showAll ? excluded : excluded.slice(0, 4)
  const more = excluded.length - 4
  return (
    <div className="grid gap-[22px] pb-20 min-[900px]:grid-cols-[1.6fr_1fr]">
      <div>
        {recommended.map((p, i) => (
          <PublisherCard key={p.publisher_id} pub={p} rank={i + 1} config={config} />
        ))}
      </div>
      <aside>
        <h5 className="m-0 mb-2.5 text-[13px] font-semibold tracking-[0.06em] text-muted uppercase">
          Excluded · {excluded.length}
        </h5>
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
        {more > 0 && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="w-full cursor-pointer rounded-[14px] border border-solid border-[#d6cde6] bg-white px-3.5 py-3 text-center text-[12.5px] font-semibold text-violet-dark"
          >
            {showAll ? 'Show fewer ▴' : `Show ${more} more ▾`}
          </button>
        )}
      </aside>
    </div>
  )
}
