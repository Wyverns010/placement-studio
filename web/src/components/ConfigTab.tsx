import { useState } from 'react'
import type { CampaignConfig, Creative, PersonaScore, PublisherScore } from '../types'
import Tabs, { type TabDef } from './Tabs'
import ConfigFormatted from './ConfigFormatted'
import ConfigJson from './ConfigJson'

export default function ConfigTab({
  config,
  publishers,
  personas,
  creatives,
}: {
  config: CampaignConfig
  publishers?: PublisherScore[]
  personas?: PersonaScore[]
  creatives?: Creative[]
}) {
  const [view, setView] = useState<'formatted' | 'json'>('formatted')
  const tabs: TabDef<'formatted' | 'json'>[] = [
    { id: 'formatted', label: 'Formatted' },
    { id: 'json', label: 'JSON' },
  ]
  return (
    <div>
      <Tabs tabs={tabs} value={view} onChange={setView} label="Config view" variant="segmented">
      {view === 'formatted' ? (
        <ConfigFormatted
          config={config}
          publishers={publishers}
          personas={personas}
          creatives={creatives}
        />
      ) : (
        <ConfigJson config={config} />
      )}
      </Tabs>
    </div>
  )
}
