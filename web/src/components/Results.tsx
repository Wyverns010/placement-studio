import { useState } from 'react'
import type { CampaignResult } from '../types'
import ConfigTab from './ConfigTab'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import ResultHeader from './ResultHeader'

type Tab = 'publishers' | 'personas' | 'config'

export default function Results({ result, onBack }: { result: CampaignResult; onBack: () => void }) {
  const [tab, setTab] = useState<Tab>('publishers')

  if (result.outcome !== 'proceed' && result.outcome !== 'weak_fit') {
    // Task 14 replaces this stub with the dedicated clarify / out-of-scope / no-signal views.
    return (
      <section className="py-14">
        <button type="button" className="pill pill-sm" onClick={onBack}>
          ← New campaign
        </button>
        <p className="mt-6 text-lg" data-testid="outcome">
          {result.outcome}: {result.message ?? ''}
        </p>
      </section>
    )
  }

  const recCount = result.publishers.filter((p) => p.recommended).length
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'publishers', label: 'Publishers', count: recCount },
    { id: 'personas', label: 'Personas & creatives', count: result.personas.length },
    { id: 'config', label: 'Campaign config' },
  ]

  return (
    <section>
      <ResultHeader result={result} onBack={onBack} />
      <div role="tablist" className="mb-[22px] flex gap-1.5 overflow-x-auto border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px cursor-pointer whitespace-nowrap border-0 border-b-2 bg-transparent px-4 py-3 text-sm ${
              tab === t.id
                ? 'border-violet font-semibold text-ink'
                : 'border-transparent font-medium text-muted'
            }`}
          >
            {t.label}
            {t.count != null && (
              <em className="ml-1.5 rounded-full bg-violet-soft px-[7px] py-0.5 text-[11.5px] font-normal not-italic text-violet-dark">
                {t.count}
              </em>
            )}
          </button>
        ))}
      </div>
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
    </section>
  )
}
