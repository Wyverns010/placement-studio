import type { CampaignResult, Sample, StreamPartial } from '../types'
import { AgentTicker } from './AgentUi'
import ClarifyView from './ClarifyView'
import OutOfScopeView from './OutOfScopeView'
import OutcomeBanner from './OutcomeBanner'
import ResultHeader from './ResultHeader'
import StagedResults, { type SteerStep } from './StagedResults'
import { Busy } from './ui'

interface Props {
  result: CampaignResult
  /** What the user typed, shown in the header (input_text may have clarify answers appended). */
  displayText?: string
  onBack: () => void
  /** Re-runs stage 1 with the same input (after a 403: the campaign changed or expired). */
  onRerun?: () => void
  samples?: Sample[]
  onPickSample?: (s: Sample) => void
  onRebuild?: (answers: Record<string, string>) => void
  running?: boolean
  rebuildError?: string | null
  /** Re-runs stage 1 with the same text/answers plus a steer for the strategist agent. */
  onSteer?: (steer: string, from?: SteerStep) => void
  /** The steer the shown result was produced with. */
  steer?: string
  /** Which step the steer was written on (the result opens there). */
  steerFrom?: SteerStep
  /** Live stage events of a re-run (for the agent ticker). */
  partial?: StreamPartial
}

export default function Results({
  result,
  displayText,
  onBack,
  onRerun,
  samples = [],
  onPickSample = () => {},
  onRebuild = () => {},
  running = false,
  rebuildError = null,
  onSteer,
  steer = '',
  steerFrom = 'publishers',
  partial,
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
      {running && <AgentTicker trace={partial?.agent} />}
      <StagedResults
        result={result}
        onRerun={running ? undefined : onRerun}
        onSteer={onSteer}
        initialStep={steerFrom}
        initialSteer={steer}
        running={running}
      />
    </section>
  )
}
