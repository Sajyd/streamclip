/**
 * Drawn illustration of the product's output: a 16:9 live turned into a 9:16
 * captioned clip. It is a schematic, not a capture of a real clip, and is
 * labelled as such.
 */
export function ClipIllustration() {
  return (
    <figure className="relative mx-auto w-full max-w-lg animate-fade-up [animation-delay:180ms]">
      <div
        aria-hidden
        className="animate-soft-pulse absolute -inset-8 -z-10 rounded-full bg-brand-500/25 blur-3xl"
      />
      <div
        aria-hidden
        className="absolute inset-x-8 bottom-8 -z-10 h-24 rounded-full bg-flare-500/15 blur-3xl"
      />

      <div className="flex items-end justify-center gap-4 sm:gap-6">
        {/* Source: the horizontal live */}
        <div className="w-40 shrink-0 pb-8 sm:w-52">
          <div className="relative aspect-video overflow-hidden rounded-2xl border border-white/10 bg-ink-900 shadow-2xl shadow-black/40">
            <div className="absolute inset-0 bg-gradient-to-br from-ink-700/80 via-ink-850 to-ink-950" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_40%,rgba(124,92,255,0.25),transparent_55%)]" />
            <div className="absolute right-2 bottom-2 h-8 w-11 rounded-md border border-white/10 bg-ink-700/80" />
            <span className="absolute top-2 left-2 inline-flex items-center gap-1.5 rounded-md bg-danger-500/95 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white">
              <span className="animate-live-dot size-1.5 rounded-full bg-white" />
              LIVE
            </span>
            <div className="absolute inset-x-2 bottom-2 flex h-5 items-end gap-0.5 pr-14">
              {[3, 5, 4, 8, 12, 16, 9, 6, 4, 5, 3, 4].map((height, index) => (
                <span
                  key={index}
                  className={
                    index >= 3 && index <= 6
                      ? "w-1 rounded-sm bg-brand-400"
                      : "w-1 rounded-sm bg-ink-500"
                  }
                  style={{ height: `${height}px` }}
                />
              ))}
            </div>
          </div>
          <p className="mt-2.5 text-center text-xs text-ink-400">Votre live 16:9</p>
        </div>

        <div className="mb-28 flex flex-col items-center gap-1">
          <svg viewBox="0 0 24 24" aria-hidden className="size-5 text-brand-300 sm:size-6">
            <path
              fill="currentColor"
              d="M13.2 5.3 19.9 12l-6.7 6.7-1.4-1.4 4.3-4.3H4v-2h12.1l-4.3-4.3z"
            />
          </svg>
        </div>

        {/* Output: the vertical clip */}
        <div className="w-32 shrink-0 sm:w-40">
          <div className="relative aspect-[9/16] overflow-hidden rounded-[1.75rem] border border-white/15 bg-ink-900 shadow-2xl shadow-brand-500/25">
            <div className="absolute inset-0 bg-gradient-to-b from-brand-600/55 via-ink-850 to-flare-500/35" />
            <div className="absolute inset-x-0 top-[16%] mx-auto size-14 rounded-full border border-white/20 bg-white/10 sm:size-16" />
            <div className="absolute inset-x-3 bottom-[22%] space-y-1.5 text-center">
              <span className="inline-block rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white sm:text-[11px]">
                ATTENDS, REGARDE
              </span>
              <span className="inline-block rounded-md bg-brand-500 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white sm:text-[11px]">
                CE MOMENT !
              </span>
            </div>
            <div className="absolute inset-x-3 bottom-3 h-1 overflow-hidden rounded-full bg-white/20">
              <div className="h-full w-2/3 rounded-full bg-white" />
            </div>
            <span className="absolute top-2.5 right-2.5 rounded-md bg-black/55 px-1.5 py-0.5 font-mono text-[10px] text-white">
              0:52
            </span>
          </div>
          <p className="mt-2.5 text-center text-xs text-ink-400">Clip 9:16 sous-titré</p>
        </div>
      </div>
      <figcaption className="mt-5 text-center text-xs text-ink-500">
        Illustration schématique du principe.
      </figcaption>
    </figure>
  );
}
