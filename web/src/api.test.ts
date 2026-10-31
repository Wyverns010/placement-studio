import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildConfig,
  createCreatives,
  getSamples,
  regenerateCreative,
  runCampaign,
  STAGE_TIMEOUT_MS,
  streamCampaign,
  TIMEOUT_MESSAGE,
} from './api'
import type { ConfigPayload, Creative, StagePayload } from './types'

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

class FakeES {
  static instances: FakeES[] = []
  url: string
  closed = false
  listeners: Record<string, ((e: unknown) => void)[]> = {}
  constructor(url: string) {
    this.url = url
    FakeES.instances.push(this)
  }
  addEventListener(t: string, fn: (e: unknown) => void) {
    ;(this.listeners[t] ||= []).push(fn)
  }
  close() {
    this.closed = true
  }
  emit(t: string, data?: unknown) {
    const ev = data === undefined ? new Event(t) : Object.assign(new Event(t), { data: JSON.stringify(data) })
    this.listeners[t]?.forEach((f) => f(ev))
  }
}

describe('streamCampaign', () => {
  beforeEach(() => {
    FakeES.instances = []
    vi.stubGlobal('EventSource', FakeES)
  })
  afterEach(() => vi.useRealTimers())

  it('opens the stream URL with text, budget and answers', () => {
    streamCampaign({ text: 'a b', budget_usd: 100, answers: { q: 'x' } }, () => {})
    const u = new URL(FakeES.instances[0].url, 'http://x')
    expect(u.pathname).toBe('/api/campaign/stream')
    expect(u.searchParams.get('text')).toBe('a b')
    expect(u.searchParams.get('budget_usd')).toBe('100')
    expect(JSON.parse(u.searchParams.get('answers')!)).toEqual({ q: 'x' })
  })

  it('omits budget_usd from the stream URL when no budget was given', () => {
    streamCampaign({ text: 't' }, () => {})
    const u = new URL(FakeES.instances[0].url, 'http://x')
    expect(u.searchParams.has('budget_usd')).toBe(false)
  })

  it('listens only for stage-1 events (no creatives/config)', () => {
    streamCampaign({ text: 't' }, () => {})
    const names = Object.keys(FakeES.instances[0].listeners)
    expect(names).toEqual(expect.arrayContaining(['understood', 'gate', 'publishers', 'personas', 'done', 'error']))
    expect(names).not.toContain('creatives')
    expect(names).not.toContain('config')
  })

  it('calls onEvent once per message in order and closes on done', () => {
    const events: [string, unknown][] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push([e.stage, e.data]))
    const es = FakeES.instances[0]
    es.emit('understood', { a: 1 })
    es.emit('gate', { confidence: 0.9 })
    expect(es.closed).toBe(false)
    es.emit('done', { outcome: 'proceed' })
    expect(events.map((e) => e[0])).toEqual(['understood', 'gate', 'done'])
    expect(events[1][1]).toEqual({ confidence: 0.9 })
    expect(es.closed).toBe(true)
  })

  it('maps a server error event to stage error with its message, then closes', () => {
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    const es = FakeES.instances[0]
    es.emit('error', { message: 'LLM exploded' })
    expect(events).toEqual([{ stage: 'error', data: { message: 'LLM exploded' } }])
    expect(es.closed).toBe(true)
  })

  it('cancel closes the source and suppresses later events', () => {
    const events: string[] = []
    const cancel = streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e.stage))
    const es = FakeES.instances[0]
    cancel()
    es.emit('gate', {})
    expect(es.closed).toBe(true)
    expect(events).toEqual([])
  })

  it('times out after 30 s without an event (timer resets per event)', () => {
    vi.useFakeTimers()
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    const es = FakeES.instances[0]
    vi.advanceTimersByTime(20000)
    es.emit('understood', {})
    vi.advanceTimersByTime(29000)
    expect(events.map((e) => e.stage)).toEqual(['understood'])
    vi.advanceTimersByTime(1500)
    expect(events.at(-1)).toEqual({
      stage: 'error',
      data: { message: 'The AI service is taking too long — try again or pick a sample.' },
    })
    expect(es.closed).toBe(true)
  })

  it('a connection error before any event falls back to POST and surfaces the server detail', async () => {
    mockFetch(422, { detail: 'Text is too long.' })
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    const es = FakeES.instances[0]
    es.emit('error')
    expect(es.closed).toBe(true)
    await vi.waitFor(() => expect(events).toHaveLength(1))
    expect(events[0]).toEqual({ stage: 'error', data: { message: 'Text is too long.' } })
  })

  it('a hung fallback POST times out with the taking-too-long error', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit) =>
      new Promise((_r, rej) => init.signal!.addEventListener('abort', () => rej(new DOMException('x', 'AbortError'))))))
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    FakeES.instances[0].emit('error')
    await vi.advanceTimersByTimeAsync(30500)
    expect(events).toEqual([{ stage: 'error', data: { message: 'The AI service is taking too long — try again or pick a sample.' } }])
  })

  it('cancel aborts the fallback fetch', async () => {
    let signal!: AbortSignal
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit) => {
      signal = init.signal!
      return new Promise(() => {})
    }))
    const events: string[] = []
    const cancel = streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e.stage))
    FakeES.instances[0].emit('error')
    expect(signal.aborted).toBe(false)
    cancel()
    expect(signal.aborted).toBe(true)
    expect(events).toEqual([])
  })

  it('a late pre-first-event drop (>3 s) reports the connection error without POSTing', () => {
    vi.useFakeTimers()
    const fn = mockFetch(200, {})
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    vi.advanceTimersByTime(4000)
    FakeES.instances[0].emit('error')
    expect(events[0].stage).toBe('error')
    expect(String(events[0].data.message)).toMatch(/connection dropped/)
    expect(fn).not.toHaveBeenCalled()
  })

  it('a done without an outcome is an error, not results', () => {
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    const es = FakeES.instances[0]
    es.emit('done', { nope: 1 })
    expect(events).toEqual([{ stage: 'error', data: { message: 'Something went wrong building this campaign.' } }])
    expect(es.closed).toBe(true)
  })

  it('a fast native error (<3 s) falls back to POST and surfaces the server detail', async () => {
    vi.useFakeTimers()
    const fn = mockFetch(429, { detail: 'Too many requests, slow down' })
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    vi.advanceTimersByTime(2000)
    FakeES.instances[0].emit('error')
    await vi.advanceTimersByTimeAsync(0)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(events).toEqual([{ stage: 'error', data: { message: 'Too many requests, slow down' } }])
  })

  it('a `null` done payload is a bad-result error (no throw)', () => {
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    FakeES.instances[0].emit('done', null)
    expect(events).toEqual([{ stage: 'error', data: { message: 'Something went wrong building this campaign.' } }])
  })

  it('a bad done on the fallback path is a bad-result error', async () => {
    mockFetch(200, { nope: 1 })
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    FakeES.instances[0].emit('error')
    await vi.waitFor(() => expect(events).toHaveLength(1))
    expect(events[0]).toEqual({ stage: 'error', data: { message: 'Something went wrong building this campaign.' } })
  })

  it('a connection error after events reports a lost connection without refetching', () => {
    const fn = mockFetch(200, {})
    const events: { stage: string; data: Record<string, unknown> }[] = []
    streamCampaign({ text: 't', budget_usd: 1 }, (e) => events.push(e))
    const es = FakeES.instances[0]
    es.emit('understood', {})
    es.emit('error')
    expect(events.at(-1)?.stage).toBe('error')
    expect(fn).not.toHaveBeenCalled()
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

const stage: StagePayload = {
  stage_token: 'tok_1',
  input_text: 'dog food',
  gate: { outcome: 'proceed', confidence: 0.9, threshold: 0.7, impl: 'llm', signals: {} },
  brief: { categories: ['pet'] } as unknown as StagePayload['brief'],
  publishers: [],
  personas: [],
}
const cr: Creative = {
  creative_id: 'cr_a', persona_id: 'a', publisher_id: 'p1', headline: 'H', body: 'B', cta: 'C', why: 'W', fact_violations: [],
}

describe('stage 2 and 3 calls', () => {
  afterEach(() => vi.useRealTimers())

  it('createCreatives posts the stage-1 payload with its stage_token and unwraps creatives', async () => {
    const fn = mockFetch(200, { creatives: [cr] })
    expect(await createCreatives(stage)).toEqual([cr])
    const [url, init] = fn.mock.calls[0]
    expect(url).toBe('/api/creatives')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual(stage)
    expect(JSON.parse(init.body).stage_token).toBe('tok_1')
  })

  it('a 403 (changed or expired campaign) surfaces as ApiError 403 with the detail', async () => {
    mockFetch(403, { detail: 'This campaign changed or expired — run it again.' })
    await expect(createCreatives(stage)).rejects.toMatchObject({ status: 403, message: /changed or expired/ })
  })

  it('regenerateCreative sends persona_id and a trimmed note, unwraps creative', async () => {
    const fn = mockFetch(200, { creative: { ...cr, headline: 'New' } })
    const out = await regenerateCreative({ ...stage, creatives: [cr] }, 'a', '  warmer  ')
    expect(out.headline).toBe('New')
    const [url, init] = fn.mock.calls[0]
    expect(url).toBe('/api/creatives/regenerate')
    expect(JSON.parse(init.body)).toEqual({ ...stage, creatives: [cr], persona_id: 'a', note: 'warmer' })
  })

  it('regenerateCreative omits an empty note', async () => {
    const fn = mockFetch(200, { creative: cr })
    await regenerateCreative({ ...stage, creatives: [cr] }, 'a', '   ')
    expect(JSON.parse(fn.mock.calls[0][1].body)).not.toHaveProperty('note')
  })

  it('buildConfig sends budget_usd only when given and unwraps config', async () => {
    const payload: ConfigPayload = { ...stage, creatives: [cr] }
    let fn = mockFetch(200, { config: { campaign_id: 'c' } })
    expect(await buildConfig(payload)).toEqual({ campaign_id: 'c' })
    expect(fn.mock.calls[0][0]).toBe('/api/config')
    expect(JSON.parse(fn.mock.calls[0][1].body)).not.toHaveProperty('budget_usd')
    fn = mockFetch(200, { config: { campaign_id: 'c' } })
    await buildConfig(payload, 12000)
    expect(JSON.parse(fn.mock.calls[0][1].body).budget_usd).toBe(12000)
  })

  it('surfaces the server detail as ApiError', async () => {
    mockFetch(429, { detail: 'Slow down' })
    await expect(createCreatives(stage)).rejects.toMatchObject({ status: 429, message: 'Slow down' })
  })

  it('a hung stage call times out with the taking-too-long message', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: string, init: RequestInit) =>
        new Promise((_, rej) => init.signal!.addEventListener('abort', () => rej(new DOMException('a', 'AbortError')))),
      ),
    )
    const p = createCreatives(stage).catch((e) => e)
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
    const p = createCreatives(stage, ctl.signal).catch((e) => e)
    ctl.abort()
    const err = await p
    expect(err.name).toBe('AbortError')
  })
})
