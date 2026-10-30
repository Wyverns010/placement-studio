import { useState } from 'react'
import type { CampaignResult } from '../types'
import ConfigTab from './ConfigTab'
import PersonasTab from './PersonasTab'
import PublishersTab from './PublishersTab'
import Tabs, { type TabDef } from './Tabs'
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
  const tabs: TabDef<Tab>[] = [
    { id: 'publishers', label: 'Publishers', count: recCount },
    { id: 'personas', label: 'Personas & creatives', count: result.personas.length },
    { id: 'config', label: 'Campaign config' },
  ]

  return (
    <section>
      <ResultHeader result={result} onBack={onBack} />
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
