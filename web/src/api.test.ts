import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getSamples, runCampaign, streamCampaign } from './api'

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

describe('streamCampaign (stub)', () => {
  it('runs the campaign and emits done; cancel suppresses events', async () => {
    mockFetch(200, { outcome: 'proceed' })
    const events: string[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e.stage))
    await vi.waitFor(() => expect(events).toEqual(['done']))

    const cancelled: string[] = []
    const cancel = streamCampaign({ text: 't', budget_usd: 1 }, (e) => cancelled.push(e.stage))
    cancel()
    await new Promise((r) => setTimeout(r, 10))
    expect(cancelled).toEqual([])
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
