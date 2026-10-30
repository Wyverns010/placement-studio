import type { CampaignRequest, CampaignResult, Sample, StageEvent, StageName } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const FALLBACK = 'Something went wrong on our side. Please try again in a moment.'

/** FastAPI `detail` is either a string or a list of {loc, msg} validation errors. */
export function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d === 'object' && 'msg' in d) return String((d as { msg: unknown }).msg)
        return ''
      })
      .filter(Boolean)
    if (parts.length) return parts.join('; ')
  }
  return FALLBACK
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, "Can't reach the server — check your connection and try again.")
  }
  if (!res.ok) {
    let message = FALLBACK
    try {
      const body = await res.json()
      message = formatDetail(body?.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message)
  }
  return (await res.json()) as T
}

export function getSamples(): Promise<Sample[]> {
  return request<Sample[]>('/api/samples')
}

export function runCampaign(req: CampaignRequest, signal?: AbortSignal): Promise<CampaignResult> {
  return request<CampaignResult>('/api/campaign', {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

export const STREAM_TIMEOUT_MS = 30_000
/** A native error this soon after opening is an HTTP 4xx/5xx, not a dropped stream. */
export const FALLBACK_WINDOW_MS = 3000
export const BAD_RESULT_MESSAGE = 'Something went wrong building this campaign.'
export const TIMEOUT_MESSAGE = 'The AI service is taking too long — try again or pick a sample.'

const STAGES: StageName[] = ['understood', 'gate', 'publishers', 'personas', 'creatives', 'config', 'done']

/**
 * Streams the pipeline over SSE (EventSource), one `onEvent` per stage, ending
 * with `done` or `error`. Returns a cancel function.
 *
 * EventSource cannot read the body of an HTTP error (422 validation, 429 rate
 * limit), so a connection error before any event falls back to the regular POST
 * /api/campaign, which re-surfaces the real `detail` (or, if it unexpectedly
 * succeeds, the result as a `done`). This costs at most one extra request on the
 * failure path only, and needs no pre-flight on the happy path.
 */
export function streamCampaign(
  req: CampaignRequest,
  onEvent: (e: StageEvent) => void,
): () => void {
  let finished = false
  let cancelled = false
  const openedAt = Date.now()
  let fallback: AbortController | undefined
  let fallbackTimer: ReturnType<typeof setTimeout> | undefined
  let gotEvent = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const params = new URLSearchParams({ text: req.text, budget_usd: String(req.budget_usd) })
  if (req.answers && Object.keys(req.answers).length) params.set('answers', JSON.stringify(req.answers))
  const es = new EventSource(`/api/campaign/stream?${params.toString()}`)

  const finish = () => {
    finished = true
    clearTimeout(timer)
    es.close()
  }
  const fail = (message: string) => {
    if (finished) return
    finish()
    onEvent({ stage: 'error', data: { message } })
  }
  const arm = () => {
    clearTimeout(timer)
    timer = setTimeout(() => fail(TIMEOUT_MESSAGE), STREAM_TIMEOUT_MS)
  }
  arm()

  const parse = (ev: Event): Record<string, unknown> => {
    try {
      const v: unknown = JSON.parse((ev as MessageEvent).data)
      return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
    } catch {
      return {}
    }
  }

  for (const stage of STAGES) {
    es.addEventListener(stage, (ev) => {
      if (finished) return
      gotEvent = true
      arm()
      const data = parse(ev)
      if (stage === 'done') {
        if (typeof data.outcome !== 'string') return fail(BAD_RESULT_MESSAGE)
        finish()
      }
      onEvent({ stage, data })
    })
  }

  es.addEventListener('error', (ev) => {
    if (finished) return
    // A server-sent `error` event carries data; a native connection error does not.
    if (typeof (ev as MessageEvent).data === 'string') {
      const d = parse(ev)
      fail(String(d.message ?? d.detail ?? FALLBACK))
    } else if (gotEvent || Date.now() - openedAt > FALLBACK_WINDOW_MS) {
      fail('The connection dropped before the campaign finished — please try again.')
    } else {
      // Likely an HTTP error before streaming: re-ask via POST to read its `detail`.
      finish()
      const ctl = (fallback = new AbortController())
      let timedOut = false
      const t = (fallbackTimer = setTimeout(() => {
        timedOut = true
        ctl.abort()
      }, STREAM_TIMEOUT_MS))
      const emit = (e: StageEvent) => {
        clearTimeout(t)
        if (!cancelled) onEvent(e)
      }
      runCampaign(req, ctl.signal)
        .then((result) => {
          const data = result as unknown as Record<string, unknown>
          if (!result || typeof data.outcome !== 'string')
            emit({ stage: 'error', data: { message: BAD_RESULT_MESSAGE } })
          else emit({ stage: 'done', data })
        })
        .catch((err: unknown) =>
          emit({
            stage: 'error',
            data: { message: timedOut ? TIMEOUT_MESSAGE : err instanceof Error ? err.message : FALLBACK },
          }),
        )
    }
  })

  return () => {
    cancelled = true
    clearTimeout(fallbackTimer)
    fallback?.abort()
    finish()
  }
}
