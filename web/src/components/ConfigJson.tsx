import { useEffect, useRef, useState } from 'react'
import { jsonHighlight } from '../format'
import type { CampaignConfig } from '../types'

export default function ConfigJson({ config }: { config: CampaignConfig }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])
  const text = JSON.stringify(config, null, 2)

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard unavailable (insecure context / denied) */
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'campaign_config.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[13px] text-muted">campaign_config.json</span>
        <span className="flex gap-2">
          <button type="button" className="pill pill-sm" onClick={copy} aria-live="polite">
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button type="button" className="pill pill-sm" onClick={download}>
            Download
          </button>
        </span>
      </div>
      <pre
        className="json m-0 max-h-[560px] overflow-auto rounded-2xl bg-[#16131f] p-[18px] text-xs leading-[1.6] text-[#e4dcf7]"
        style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}
        // safe: jsonHighlight escapes all text before wrapping it in spans
        dangerouslySetInnerHTML={{ __html: jsonHighlight(config) }}
      />
    </div>
  )
}
