import { useEffect, useState } from 'react'
import { STEER_MAX, type AgentTraceEntry } from '../types'
import { Busy } from './ui'

/** "Agent: <tool> …" — the latest tool call while stage 1 streams in. */
export function AgentTicker({ trace }: { trace?: AgentTraceEntry[] }) {
  const last = trace?.at(-1)
  if (!last) return null
  return (
    <p data-testid="agent-ticker" role="status" className="m-0 mb-2.5 truncate text-[12px] text-muted">
      Agent: <span className="font-mono text-violet-dark">{last.tool}</span> …
    </p>
  )
}

/** What the creative team is doing, step by step, for these personas and publishers. */
export function workingSteps(personas: string[], publishers: string[]): string[] {
  const writes = personas.map((p, i) =>
    publishers.length ? `Writing for ${p} on ${publishers[i % publishers.length]}…` : `Writing for ${p}…`,
  )
  return [
    personas.length ? `Reading what ${personas[0]} cares about…` : 'Reading your brief…',
    ...writes,
    'The critic is reviewing each draft against the playbook…',
    'Checking every claim against your text…',
    'Picking the right button for how it is bought…',
    'Final checks on the ads…',
  ]
}

/**
 * Step ② while the ads are being written: what the team is doing now, advancing every couple of
 * seconds and holding on the last step (no timer to stare at).
 */
export function AgentWorking({
  personas = [],
  publishers = [],
  className = '',
}: {
  personas?: string[]
  publishers?: string[]
  className?: string
}) {
  const steps = workingSteps(personas, publishers)
  const [i, setI] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setI((n) => Math.min(n + 1, steps.length - 1)), 2200)
    return () => clearInterval(id)
  }, [steps.length])
  return (
    <p
      data-testid="agent-working"
      role="status"
      aria-live="polite"
      className={`m-0 flex items-center gap-2 text-[12.5px] text-muted ${className}`}
    >
      <span aria-hidden="true" className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet" />
      <span key={i} className="animate-[fadeIn_.3s_ease]">
        {steps[i]}
      </span>
    </p>
  )
}

/** What a steer changed or couldn't apply, in plain sentences; nothing when there are none. */
export function AgentNotes({ notes, className = '' }: { notes?: string[]; className?: string }) {
  if (!notes?.length) return null
  return (
    <ul
      data-testid="agent-notes"
      aria-label="What your note changed"
      className={`m-0 list-disc space-y-1 rounded-xl border border-line bg-white py-2.5 pr-3.5 pl-8 text-[13px] leading-snug ${className}`}
    >
      {notes.map((n, i) => (
        <li key={i}>{n}</li>
      ))}
    </ul>
  )
}

/** Compact "Tell the agent…" box (≤ 300 chars, counter) with an Apply button. */
export function AgentSteer({
  placeholder,
  value,
  onChange,
  onApply,
  busy = false,
  disabled = false,
  allowBlank = false,
}: {
  placeholder: string
  value: string
  onChange: (v: string) => void
  onApply: (steer: string) => void
  busy?: boolean
  disabled?: boolean
  /** Blank Apply is allowed (clears a steer that was applied earlier). */
  allowBlank?: boolean
}) {
  const trimmed = value.trim()
  const canApply = !busy && !disabled && trimmed.length <= STEER_MAX && (trimmed.length > 0 || allowBlank)
  return (
    <form
      className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (canApply) onApply(trimmed)
      }}
    >
      <input
        aria-label="Tell the agent"
        placeholder={`Tell the agent… e.g. ${placeholder}`}
        value={value}
        maxLength={STEER_MAX}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[180px] flex-1 border-0 bg-transparent font-[inherit] text-[13.5px] outline-none"
      />
      <span className="text-[11.5px] text-muted" aria-live="off" data-testid="steer-count">
        {value.length}/{STEER_MAX}
      </span>
      <button type="submit" className="pill pill-sm" disabled={!canApply}>
        {busy ? <Busy label="Applying…" /> : 'Apply'}
      </button>
    </form>
  )
}
