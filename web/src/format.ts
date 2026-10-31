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

/** Parses a typed budget: blank → null (use the recommendation), else the whole dollars. */
export function parseOptionalBudget(s: string): number | null {
  const digits = s.replace(/[^\d]/g, '')
  return digits ? Number(digits) : null
}

/** A user-facing problem with a typed budget, or null when it is blank or in range. */
export function budgetProblem(n: number | null): string | null {
  if (n == null) return null
  if (n < BUDGET_MIN || n > BUDGET_MAX)
    return `Enter a monthly budget between ${usd(BUDGET_MIN)} and ${usd(BUDGET_MAX)}.`
  return null
}
