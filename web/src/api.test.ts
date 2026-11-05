import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildConfig,
  createCreatives,
  getSamples,
  runCampaign,
  STAGE_TIMEOUT_MS,
  TIMEOUT_MESSAGE,
} from './api'
import type { CampaignResult, Creative } from './types'

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

describe('runCampaign', () => {
  it('posts JSON to /api/campaign and returns parsed JSON', async () => {
    const result = { outcome: 'proceed', input_text: 'x' }
    const fn = mockFetch(200, result)
    const out = await runCampaign({ text: 'hello', budget_usd: 25000 })
    expect(out).toEqual(result)
    expect(fn).toHaveBeenCalledTimes(1)
    const [url, init] = fn.mock.calls[0]
    expect(url).toBe('/api/campaign')
    expect(init.method).toBe('POST')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(init.body)).toEqual({ text: 'hello', budget_usd: 25000 })
  })

  it('includes answers when provided', async () => {
    const fn = mockFetch(200, {})
    await runCampaign({ text: 't', budget_usd: 1, answers: { q: 'a' } })
    expect(JSON.parse(fn.mock.calls[0][1].body).answers).toEqual({ q: 'a' })
  })

  it('throws ApiError with string detail', async () => {
    mockFetch(429, { detail: 'Slow down' })
    await expect(runCampaign({ text: 't', budget_usd: 1 })).rejects.toMatchObject({
      name: 'ApiError',
      status: 429,
      message: 'Slow down',
    })
  })

  it('flattens FastAPI list-shaped 422 detail', async () => {
    mockFetch(422, {
      detail: [
        { loc: ['body', 'text'], msg: 'String should have at least 1 character', type: 'x' },
        { loc: ['body', 'budget_usd'], msg: 'Input should be greater than 0', type: 'y' },
      ],
    })
    const err = await runCampaign({ text: '', budget_usd: 0 }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.message).toContain('String should have at least 1 character')
    expect(err.message).toContain('Input should be greater than 0')
  })

  it('falls back to a friendly message when body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new Error('bad json')
        },
      }),
    )
    const err = await runCampaign({ text: 't', budget_usd: 1 }).catch((e) => e)
    expect(err.status).toBe(502)
    expect(err.message.length).toBeGreaterThan(0)
  })
})

describe('getSamples', () => {
  it('GETs /api/samples', async () => {
    const samples = [{ id: 1, label: 'A', text: 'a' }]
    const fn = mockFetch(200, samples)
    expect(await getSamples()).toEqual(samples)
    expect(fn.mock.calls[0][0]).toBe('/api/samples')
  })
})

describe('network failure', () => {
  it('wraps fetch rejection in ApiError(0) with a friendly message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(getSamples()).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      message: "Can't reach the server — check your connection and try again.",
    })
  })
})

const stage: CampaignResult = {
  input_text: 'dog food',
  budget_usd: null,
  outcome: 'proceed',
  message: null,
  gate: { outcome: 'proceed', confidence: 0.9, threshold: 0.7 },
  brief: { categories: ['pet'] } as unknown as CampaignResult['brief'],
  publishers: [],
  personas: [],
  clarify: [],
  notes: [],
}
const cr: Creative = {
  persona_id: 'a', publisher_id: 'p1', headline: 'H', body: 'B', cta: 'C', why: 'W', fact_violations: [],
}

describe('stage 2 and 3 calls', () => {
  afterEach(() => vi.useRealTimers())

  it('createCreatives posts step 1\'s result as it is with the note, and returns the ads', async () => {
    const fn = mockFetch(200, [cr])
    expect(await createCreatives(stage, 'more playful')).toEqual([cr])
    const [url, init] = fn.mock.calls[0]
    expect(url).toBe('/api/creatives')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ result: stage, note: 'more playful' })
  })

  it('buildConfig sends budget_usd only when given and returns the config with its notes', async () => {
    let fn = mockFetch(200, { config: { campaign_id: 'c' }, notes: ['n'] })
    expect(await buildConfig(stage, [cr], null, '')).toEqual({ config: { campaign_id: 'c' }, notes: ['n'] })
    expect(fn.mock.calls[0][0]).toBe('/api/config')
    expect(JSON.parse(fn.mock.calls[0][1].body)).toEqual({ result: stage, creatives: [cr], budget_usd: null, note: null })
    fn = mockFetch(200, { config: { campaign_id: 'c' }, notes: [] })
    await buildConfig(stage, [cr], 12000, 'cheaper')
    expect(JSON.parse(fn.mock.calls[0][1].body)).toMatchObject({ budget_usd: 12000, note: 'cheaper' })
  })

  it('surfaces the server detail as ApiError', async () => {
    mockFetch(429, { detail: 'Slow down' })
    await expect(createCreatives(stage, '')).rejects.toMatchObject({ status: 429, message: 'Slow down' })
  })

  it('a hung stage call times out with the taking-too-long message', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: string, init: RequestInit) =>
        new Promise((_, rej) => init.signal!.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))),
      ),
    )
    const p = createCreatives(stage, '').catch((e) => e)
    await vi.advanceTimersByTimeAsync(STAGE_TIMEOUT_MS + 10)
    const err = await p
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe(TIMEOUT_MESSAGE)
  })

  it('a caller abort rejects with an AbortError, not a timeout', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: string, init: RequestInit) =>
        new Promise((_, rej) => init.signal!.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))),
      ),
    )
    const ctl = new AbortController()
    const p = createCreatives(stage, '', ctl.signal).catch((e) => e)
    ctl.abort()
    const err = await p
    expect(err.name).toBe('AbortError')
  })
})
