import { pct } from '../format'
import { personaById } from '../catalog'
import type { Creative, PersonaScore, PublisherScore } from '../types'

const FACTOR_LABEL: Record<string, string> = {
  affinity: 'Category',
  publishers: 'Your publishers',
  price: 'Price',
  age: 'Age',
}

/**
 * Persona cards. Without `creatives` it is a plain persona list; with them each card shows its ad.
 */
export default function PersonasTab({
  personas,
  creatives,
  publishers,
}: {
  personas: PersonaScore[]
  creatives?: Creative[]
  publishers: PublisherScore[]
}) {
  const withAds = creatives != null
  return (
    <div className="grid gap-[18px] min-[700px]:grid-cols-2 min-[1000px]:grid-cols-3">
      {personas.map((p) => {
        const cr = creatives?.find((c) => c.persona_id === p.persona_id)
        const pubName = cr
          ? (publishers.find((x) => x.publisher_id === cr.publisher_id)?.name ?? cr.publisher_id)
          : null
        const tags = personaById(p.persona_id)?.messaging_preferences ?? []
        return (
          <article
            key={p.persona_id}
            aria-label={p.name}
            className="flex flex-col overflow-hidden rounded-[18px] border border-line bg-white"
          >
            <div className="border-b border-line bg-[#faf8fe] px-[18px] py-4">
              <h4 className="m-0 flex items-baseline justify-between gap-2 text-base font-semibold">
                {p.name}
                <span className="font-bold text-violet-dark">{pct(p.fit)}</span>
              </h4>
              {cr && (
                <p className="m-0 mt-2 text-[12.5px] leading-normal text-[#3b3850]">
                  {p.stretch && <b>Stretch: </b>}
                  {cr.why.replace(/_/g, ' ')}
                </p>
              )}
              {!withAds && p.factors.length > 0 && (
                <ul data-testid="persona-factors" className="m-0 mt-2.5 list-none space-y-1 p-0 text-[12px]">
                  {p.factors.map((f) => (
                    <li key={f.name} className="flex justify-between gap-2">
                      <span className="min-w-0 text-[#3b3850]">
                        <span className="text-muted">{FACTOR_LABEL[f.name] ?? f.name.replace(/_/g, ' ')}: </span>
                        {f.note.replace(/_/g, ' ')}
                      </span>
                      <span className={`shrink-0 font-semibold ${f.score < 0 ? 'text-bad' : 'text-violet-dark'}`}>
                        {f.score < 0 ? `−${pct(-f.score)}` : pct(f.score)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {tags.length > 0 && (
                <div className="mt-2.5 flex flex-wrap gap-[5px]">
                  {tags.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-violet-soft px-2 py-[3px] text-[11px] text-violet-dark"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {!withAds ? null : cr ? (
              <>
              <div
                className="m-[16px_18px_18px] rounded-[14px] border border-line p-3.5"
                style={{ boxShadow: '0 10px 24px -20px #3b1d7a' }}
              >
                <div className="text-[10.5px] tracking-[0.06em] text-muted uppercase">
                  Sponsored · on {pubName}
                </div>
                <div className="my-1.5 text-[17px] leading-tight font-bold">{cr.headline}</div>
                <p className="m-0 text-[13px] leading-normal text-[#3b3850]">{cr.body}</p>
                <span className="mt-3 inline-block rounded-full bg-ink px-[13px] py-[7px] text-xs text-white">
                  {cr.cta}
                </span>
                {cr.fact_violations.map((v) => (
                  <div
                    key={v}
                    className="mt-2.5 rounded-lg bg-warn-soft px-2.5 py-1.5 text-[11.5px] font-medium text-warn"
                  >
                    Check: {v}
                  </div>
                ))}
              </div>
              </>
            ) : (
              <p className="m-[16px_18px] text-[13px] text-muted">No creative generated.</p>
            )}
          </article>
        )
      })}
    </div>
  )
}
