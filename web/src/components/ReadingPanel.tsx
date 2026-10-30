import type { CampaignResult, Outcome } from '../types'
import { tierLabel, titleCase } from '../format'

const DASH = <span className="text-muted">—</span>

function Lane({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[84px_1fr] items-center gap-2.5 border-b border-dashed border-[#dcd3ec] py-[9px] text-[13px] last:border-0 sm:grid-cols-[96px_1fr]">
      <span className="text-muted">{label}</span>
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

const PLACEHOLDER_UNDERSTOOD = ['Category', 'Price tier', 'Business model']
const PLACEHOLDER_PERSONAS = ['Persona', 'Persona']

function gateVerdict(outcome: Outcome): { text: string; tone: 'ok' | 'warn' } {
  switch (outcome) {
    case 'proceed':
    case 'weak_fit':
      return { text: 'enough to proceed', tone: 'ok' }
    case 'clarify':
      return { text: 'needs more detail', tone: 'warn' }
    case 'out_of_scope':
      return { text: 'outside what we can place', tone: 'warn' }
    case 'no_signal':
      return { text: 'not enough signal', tone: 'warn' }
  }
}

export function understoodChips(result: CampaignResult | null): string[] {
  const b = result?.brief
  if (!b) return []
  const chips = b.categories.map(titleCase)
  const tier = tierLabel(b.price_tier)
  if (tier) chips.push(tier)
  if (b.business_model !== 'unknown') chips.push(titleCase(b.business_model === 'one_off' ? 'one-off' : b.business_model))
  return chips
}

export default function ReadingPanel({ result }: { result: CampaignResult | null }) {
  const gate = result?.gate ?? null
  const verdict = result ? gateVerdict(result.gate?.outcome ?? result.outcome) : null
  const chips = understoodChips(result)
  const topPubs = result
    ? [...result.publishers]
        .filter((p) => p.recommended)
        .sort((a, b) => b.fit - a.fit)
        .slice(0, 4)
    : []
  const recommended = result ? result.publishers.filter((p) => p.recommended).length : 0
  const excluded = result ? result.publishers.length - recommended : 0
  const personas = result ? result.personas.slice(0, 4) : []

  return (
    <aside
      className="rounded-card border border-line bg-card p-[22px]"
      style={{ boxShadow: '0 30px 60px -40px #3b1d7a66' }}
      aria-label="How we read your brand"
    >
      <div className="mb-3.5 flex items-baseline justify-between gap-3">
        <h3 className="m-0 text-[19px] font-semibold">How we read your brand</h3>
        <small className="text-muted">{result ? 'last campaign' : 'updates as it runs'}</small>
      </div>

      <div className="rounded-[14px] bg-[#f3effa] p-3.5">
        <Lane label="Understood">
          {result ? (
            chips.length ? <Chips items={chips} /> : DASH
          ) : (
            PLACEHOLDER_UNDERSTOOD.map((t) => (
              <span key={t} className="blk blk-ph">
                {t}
              </span>
            ))
          )}
        </Lane>

        <Lane label="Confidence">
          <div className="relative h-2.5 rounded-full bg-[#e2dbef]">
            {gate && (
              <i
                className="absolute inset-y-0 left-0 rounded-full"
                style={{
                  width: `${Math.min(100, Math.max(0, gate.confidence * 100))}%`,
                  background:
                    verdict?.tone === 'ok'
                      ? 'linear-gradient(90deg,#c4b5fd,#7c3aed)'
                      : 'linear-gradient(90deg,#f3d49a,#d48a1c)',
                }}
              />
            )}
            <b
              className="absolute -top-[5px] h-5 w-0.5 bg-ink"
              style={{ left: `${(gate?.threshold ?? 0.7) * 100}%` }}
              title="Confidence threshold"
            />
          </div>
          <div className="mt-1.5 text-[11.5px] text-muted">
            {gate && verdict ? (
              <>
                {gate.confidence.toFixed(2)} vs. threshold {gate.threshold.toFixed(2)} →{' '}
                <b className={verdict.tone === 'ok' ? 'text-ok' : 'text-warn'}>{verdict.text}</b>
              </>
            ) : result ? (
              DASH
            ) : (
              'Confidence appears here after you build a campaign'
            )}
          </div>
        </Lane>

        <Lane label="Publishers">
          {result ? (
            topPubs.length ? (
              topPubs.map((p) => (
                <div key={p.publisher_id} className="my-[3px] flex items-center gap-2">
                  <span className="w-[90px] shrink-0 truncate">{p.name}</span>
                  <i
                    className="h-2 rounded-full bg-violet"
                    style={{ width: `${Math.round(p.fit * 100) * 0.6}%`, minWidth: 4 }}
                    title={`fit ${p.fit.toFixed(2)}`}
                  />
                </div>
              ))
            ) : (
              DASH
            )
          ) : (
            [88, 70, 55, 42].map((w) => (
              <div key={w} className="my-[3px] flex items-center gap-2">
                <span className="h-2 w-[90px] shrink-0 rounded-full bg-[#e2dbef]" />
                <i className="h-2 rounded-full bg-[#e2dbef]" style={{ width: `${w * 0.5}%` }} />
              </div>
            ))
          )}
        </Lane>

        <Lane label="Personas">
          {result ? (
            personas.length ? (
              <Chips items={personas.map((p) => p.name)} />
            ) : (
              DASH
            )
          ) : (
            PLACEHOLDER_PERSONAS.map((t, i) => (
              <span key={i} className="blk blk-ph">
                {t}
              </span>
            ))
          )}
        </Lane>
      </div>

      <div className="mt-4 flex items-center justify-end gap-6 text-center text-xs text-muted">
        <div>
          <strong className="block text-[22px] text-ink">{result ? recommended : '–'}</strong>
          publishers
        </div>
        <div>
          <strong className="block text-[22px] text-ink">{result ? result.personas.length : '–'}</strong>
          personas
        </div>
        <div>
          <strong className="block text-[22px] text-ink">{result ? excluded : '–'}</strong>
          excluded
        </div>
      </div>
    </aside>
  )
}
