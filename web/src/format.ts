export function formatBudget(n: number): string {
  return Number.isFinite(n) && n > 0 ? n.toLocaleString('en-US') : ''
}

export function parseBudget(s: string): number {
  const digits = s.replace(/[^\d]/g, '')
  return digits ? Number(digits) : 0
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
