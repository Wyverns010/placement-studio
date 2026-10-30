import { useState } from 'react'
import type { CampaignConfig, Creative, PersonaScore, PublisherScore } from '../types'
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
  const tabs = [
    ['formatted', 'Formatted'],
    ['json', 'JSON'],
  ] as const
  return (
    <div className="pb-20">
      <div role="tablist" aria-label="Config view" className="mb-3.5 inline-flex rounded-full border border-line bg-white p-[3px]">
        {tabs.map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={view === k}
            onClick={() => setView(k)}
            className={`cursor-pointer rounded-full border-0 px-4 py-1.5 text-[13px] font-semibold ${
              view === k ? 'bg-violet text-white' : 'bg-transparent text-muted'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
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
    </div>
  )
}
