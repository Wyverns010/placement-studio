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

/**
 * Step ② while the ads are being written (the agent path takes ~20 s): what the team is doing,
 * with the seconds elapsed since it started.
 */
export function AgentWorking({ className = '' }: { className?: string }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const start = Date.now()
    const id = setInterval(() => setSecs(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])
  return (
    <p data-testid="agent-working" role="status" className={`m-0 text-[12.5px] text-muted ${className}`}>
      The copywriter is drafting, the critic is reviewing… {secs} s
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
