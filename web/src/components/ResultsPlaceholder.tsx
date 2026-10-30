import type { CampaignResult } from '../types'

// Temporary: Task 13 replaces this with the real Results view.
export default function ResultsPlaceholder({
  result,
  onBack,
}: {
  result: CampaignResult
  onBack: () => void
}) {
  return (
    <section className="py-14">
      <button type="button" className="pill pill-sm" onClick={onBack}>
        ← Back
      </button>
      <p className="mt-6 text-sm text-muted">Outcome</p>
      <h2 className="m-0 text-3xl font-semibold" data-testid="outcome">
        {result.outcome}
      </h2>
    </section>
  )
}
