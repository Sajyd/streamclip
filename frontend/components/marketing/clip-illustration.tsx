/**
 * Drawn 3D illustration of the product's output: a 16:9 live turned into a
 * 9:16 captioned clip. Schematic, not a capture of a real clip.
 */
export function ClipIllustration() {
  return (
    <figure className="relative mx-auto w-full max-w-xl animate-fade-up [animation-delay:160ms]">
      <div
        aria-hidden
        className="animate-soft-pulse absolute top-1/2 left-1/2 -z-10 h-72 w-72 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand-500/30 blur-3xl"
      />
      <div
        aria-hidden
        className="absolute right-6 bottom-10 -z-10 h-40 w-40 rounded-full bg-flare-500/20 blur-3xl"
      />

      <div
        className="relative mx-auto flex h-[420px] items-center justify-center sm:h-[460px]"
        style={{ perspective: "1100px" }}
      >
        {/* Floor shadow */}
        <div
          aria-hidden
          className="absolute bottom-8 left-1/2 h-10 w-64 -translate-x-1/2 rounded-[100%] bg-black/55 blur-xl"
        />

        {/* Back plane */}
        <div
          aria-hidden
          className="absolute h-56 w-72 rounded-3xl border border-white/5 bg-ink-800/40 shadow-2xl"
          style={{ transform: "rotateX(12deg) rotateY(22deg) translateZ(-80px)" }}
        />

        {/* Source live — mid layer */}
        <div
          className="absolute animate-float-3d"
          style={{ transformStyle: "preserve-3d", transform: "rotateX(8deg) rotateY(-18deg) translate(-78px, 18px)" }}
        >
          <div className="depth-panel relative w-52 overflow-hidden rounded-2xl sm:w-60">
            <div className="relative aspect-video">
              <div className="absolute inset-0 bg-gradient-to-br from-ink-700 via-ink-850 to-ink-950" />
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_28%_36%,rgba(59,130,246,0.35),transparent_55%)]" />
              <div className="absolute right-2.5 bottom-2.5 h-9 w-12 rounded-md border border-white/15 bg-ink-700/90 shadow-lg" />
              <span className="absolute top-2.5 left-2.5 inline-flex items-center gap-1.5 rounded-md bg-danger-500 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white shadow-md">
                <span className="animate-live-dot size-1.5 rounded-full bg-white" />
                LIVE
              </span>
              <div className="absolute inset-x-2.5 bottom-2.5 flex h-5 items-end gap-0.5 pr-16">
                {[3, 5, 4, 8, 12, 16, 9, 6, 4, 5, 3, 4].map((height, index) => (
                  <span
                    key={index}
                    className={
                      index >= 3 && index <= 6
                        ? "w-1 rounded-sm bg-brand-400 shadow-[0_0_8px_rgba(96,165,250,0.7)]"
                        : "w-1 rounded-sm bg-ink-500"
                    }
                    style={{ height: `${height}px` }}
                  />
                ))}
              </div>
            </div>
          </div>
          <p className="mt-3 text-center text-xs font-medium tracking-wide text-ink-400">
            Live 16:9
          </p>
        </div>

        {/* Connector chip */}
        <div
          aria-hidden
          className="absolute z-10 flex size-11 items-center justify-center rounded-2xl border border-white/15 bg-ink-850 text-brand-300 shadow-xl shadow-brand-500/20"
          style={{ transform: "translate(8px, -12px) rotateX(10deg) rotateY(-8deg) translateZ(40px)" }}
        >
          <svg viewBox="0 0 24 24" className="size-5">
            <path
              fill="currentColor"
              d="M13.2 5.3 19.9 12l-6.7 6.7-1.4-1.4 4.3-4.3H4v-2h12.1l-4.3-4.3z"
            />
          </svg>
        </div>

        {/* Output phone — front layer */}
        <div
          className="absolute animate-float"
          style={{
            transformStyle: "preserve-3d",
            transform: "rotateX(6deg) rotateY(14deg) translate(86px, -10px) translateZ(60px)",
            animationDelay: "0.6s",
          }}
        >
          <div className="depth-panel relative w-36 overflow-hidden rounded-[1.85rem] sm:w-40">
            <div className="relative aspect-[9/16]">
              <div className="absolute inset-0 bg-gradient-to-b from-brand-600/70 via-ink-850 to-flare-500/40" />
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_28%,rgba(255,255,255,0.18),transparent_40%)]" />
              <div className="absolute inset-x-0 top-[15%] mx-auto size-14 rounded-full border border-white/25 bg-white/10 shadow-inner sm:size-16" />
              <div className="absolute inset-x-3 bottom-[22%] space-y-1.5 text-center">
                <span className="inline-block rounded-md bg-black/75 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white shadow-sm sm:text-[11px]">
                  ATTENDS, REGARDE
                </span>
                <span className="inline-block rounded-md bg-brand-500 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white shadow-md shadow-brand-500/40 sm:text-[11px]">
                  CE MOMENT !
                </span>
              </div>
              <div className="absolute inset-x-3 bottom-3 h-1 overflow-hidden rounded-full bg-white/20">
                <div className="h-full w-2/3 rounded-full bg-white shadow-[0_0_10px_rgba(255,255,255,0.5)]" />
              </div>
              <span className="absolute top-3 right-3 rounded-md bg-black/55 px-1.5 py-0.5 font-mono text-[10px] text-white">
                0:52
              </span>
            </div>
          </div>
          <p className="mt-3 text-center text-xs font-medium tracking-wide text-ink-400">
            Clip 9:16
          </p>
        </div>
      </div>

      <figcaption className="mt-1 text-center text-xs text-ink-500">
        Illustration schématique du principe.
      </figcaption>
    </figure>
  );
}
