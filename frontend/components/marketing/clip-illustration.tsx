/**
 * Drawn illustration of the product's output: a 16:9 live turned into a 9:16
 * captioned clip. It is a schematic, not a capture of a real clip, and is
 * labelled as such.
 */
export function ClipIllustration() {
  return (
    <figure className="relative mx-auto w-full max-w-md">
      <div
        aria-hidden
        className="absolute -inset-10 -z-10 rounded-full bg-brand-500/20 blur-3xl"
      />
      <div className="flex items-end justify-center gap-5">
        {/* Source: the horizontal live */}
        <div className="w-44 shrink-0 pb-6 sm:w-52">
          <div className="surface relative aspect-video overflow-hidden p-0">
            <div className="absolute inset-0 bg-gradient-to-br from-ink-700 via-ink-800 to-ink-900" />
            <div className="absolute bottom-2 right-2 h-9 w-12 rounded-md border border-ink-500 bg-ink-600" />
            <span className="absolute left-2 top-2 inline-flex items-center gap-1.5 rounded bg-danger-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
              <span className="size-1.5 rounded-full bg-white" />
              LIVE
            </span>
            <div className="absolute inset-x-2 bottom-2 flex h-5 items-end gap-0.5 pr-14">
              {[3, 5, 4, 8, 12, 16, 9, 6, 4, 5, 3, 4].map((height, index) => (
                <span
                  key={index}
                  className={index >= 3 && index <= 6 ? "w-1 rounded-sm bg-brand-400" : "w-1 rounded-sm bg-ink-500"}
                  style={{ height: `${height}px` }}
                />
              ))}
            </div>
          </div>
          <p className="mt-2 text-center text-xs text-ink-400">Votre live 16:9</p>
        </div>

        <svg viewBox="0 0 24 24" aria-hidden className="mb-24 size-6 shrink-0 text-brand-300">
          <path fill="currentColor" d="M13.2 5.3 19.9 12l-6.7 6.7-1.4-1.4 4.3-4.3H4v-2h12.1l-4.3-4.3z" />
        </svg>

        {/* Output: the vertical clip */}
        <div className="w-36 shrink-0 sm:w-40">
          <div className="relative aspect-[9/16] overflow-hidden rounded-[1.6rem] border-4 border-ink-700 bg-ink-900 shadow-2xl shadow-brand-500/20">
            <div className="absolute inset-0 bg-gradient-to-b from-brand-600/50 via-ink-800 to-flare-500/40" />
            <div className="absolute inset-x-0 top-[18%] mx-auto size-16 rounded-full border border-white/20 bg-white/10" />
            <div className="absolute inset-x-3 bottom-[22%] space-y-1 text-center">
              <span className="inline-block rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-bold text-white">
                ATTENDS, REGARDE
              </span>
              <span className="inline-block rounded bg-brand-500 px-1.5 py-0.5 text-[11px] font-bold text-white">
                CE MOMENT !
              </span>
            </div>
            <div className="absolute inset-x-3 bottom-3 h-1 overflow-hidden rounded-full bg-white/20">
              <div className="h-full w-2/3 rounded-full bg-white" />
            </div>
            <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white">
              0:52
            </span>
          </div>
          <p className="mt-2 text-center text-xs text-ink-400">Clip 9:16 sous-titré</p>
        </div>
      </div>
      <figcaption className="mt-4 text-center text-xs text-ink-500">
        Illustration schématique du principe.
      </figcaption>
    </figure>
  );
}
