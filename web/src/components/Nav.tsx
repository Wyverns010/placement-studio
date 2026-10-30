const REPO = 'https://github.com/Wyverns010/placement-studio'

const LINKS: [string, string][] = [
  ['Prompts', `${REPO}/tree/main/prompts`],
  ['Evals', `${REPO}/tree/main/evals`],
]

export default function Nav({ onHome }: { onHome: () => void }) {
  return (
    <nav className="flex items-center justify-between gap-4 border-b border-line py-[18px]">
      <button
        type="button"
        onClick={onHome}
        className="flex cursor-pointer items-center gap-2.5 border-0 bg-transparent p-0 text-[19px] font-bold text-ink"
        aria-label="Placement Studio home"
      >
        <span
          className="h-[30px] w-[30px] rounded-full"
          style={{ background: 'linear-gradient(135deg,#7c3aed,#5b21b6)' }}
        />
        <span>
          Placement <span className="font-normal text-muted">Studio</span>
        </span>
      </button>
      <div className="hidden gap-[26px] text-sm md:flex">
        {LINKS.map(([label, href]) => (
          <a
            key={label}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#3b3850] no-underline hover:text-violet-dark"
          >
            {label}
          </a>
        ))}
      </div>
      <a href={REPO} target="_blank" rel="noopener noreferrer" className="pill pill-sm no-underline">
        GitHub
      </a>
    </nav>
  )
}
