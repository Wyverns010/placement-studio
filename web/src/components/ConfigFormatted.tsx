import { personaById } from '../catalog'
import { pct, titleCase, usd } from '../format'
import type { CampaignConfig, Creative, PersonaScore, PublisherScore } from '../types'

const SHADES = ['#7c3aed', '#a78bfa', '#c4b5fd', '#ddd2fb', '#ece6fb']

function Row({
  label,
  rkey,
  config,
  children,
}: {
  label: string
  rkey: string
  config: CampaignConfig
  children: React.ReactNode
}) {
  const tip = config.rationales?.[rkey]
  return (
    <div
      className="grid grid-cols-1 gap-1 border-b border-[#f0ebf8] py-3 text-[13px] last:border-0 sm:grid-cols-[150px_1fr] sm:gap-3"
      title={tip}
      style={tip ? { cursor: 'help' } : undefined}
    >
      <span className="text-muted">
        {label}
        {tip && <span className="text-[#b9aed3]"> ⓘ</span>}
      </span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

function Chips({ items }: { items: string[] }) {
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

const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])

export default function ConfigFormatted({
  config,
  publishers = [],
  personas = [],
  creatives = [],
}: {
  config: CampaignConfig
  publishers?: PublisherScore[]
  personas?: PersonaScore[]
  creatives?: Creative[]
}) {
  const pubName = (id: string) => publishers.find((p) => p.publisher_id === id)?.name ?? id
  const personaName = (id: string) =>
    personas.find((p) => p.persona_id === id)?.name ?? personaById(id)?.name ?? id

  const b = config.budget
  const monthly = num(b.monthly_usd) ?? 0
  const unallocated = num(b.unallocated_usd) ?? 0
  const bid = config.bid_strategy
  const bidType = typeof bid.type === 'string' ? bid.type : ''
  const bidTarget = num(bid.target_usd)
  const t = config.targeting
  const ages = Array.isArray(t.age_range) ? (t.age_range as (number | null)[]) : []
  const ageText =
    ages.length === 2 && ages[0] != null && ages[1] != null ? `Ages ${ages[0]}–${ages[1]}` : null
  const gender = typeof t.gender === 'string' ? t.gender : ''
  const fc = config.frequency_cap
  const g = config.guardrails
  const cpaLimit = num(g.cpa_limit_usd)
  const mult = num(g.pause_if_cpa_over_x)
  const minImp = num(g.min_impressions)

  return (
    <div className="rounded-2xl border border-line bg-white px-[18px] py-1.5">
      <Row label="Objective" rkey="objective" config={config}>
        <b className="font-semibold">Conversions</b>
        <span className="text-muted"> · {titleCase(config.conversion_event)}</span>
      </Row>
      <Row label="Bid strategy" rkey="bid_strategy" config={config}>
        <b className="font-semibold">
          {titleCase(bidType).replace(/\bcpa\b/i, 'CPA')}
          {bidTarget != null && ` · ${usd(bidTarget)}`}
        </b>
      </Row>
      <Row label="Budget" rkey="budget" config={config}>
        <b className="font-semibold">
          {usd(monthly)} / month · {String(b.pacing ?? 'even')} pacing
        </b>
        {b.test_budget === true && (
          <span className="ml-2 rounded-full bg-warn-soft px-2 py-0.5 text-[11px] font-semibold text-warn">
            Test budget
          </span>
        )}
        <div
          className="my-2 flex h-3 overflow-hidden rounded-full bg-[#ece6fb]"
          role="img"
          aria-label="Budget allocation by publisher"
        >
          {config.line_items.map((li, i) => (
            <i
              key={li.publisher_id}
              style={{ width: `${li.share * 100}%`, background: SHADES[i % SHADES.length] }}
              title={`${pubName(li.publisher_id)} ${pct(li.share)}`}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-muted">
          {config.line_items.map((li, i) => (
            <span key={li.publisher_id} className="inline-flex items-center gap-1">
              <i
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: SHADES[i % SHADES.length] }}
              />
              {pubName(li.publisher_id)} {pct(li.share)}
            </span>
          ))}
          {unallocated > 0 && <span>Unallocated {usd(unallocated)}</span>}
        </div>
      </Row>
      <Row label="Targeting" rkey="targeting" config={config}>
        <Chips
          items={[
            ...(ageText ? [ageText] : []),
            ...(gender ? [gender === 'all' ? 'All genders' : titleCase(gender)] : []),
            ...strs(t.geo),
            ...strs(t.interests).map(titleCase),
            ...strs(t.personas).map(personaName),
          ]}
        />
      </Row>
      <Row label="Creative rotation" rkey="line_items" config={config}>
        <div className="space-y-1">
          {config.line_items.map((li) => {
            const cr = creatives.find((c) => c.creative_id === li.creative_id)
            return (
              <div key={li.publisher_id}>
                <b className="font-semibold">{pubName(li.publisher_id)}</b>
                <span className="text-muted"> → {cr ? personaName(cr.persona_id) : 'no creative'}</span>
              </div>
            )
          })}
        </div>
      </Row>
      <Row label="Frequency cap" rkey="frequency_cap" config={config}>
        <b className="font-semibold">
          {String(fc.impressions ?? '—')} / user / {String(fc.per_days ?? '—')} days
        </b>
      </Row>
      <Row label="Guardrails" rkey="guardrails" config={config}>
        <b className="font-semibold">
          Pause if CPA {cpaLimit != null ? `> ${usd(cpaLimit)}` : '> limit'}
          {mult != null && ` (${mult}× target)`}
          {minImp != null && ` after ${minImp.toLocaleString('en-US')} impressions`}
        </b>
      </Row>
    </div>
  )
}
