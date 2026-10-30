import type { CampaignRequest, CampaignResult, Sample, StageEvent } from './types'

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

export function runCampaign(req: CampaignRequest): Promise<CampaignResult> {
  return request<CampaignResult>('/api/campaign', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
}

/**
 * Stub until Task 17 (EventSource streaming): runs the campaign and emits a
 * single `done` event. Returns a cancel function.
 */
export function streamCampaign(
  req: CampaignRequest,
  onEvent: (e: StageEvent) => void,
): () => void {
  let cancelled = false
  runCampaign(req)
    .then((result) => {
      if (!cancelled) onEvent({ stage: 'done', data: result as unknown as Record<string, unknown> })
    })
    .catch((err: unknown) => {
      if (!cancelled)
        onEvent({ stage: 'error', data: { detail: err instanceof Error ? err.message : FALLBACK } })
    })
  return () => {
    cancelled = true
  }
}
