import { personaById, publisherById } from '../catalog'
import { humanise, pct, titleCase, usd } from '../format'
import type { CampaignConfig, Creative, PersonaScore, PublisherScore } from '../types'
import { Chips } from './ui'

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
  const raw = config.rationales?.[rkey]
  const tip = raw ? humanise(raw) : undefined
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
      <div className="min-w-0">
        {children}
        {tip && <p className="mt-1 mb-0 text-[11.5px] leading-snug text-muted">{tip}</p>}
      </div>
    </div>
  )
}

/** "front_loaded" → "front loaded"; missing → "even". */
const pacingLabel = (v: unknown): string => (typeof v === 'string' && v ? v.replace(/_/g, ' ') : 'even')
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
          {usd(monthly)} / month · {pacingLabel(b.pacing)} pacing
        </b>
        {b.source === 'user' && (
          <span className="ml-2 rounded-full bg-violet-soft px-2 py-0.5 text-[11px] font-semibold text-violet-dark">
            Your budget
          </span>
        )}
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
        {config.line_items.some((li) => num(li.cpm_usd) != null) && (
          <div className="mt-3 overflow-x-auto">
            <table data-testid="budget-breakdown" className="w-full border-collapse text-[12px]">
              <thead>
                <tr className="text-left text-muted">
                  <th className="py-1 pr-3 font-medium">Publisher</th>
                  <th className="py-1 pr-3 font-medium">Audience income</th>
                  <th className="py-1 pr-3 text-right font-medium">CPM</th>
                  <th className="py-1 pr-3 text-right font-medium">Share</th>
                  <th className="py-1 pr-3 text-right font-medium">Budget</th>
                  <th className="py-1 text-right font-medium">Impressions</th>
                </tr>
              </thead>
              <tbody>
                {config.line_items.map((li) => (
                  <tr key={li.publisher_id} className="border-t border-[#f0ebf8]">
                    <td className="py-1 pr-3">{pubName(li.publisher_id)}</td>
                    <td className="py-1 pr-3">{publisherById(li.publisher_id)?.audience?.income_tier ?? '—'}</td>
                    <td className="py-1 pr-3 text-right">{usd(num(li.cpm_usd) ?? 0)}</td>
                    <td className="py-1 pr-3 text-right">{pct(li.share)}</td>
                    <td className="py-1 pr-3 text-right">{usd(li.budget_usd)}</td>
                    <td className="py-1 text-right">{(num(li.est_impressions) ?? 0).toLocaleString('en-US')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(() => {
              const li = config.line_items[0]
              const cpm = num(li.cpm_usd) ?? 0
              return (
                <p data-testid="impressions-how" className="m-0 mt-2 text-[11.5px] leading-snug text-muted">
                  <b className="font-semibold text-ink">How these are worked out.</b> CPM (the price of 1,000
                  impressions) follows the publisher's audience income: mid $10, mid-high $13, high $16.
                  Share follows fit, with a 10% floor, capped at a quarter of the publisher's monthly
                  impressions. Budget = share × {usd(monthly)}. Impressions = budget ÷ CPM × 1,000, e.g.{' '}
                  {pubName(li.publisher_id)}: {usd(li.budget_usd)} ÷ {usd(cpm)} × 1,000 ={' '}
                  {(num(li.est_impressions) ?? 0).toLocaleString('en-US')}.
                </p>
              )
            })()}
          </div>
        )}
      </Row>
      {num(b.est_conversions) != null && (
        <Row label="Projection" rkey="projection" config={config}>
          <div data-testid="projection" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ['Impressions', (num(b.est_impressions) ?? 0).toLocaleString('en-US')],
              ['Conversions', (num(b.est_conversions) ?? 0).toLocaleString('en-US')],
              ['Revenue', usd(num(b.est_revenue_usd) ?? 0)],
              ['ROAS', `${num(b.est_roas) ?? 0}×`],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-[#f7f4fd] px-2.5 py-1.5">
                <div className="text-[11px] text-muted">{k}</div>
                <b className="text-[14px] font-semibold">{v}</b>
              </div>
            ))}
          </div>
          {b.cpa_is_stretch === true && (
            <p className="m-0 mt-2 text-[12px] font-semibold text-warn">
              This CPA needs more conversions per impression than checkout offers usually get.
            </p>
          )}
        </Row>
      )}
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
            const names = li.ads.filter((id) => creatives.some((c) => c.persona_id === id)).map(personaName)
            return (
              <div key={li.publisher_id}>
                <b className="font-semibold">{pubName(li.publisher_id)}</b>
                <span className="text-muted"> → {names.length ? names.join(', ') : 'no creative'}</span>
              </div>
            )
          })}
        </div>
      </Row>
      {config.rationales?.pacing != null && (
        <Row label="Pacing" rkey="pacing" config={config}>
          <b className="font-semibold">{titleCase(pacingLabel(b.pacing))}</b>
        </Row>
      )}
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
