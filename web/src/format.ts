/** Budget input text: blank for null, otherwise digits with separators (0 stays visible). */
export function formatBudget(n: number | null): string {
  return n != null && Number.isFinite(n) ? n.toLocaleString('en-US') : ''
}

const TIER_LABEL: Record<string, string> = {
  value: 'Value',
  mid: 'Mid-market',
  premium: 'Premium',
  luxury: 'Luxury',
}

export function tierLabel(t: string): string | null {
  return TIER_LABEL[t] ?? null
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

export const clamp01 = (n: number): number => Math.max(0, Math.min(1, n))

export function usd(n: number): string {
  return '$' + Math.round(n).toLocaleString('en-US')
}

export function pct(share: number): string {
  return `${Math.round(share * 100)}%`
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

const TOKEN = /("(?:\\.|[^"\\])*")(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g

/**
 * Pretty-prints `obj` as HTML with `.k` (keys), `.s` (strings) and `.n`
 * (numbers/booleans/null) spans. Every piece of text is escaped, so the result
 * is safe for dangerouslySetInnerHTML.
 */
export function jsonHighlight(obj: unknown): string {
  const text = JSON.stringify(obj, null, 2) ?? 'null'
  let out = ''
  let last = 0
  for (const m of text.matchAll(TOKEN)) {
    out += esc(text.slice(last, m.index))
    if (m[1] !== undefined) {
      const cls = m[2] ? 'k' : 's'
      out += `<span class="${cls}">"${esc(m[1].slice(1, -1))}"</span>${esc(m[2] ?? '')}`
    } else {
      out += `<span class="n">${m[0]}</span>`
    }
    last = m.index + m[0].length
  }
  return out + esc(text.slice(last))
}

/** Rewrites snake_case tokens inside free text as plain words: "pet_food" -> "pet food". */
export function humanise(s: string): string {
  return s.replace(/\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b/g, (m) => m.replace(/_/g, ' '))
}

// Matches budget.min_usd / max_usd in config/tuning.yaml.
export const BUDGET_MIN = 500
export const BUDGET_MAX = 5_000_000

export type BudgetParse = { ok: true; value: number | null } | { ok: false; error: string }

/**
 * Parses a typed monthly budget. Blank → null (use the recommendation). Only "$", commas and
 * spaces are ignored; anything else must be a plain decimal number ("12,000.00", "$5,000",
 * "5000.5" → 5001). Exponents, other characters and out-of-range values are errors.
 */
export function parseBudgetInput(s: string): BudgetParse {
  const t = s.replace(/[$,\s]/g, '')
  if (!t) return { ok: true, value: null }
  if (!/^\d+(\.\d+)?$/.test(t)) return { ok: false, error: 'Enter a dollar amount, like 12,000.' }
  const n = Number(t)
  if (!Number.isFinite(n)) return { ok: false, error: budgetProblem(Infinity)! }
  const value = Math.round(n)
  const problem = budgetProblem(value)
  return problem ? { ok: false, error: problem } : { ok: true, value }
}

/** A user-facing problem with a typed budget, or null when it is blank or in range. */
export function budgetProblem(n: number | null): string | null {
  if (n == null) return null
  if (n < BUDGET_MIN || n > BUDGET_MAX)
    return `Enter a monthly budget between ${usd(BUDGET_MIN)} and ${usd(BUDGET_MAX)}.`
  return null
}
