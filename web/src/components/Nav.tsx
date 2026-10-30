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
      <div className="hidden gap-[26px] text-sm text-[#3b3850] md:flex">
        <span>How it works</span>
        <span>Publishers</span>
        <span>Personas</span>
        <span>Prompts</span>
      </div>
      <a
        href="https://github.com/"
        target="_blank"
        rel="noreferrer"
        className="pill pill-sm no-underline"
      >
        GitHub
      </a>
    </nav>
  )
}
