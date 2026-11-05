import type { CampaignResult, Sample } from '../types'
import ClarifyView from './ClarifyView'
import OutOfScopeView from './OutOfScopeView'
import OutcomeBanner from './OutcomeBanner'
import ResultHeader from './ResultHeader'
import StagedResults, { type NoteStep } from './StagedResults'
import { Busy } from './ui'

interface Props {
  result: CampaignResult
  /** What the user typed, shown in the header (input_text may have clarify answers appended). */
  displayText?: string
  onBack: () => void
  samples?: Sample[]
  onPickSample?: (s: Sample) => void
  onRebuild?: (answers: Record<string, string>) => void
  running?: boolean
  rebuildError?: string | null
  /** Re-runs step 1 with the same text and answers plus a note. */
  onNote?: (note: string, from?: NoteStep) => void
  /** The note the shown result was produced with. */
  note?: string
  /** Which step the note was written on (the result opens there). */
  noteFrom?: NoteStep
}

export default function Results({
  result,
  displayText,
  onBack,
  samples = [],
  onPickSample = () => {},
  onRebuild = () => {},
  running = false,
  rebuildError = null,
  onNote,
  note = '',
  noteFrom = 'publishers',
}: Props) {
  if (result.outcome !== 'proceed' && result.outcome !== 'weak_fit') {
    return (
      <section>
        <ResultHeader result={result} displayText={displayText} onBack={onBack} />
        {rebuildError && (
          <div className="mb-4">
            <OutcomeBanner variant="error" title="That run didn't finish.">
              <p className="m-0 mb-2.5">{rebuildError}</p>
              <button type="button" className="pill pill-sm" onClick={onBack}>
                Try a sample
              </button>
            </OutcomeBanner>
          </div>
        )}
        {result.outcome === 'out_of_scope' ? (
          <OutOfScopeView result={result} samples={samples} onPickSample={onPickSample} running={running} />
        ) : (
          <ClarifyView
            key={result.clarify.map((q) => q.question).join('|')}
            result={result}
            onRebuild={onRebuild}
            rebuilding={running}
          />
        )}
      </section>
    )
  }

  return (
    <section>
      <ResultHeader result={result} displayText={displayText} onBack={onBack} />
      {rebuildError && (
        <div className="mb-4">
          <OutcomeBanner variant="error" title="That run didn't finish.">
            <p className="m-0">{rebuildError}</p>
          </OutcomeBanner>
        </div>
      )}
      {running && (
        <p role="status" className="mb-4 text-[13px] text-muted">
          <Busy label="Running your campaign again…" />
        </p>
      )}
      <StagedResults
        result={result}
        onNote={onNote}
        initialStep={noteFrom}
        initialNote={note}
        running={running}
      />
    </section>
  )
}
