import { useEffect, useRef, useState } from 'react'
import type { Brief, CampaignResult, Outcome, StreamPartial } from '../types'
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
  return briefChips(result?.brief)
}

function briefChips(b: Brief | null | undefined): string[] {
  if (!b) return []
  const chips = b.categories.map(titleCase)
  const tier = tierLabel(b.price_tier)
  if (tier) chips.push(tier)
  if (b.business_model !== 'unknown') chips.push(titleCase(b.business_model === 'one_off' ? 'one-off' : b.business_model))
  return chips
}

/** Subtle pulsing "…" for a lane the pipeline has not reached yet. */
function Pending() {
  return (
    <span className="pulse-dots text-muted" aria-label="working">
      …
    </span>
  )
}

/** Fills from 0 to `value` on mount so the confidence animates in. */
function GateBar({ value, threshold, tone }: { value: number | null; threshold: number; tone: 'ok' | 'warn' | null }) {
  const [w, setW] = useState(0)
  useEffect(() => {
    if (value == null) return setW(0)
    const t = setTimeout(() => setW(Math.min(100, Math.max(0, value * 100))), 30)
    return () => clearTimeout(t)
  }, [value])
  return (
    <div className="relative h-2.5 rounded-full bg-[#e2dbef]">
      {value != null && (
        <i
          className="gate-fill absolute inset-y-0 left-0 rounded-full"
          style={{
            width: `${w}%`,
            background:
              tone === 'ok'
                ? 'linear-gradient(90deg,#c4b5fd,#7c3aed)'
                : 'linear-gradient(90deg,#f3d49a,#d48a1c)',
          }}
        />
      )}
      <b
        className="absolute -top-[5px] h-5 w-0.5 bg-ink"
        style={{ left: `${threshold * 100}%` }}
        title="Confidence threshold"
      />
    </div>
  )
}

function PubBars({ rows }: { rows: { key: string; name: string; fit: number }[] }) {
  return (
    <>
      {rows.map((p) => (
        <div key={p.key} className="my-[3px] flex items-center gap-2">
          <span className="w-[90px] shrink-0 truncate">{p.name}</span>
          <i
            className="h-2 rounded-full bg-violet"
            style={{ width: `${Math.round(p.fit * 100) * 0.6}%`, minWidth: 4 }}
            title={`fit ${p.fit.toFixed(2)}`}
          />
        </div>
      ))}
    </>
  )
}

interface Props {
  result: CampaignResult | null
  partial?: StreamPartial
  running?: boolean
}

export default function ReadingPanel({ result: last, partial = {}, running = false }: Props) {
  const ref = useRef<HTMLElement>(null)
  // While a run streams in, the lanes show the stages received so far, not the last result.
  const live = running
  const result = live ? null : last

  // On mobile the panel sits below the form: bring it into view when a run starts.
  useEffect(() => {
    if (!running) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ref.current?.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest' })
  }, [running])

  // Normalise both sources into one view-model.
  const gate = live ? (partial.gate ?? null) : (result?.gate ?? null)
  const verdict = gate ? gateVerdict(gate.outcome) : result ? gateVerdict(result.outcome) : null
  const chips = live ? briefChips(partial.understood) : understoodChips(result)
  let pubRows: { key: string; name: string; fit: number }[] = []
  let recommended: number | null = null
  let excluded: number | null = null
  if (live) {
    const rec = new Set(partial.publishers?.recommended ?? [])
    pubRows = (partial.publishers?.top ?? [])
      .filter((p) => rec.has(p.id))
      .sort((a, b) => b.fit - a.fit)
      .slice(0, 4)
      .map((p) => ({ key: p.id, name: p.name, fit: p.fit }))
    recommended = partial.publishers ? rec.size : null
  } else if (result) {
    pubRows = [...result.publishers]
      .filter((p) => p.recommended)
      .sort((a, b) => b.fit - a.fit)
      .slice(0, 4)
      .map((p) => ({ key: p.publisher_id, name: p.name, fit: p.fit }))
    recommended = result.publishers.filter((p) => p.recommended).length
    excluded = result.publishers.length - recommended
  }
  const personaNames = live
    ? (partial.personas?.selected ?? []).slice(0, 4).map((p) => p.name)
    : result
      ? result.personas.slice(0, 4).map((p) => p.name)
      : []
  const personaCount = live
    ? (partial.personas?.selected.length ?? null)
    : result
      ? result.personas.length
      : null

  const has = {
    understood: live ? !!partial.understood : !!result,
    gate: live ? !!partial.gate : !!result,
    publishers: live ? !!partial.publishers : !!result,
    personas: live ? !!partial.personas : !!result,
  }
  // Placeholders (idle) vs pulsing dots (running, stage not reached yet).
  const wait = (idle: React.ReactNode) => (live ? <Pending /> : idle)

  return (
    <aside
      ref={ref}
      className="rounded-card border border-line bg-card p-[22px]"
      style={{ boxShadow: '0 30px 60px -40px #3b1d7a66' }}
      aria-label="How we read your brand"
    >
      <div className="mb-3.5 flex items-baseline justify-between gap-3">
        <h3 className="m-0 text-[19px] font-semibold">How we read your brand</h3>
        <small className="text-muted">
          {live ? (partial.done ? 'done' : 'reading…') : result ? 'last campaign' : 'updates as it runs'}
        </small>
      </div>

      <div className="rounded-[14px] bg-[#f3effa] p-3.5">
        <Lane label="Understood">
          {has.understood ? (
            chips.length ? <Chips items={chips} /> : DASH
          ) : (
            wait(
              PLACEHOLDER_UNDERSTOOD.map((t) => (
                <span key={t} className="blk blk-ph">
                  {t}
                </span>
              )),
            )
          )}
        </Lane>

        <Lane label="Confidence">
          <GateBar value={gate?.confidence ?? null} threshold={gate?.threshold ?? 0.7} tone={verdict?.tone ?? null} />
          <div className="mt-1.5 text-[11.5px] text-muted">
            {gate && verdict ? (
              <>
                {gate.confidence.toFixed(2)} vs. threshold {gate.threshold.toFixed(2)} →{' '}
                <b className={verdict.tone === 'ok' ? 'text-ok' : 'text-warn'}>{verdict.text}</b>
              </>
            ) : has.gate ? (
              DASH
            ) : (
              wait('Confidence appears here after you build a campaign')
            )}
          </div>
        </Lane>

        <Lane label="Publishers">
          {has.publishers ? (
            pubRows.length ? <PubBars rows={pubRows} /> : DASH
          ) : (
            wait(
              [88, 70, 55, 42].map((w) => (
                <div key={w} className="my-[3px] flex items-center gap-2">
                  <span className="h-2 w-[90px] shrink-0 rounded-full bg-[#e2dbef]" />
                  <i className="h-2 rounded-full bg-[#e2dbef]" style={{ width: `${w * 0.5}%` }} />
                </div>
              )),
            )
          )}
        </Lane>

        <Lane label="Personas">
          {has.personas ? (
            personaNames.length ? <Chips items={personaNames} /> : DASH
          ) : (
            wait(
              PLACEHOLDER_PERSONAS.map((t, i) => (
                <span key={i} className="blk blk-ph">
                  {t}
                </span>
              )),
            )
          )}
        </Lane>
      </div>

      <div className="mt-4 flex items-center justify-end gap-6 text-center text-xs text-muted">
        <div>
          <strong className="block text-[22px] text-ink">{recommended ?? '–'}</strong>
          publishers
        </div>
        <div>
          <strong className="block text-[22px] text-ink">{personaCount ?? '–'}</strong>
          personas
        </div>
        <div>
          <strong className="block text-[22px] text-ink">{excluded ?? '–'}</strong>
          excluded
        </div>
      </div>
    </aside>
  )
}
