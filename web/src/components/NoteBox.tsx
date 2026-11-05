import { Busy } from './ui'

/** What a note changed or couldn't apply, in plain sentences; nothing when there are none. */
export function NoteList({ notes, className = '' }: { notes?: string[]; className?: string }) {
  if (!notes?.length) return null
  return (
    <ul
      data-testid="note-list"
      aria-label="What your note changed"
      className={`m-0 list-disc space-y-1 rounded-xl border border-line bg-white py-2.5 pr-3.5 pl-8 text-[13px] leading-snug ${className}`}
    >
      {notes.map((note, i) => (
        <li key={i}>{note}</li>
      ))}
    </ul>
  )
}

/** A one-line note that updates this step, with an Apply button. */
export function NoteBox({
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
  onChange: (value: string) => void
  onApply: (note: string) => void
  busy?: boolean
  disabled?: boolean
  /** Applying a blank note is allowed (it clears a note applied earlier). */
  allowBlank?: boolean
}) {
  const trimmed = value.trim()
  const canApply = !busy && !disabled && (trimmed.length > 0 || allowBlank)
  return (
    <form
      className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-white px-3 py-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (canApply) onApply(trimmed)
      }}
    >
      <input
        aria-label="Note"
        placeholder={`Add a note… e.g. ${placeholder}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-[180px] flex-1 border-0 bg-transparent font-[inherit] text-[13.5px] outline-none"
      />
      <button type="submit" className="pill pill-sm" disabled={!canApply}>
        {busy ? <Busy label="Applying…" /> : 'Apply'}
      </button>
    </form>
  )
}
