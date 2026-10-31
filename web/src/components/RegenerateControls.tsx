import { useId, useState } from 'react'
import { Busy, StageError, type StageErr } from './ui'

const NOTE_MAX = 200 // matches creative.note_max_chars in config/tuning.yaml

/** Under one ad: an optional steering note and Regenerate, with that card's own busy/error state. */
export default function RegenerateControls({
  personaName,
  busy,
  disabled,
  error,
  onRerun,
  onRegenerate,
}: {
  personaName: string
  busy: boolean
  disabled?: boolean
  error?: StageErr
  onRerun?: () => void
  /** Resolves true when the ad was replaced (the note is then cleared). */
  onRegenerate: (note: string) => Promise<boolean>
}) {
  const [note, setNote] = useState('')
  const id = useId()
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault()
        if (busy || disabled) return
        if (await onRegenerate(note)) setNote('')
      }}
    >
      <label htmlFor={id} className="sr-only">
        Note for the {personaName} ad (optional)
      </label>
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="text"
          value={note}
          maxLength={NOTE_MAX}
          disabled={busy}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note (optional)"
          title="Optional: steer the rewrite, e.g. warmer tone"
          className="min-w-0 flex-1 rounded-lg border border-line bg-card px-2.5 py-1.5 text-[12.5px] text-ink outline-none placeholder:text-muted focus:border-violet disabled:opacity-60"
        />
        <button
          type="submit"
          className="pill pill-sm shrink-0"
          disabled={busy || disabled}
          aria-label={busy ? `Rewriting the ${personaName} ad` : `Regenerate the ${personaName} ad`}
        >
          {busy ? <Busy label="Rewriting…" /> : '↻ Regenerate'}
        </button>
      </div>
      {note.length > NOTE_MAX - 40 && (
        <div className="mt-1 text-right text-[11px] text-muted">
          {note.length} / {NOTE_MAX}
        </div>
      )}
      {error && (
        <div className="mt-2">
          <StageError err={error} onRerun={onRerun} compact />
        </div>
      )}
    </form>
  )
}
