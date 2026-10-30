import { useState } from 'react'
import { usd } from '../format'
import type { CampaignResult, Sample } from '../types'
import ClarifyView from './ClarifyView'
import OutOfScopeView from './OutOfScopeView'
import OutcomeBanner from './OutcomeBanner'
import ConfigTab from './ConfigTab'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import Tabs, { type TabDef } from './Tabs'
import ResultHeader from './ResultHeader'

type Tab = 'publishers' | 'personas' | 'config'

interface Props {
  result: CampaignResult
  onBack: () => void
  samples?: Sample[]
  onPickSample?: (s: Sample) => void
  onRebuild?: (answers: Record<string, string>) => void
  running?: boolean
  rebuildError?: string | null
}

export default function Results({
  result,
  onBack,
  samples = [],
  onPickSample = () => {},
  onRebuild = () => {},
  running = false,
  rebuildError = null,
}: Props) {
  const [tab, setTab] = useState<Tab>('publishers')

  if (result.outcome !== 'proceed' && result.outcome !== 'weak_fit') {
    return (
      <section>
        <ResultHeader result={result} onBack={onBack} />
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

  const recCount = result.publishers.filter((p) => p.recommended).length
  const tabs: TabDef<Tab>[] = [
    { id: 'publishers', label: 'Publishers', count: recCount },
    { id: 'personas', label: 'Personas & creatives', count: result.personas.length },
    { id: 'config', label: 'Campaign config' },
  ]

  return (
    <section>
      <ResultHeader result={result} onBack={onBack} />
      {result.outcome === 'weak_fit' && (
        <div className="mb-4">
          <OutcomeBanner variant="amber" title="Weak fit — treat this as a test.">
            {result.message && <p className="m-0">{result.message}</p>}
            {typeof result.config?.budget.monthly_usd === 'number' && (
              <p className="m-0 mt-1 font-semibold">
                Test budget: {usd(result.config.budget.monthly_usd)} of {usd(result.budget_usd)}
              </p>
            )}
          </OutcomeBanner>
        </div>
      )}
      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Results sections">
      {tab === 'publishers' && <PublishersTab publishers={result.publishers} config={result.config} />}
      {tab === 'personas' && (
        <PersonasTab
          personas={result.personas}
          creatives={result.creatives}
          publishers={result.publishers}
        />
      )}
      {tab === 'config' &&
        (result.config ? (
          <ConfigTab
            config={result.config}
            publishers={result.publishers}
            personas={result.personas}
            creatives={result.creatives}
          />
        ) : (
          <p className="text-sm text-muted">No campaign config was generated.</p>
        ))}
      </Tabs>
    </section>
  )
}
