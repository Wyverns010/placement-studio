// Static catalog data bundled from the repo's data/ folder (single source of truth).
import publishersJson from '../../data/publishers.json'
import personasJson from '../../data/shopper_personas.json'

export interface CatalogPublisher {
  id: string
  name: string
  category: string
  monthly_impressions: number
  avg_order_value_usd: number
}

export interface CatalogPersona {
  id: string
  name: string
  messaging_preferences: string[]
}

const publishers = publishersJson as CatalogPublisher[]
const personas = personasJson as CatalogPersona[]

export const publisherById = (id: string): CatalogPublisher | undefined =>
  publishers.find((p) => p.id === id)

export const personaById = (id: string): CatalogPersona | undefined =>
  personas.find((p) => p.id === id)

export function reachLabel(impressions: number): string {
  return impressions >= 1_000_000
    ? `${+(impressions / 1_000_000).toFixed(1)}M/mo`
    : `${Math.round(impressions / 1000)}K/mo`
}
