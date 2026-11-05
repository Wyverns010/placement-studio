import type { CampaignConfig, CampaignRequest, CampaignResult, Creative, Sample } from './types'

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
  } catch (err) {
    if (init?.signal?.aborted) throw err // the caller (or a timeout) cancelled: let it decide
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

export const TIMEOUT_MESSAGE = 'The AI service is taking too long — try again or pick a sample.'

/** Writing the ads takes the longest (several calls per persona); every step gets this long. */
export const STAGE_TIMEOUT_MS = 60_000

/**
 * POSTs one stage request with a timeout. A timeout rejects with ApiError(TIMEOUT_MESSAGE);
 * a caller abort rejects with the fetch AbortError so callers can ignore it.
 */
async function postStage<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const ctl = new AbortController()
  let timedOut = false
  const t = setTimeout(() => {
    timedOut = true
    ctl.abort()
  }, STAGE_TIMEOUT_MS)
  const onAbort = () => ctl.abort()
  signal?.addEventListener('abort', onAbort)
  try {
    return await request<T>(url, {
      method: 'POST',
      signal: ctl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (err) {
    if (timedOut) throw new ApiError(0, TIMEOUT_MESSAGE)
    throw err
  } finally {
    clearTimeout(t)
    signal?.removeEventListener('abort', onAbort)
  }
}

/** Step 1: read the text, decide, and match publishers and personas. */
export function runCampaign(req: CampaignRequest, signal?: AbortSignal): Promise<CampaignResult> {
  return postStage<CampaignResult>('/api/campaign', req, signal)
}

/** Step 3: one ad per persona for step 1's result; a note is guidance for the writers. */
export async function createCreatives(result: CampaignResult, note: string, signal?: AbortSignal): Promise<Creative[]> {
  const body = { result, note: note || null }
  return (await postStage<{ creatives: Creative[] }>('/api/creatives', body, signal)).creatives
}

/** Step 4 (code only): the campaign config, and what a note changed; no budget means the recommended one. */
export function buildConfig(
  result: CampaignResult,
  creatives: Creative[],
  budgetUsd: number | null,
  note: string,
  signal?: AbortSignal,
): Promise<{ config: CampaignConfig; notes: string[] }> {
  return postStage('/api/config', { result, creatives, budget_usd: budgetUsd, note: note || null }, signal)
}
