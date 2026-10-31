import { describe, expect, it } from 'vitest'
import { budgetProblem, formatBudget, humanise, jsonHighlight, parseBudgetInput, pct, usd } from './format'

describe('usd / pct', () => {
  it('formats dollars with separators', () => {
    expect(usd(25000)).toBe('$25,000')
    expect(usd(1234.56)).toBe('$1,235')
    expect(usd(0)).toBe('$0')
  })
  it('formats shares as whole percents', () => {
    expect(pct(0.41)).toBe('41%')
    expect(pct(0.125)).toBe('13%')
  })
})

describe('jsonHighlight', () => {
  it('wraps keys, strings and numbers in spans', () => {
    const html = jsonHighlight({ a: 1, b: 'x', c: [true, null] })
    expect(html).toContain('<span class="k">"a"</span>')
    expect(html).toContain('<span class="n">1</span>')
    expect(html).toContain('<span class="s">"x"</span>')
    expect(html).toContain('<span class="n">true</span>')
    expect(html).toContain('<span class="n">null</span>')
  })
  it('escapes markup in string values and keys', () => {
    const html = jsonHighlight({ '<k>': '<script>alert("x")</script> & co' })
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<k>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('&amp; co')
    expect(html).toContain('&quot;')
  })
  it('round-trips to pretty JSON once tags are stripped', () => {
    const obj = { n: { x: [1, 2], s: 'a<b' } }
    const text = jsonHighlight(obj)
      .replace(/<[^>]+>/g, '')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&amp;/g, '&')
    expect(JSON.parse(text)).toEqual(obj)
    expect(text).toBe(JSON.stringify(obj, null, 2))
  })
})

describe('humanise', () => {
  it('turns snake_case tokens into words and leaves the rest alone', () => {
    expect(humanise('interests pet_food, wellness_dtc, US')).toBe('interests pet food, wellness dtc, US')
    expect(humanise('$42 target CPA')).toBe('$42 target CPA')
  })
})

describe('optional budget', () => {
  it('blank means use the recommendation; $, commas and spaces are ignored', () => {
    expect(parseBudgetInput('')).toEqual({ ok: true, value: null })
    expect(parseBudgetInput('  ')).toEqual({ ok: true, value: null })
    expect(parseBudgetInput('$5,000')).toEqual({ ok: true, value: 5000 })
    expect(parseBudgetInput('12,000.00')).toEqual({ ok: true, value: 12000 })
    expect(parseBudgetInput(' 12 000 ')).toEqual({ ok: true, value: 12000 })
  })
  it('rounds to whole dollars', () => {
    expect(parseBudgetInput('5000.5')).toEqual({ ok: true, value: 5001 })
    expect(parseBudgetInput('5000.4')).toEqual({ ok: true, value: 5000 })
  })
  it('rejects exponents, junk, out-of-range and huge values', () => {
    for (const bad of ['1e3', '12abc', '-5000', '5.000.0', '0', '100', '999999999999999999999', '9'.repeat(400)]) {
      expect(parseBudgetInput(bad).ok, bad).toBe(false)
    }
    expect(parseBudgetInput('999999999999999999999')).toMatchObject({ error: expect.stringMatching(/between \$500 and \$5,000,000/) })
    expect(parseBudgetInput('1e3')).toMatchObject({ error: expect.stringMatching(/dollar amount/) })
  })
  it('formats with separators and keeps 0 visible', () => {
    expect(formatBudget(null)).toBe('')
    expect(formatBudget(0)).toBe('0')
    expect(formatBudget(12000)).toBe('12,000')
  })
  it('only flags a typed budget outside $500–$5,000,000', () => {
    expect(budgetProblem(null)).toBeNull()
    expect(budgetProblem(500)).toBeNull()
    expect(budgetProblem(5_000_000)).toBeNull()
    expect(budgetProblem(499)).toMatch(/between \$500 and \$5,000,000/)
    expect(budgetProblem(5_000_001)).not.toBeNull()
  })
})
