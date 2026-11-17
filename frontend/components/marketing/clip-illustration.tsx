/**
 * Drawn 3D illustration of the product's output: a 16:9 live turned into a
 * 9:16 captioned clip. Schematic, not a capture of a real clip.
 *
 * Float animations sit on an inner wrapper so they never overwrite the
 * outer 3D transform (rotate / translateZ).
 */
export function ClipIllustration() {
  return (
    <figure className="relative mx-auto w-full max-w-xl animate-fade-up [animation-delay:160ms]">
      <div
        aria-hidden
        className="animate-soft-pulse absolute top-1/2 left-1/2 -z-10 h-80 w-80 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand-500/35 blur-3xl"
      />
      <div
        aria-hidden
        className="absolute right-4 bottom-12 -z-10 h-44 w-44 rounded-full bg-brand-400/20 blur-3xl"
      />

      <div
        className="relative mx-auto h-[420px] w-full sm:h-[460px]"
        style={{ perspective: "1200px" }}
      >
        {/* Floor shadow */}
        <div
          aria-hidden
          className="absolute bottom-6 left-1/2 h-12 w-72 -translate-x-1/2 rounded-[100%] bg-black/60 blur-2xl"
        />

        {/* Back depth plane */}
        <div
          aria-hidden
          className="absolute top-16 left-1/2 h-52 w-80 -translate-x-1/2 rounded-3xl border border-white/5 bg-ink-850/50"
          style={{ transform: "translateX(-50%) rotateX(14deg) rotateY(18deg) translateZ(-90px)" }}
        />

        {/* Source: 16:9 live monitor */}
        <div
          className="absolute top-[18%] left-[4%] z-[1] w-[54%] max-w-[260px] sm:left-[6%]"
          style={{ transform: "rotateX(10deg) rotateY(-22deg) translateZ(20px)", transformStyle: "preserve-3d" }}
        >
          <div className="animate-float" style={{ animationDuration: "6.2s" }}>
            <div className="depth-panel overflow-hidden rounded-2xl">
              {/* Bezel */}
              <div className="border-b border-white/10 bg-ink-900/90 px-3 py-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full bg-white/25" />
                  <span className="size-1.5 rounded-full bg-white/25" />
                  <span className="size-1.5 rounded-full bg-white/25" />
                  <span className="ml-2 text-[10px] tracking-wide text-ink-400">OBS · Scene</span>
                </div>
              </div>
              <div className="relative aspect-video bg-ink-950">
                <div className="absolute inset-0 bg-gradient-to-br from-ink-700 via-ink-850 to-ink-950" />
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_35%,rgba(92,112,212,0.35),transparent_55%)]" />
                {/* Fake gameplay / content blocks */}
                <div className="absolute inset-x-4 top-5 h-2/5 rounded-lg border border-white/10 bg-ink-800/80" />
                <div className="absolute right-3 bottom-3 h-10 w-14 rounded-md border border-white/15 bg-ink-700/90 shadow-lg" />
                <span className="absolute top-2.5 left-2.5 inline-flex items-center gap-1.5 rounded-md bg-danger-500 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white shadow-md">
                  <span className="animate-live-dot size-1.5 rounded-full bg-white" />
                  LIVE
                </span>
                <div className="absolute inset-x-3 bottom-2.5 flex h-5 items-end gap-0.5 pr-16">
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
            </div>
            <p className="mt-3 text-center text-xs font-medium tracking-wide text-ink-400">
              Live 16:9
            </p>
          </div>
        </div>

        {/* Connector */}
        <div
          aria-hidden
          className="absolute top-[42%] left-1/2 z-[2] flex size-11 -translate-x-1/2 items-center justify-center rounded-2xl border border-white/15 bg-ink-850 text-brand-300 shadow-xl shadow-brand-500/30"
          style={{ transform: "translateX(-50%) rotateX(8deg) translateZ(50px)" }}
        >
          <svg viewBox="0 0 24 24" className="size-5">
            <path
              fill="currentColor"
              d="M13.2 5.3 19.9 12l-6.7 6.7-1.4-1.4 4.3-4.3H4v-2h12.1l-4.3-4.3z"
            />
          </svg>
        </div>

        {/* Output: 9:16 phone */}
        <div
          className="absolute top-[8%] right-[2%] z-[3] w-[38%] max-w-[168px] sm:right-[4%]"
          style={{ transform: "rotateX(8deg) rotateY(16deg) translateZ(70px)", transformStyle: "preserve-3d" }}
        >
          <div className="animate-float" style={{ animationDuration: "5.4s", animationDelay: "0.5s" }}>
            <div className="depth-panel relative overflow-hidden rounded-[1.85rem] p-[3px]">
              <div className="relative overflow-hidden rounded-[1.65rem] bg-ink-950">
                {/* Notch */}
                <div className="absolute top-2 left-1/2 z-10 h-1.5 w-12 -translate-x-1/2 rounded-full bg-black/70" />
                <div className="relative aspect-[9/16]">
                  <div className="absolute inset-0 bg-gradient-to-b from-brand-600 via-ink-850 to-brand-700" />
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_26%,rgba(255,255,255,0.16),transparent_42%)]" />
                  <div className="absolute inset-x-0 top-[16%] mx-auto size-14 rounded-full border border-white/25 bg-white/10 shadow-inner sm:size-16" />
                  <div className="absolute inset-x-3 bottom-[22%] space-y-1.5 text-center">
                    <span className="inline-block rounded-md bg-black/75 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white sm:text-[11px]">
                      ATTENDS, REGARDE
                    </span>
                    <span className="inline-block rounded-md bg-brand-400 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white shadow-md shadow-brand-500/50 sm:text-[11px]">
                      CE MOMENT !
                    </span>
                  </div>
                  <div className="absolute inset-x-3 bottom-3 h-1 overflow-hidden rounded-full bg-white/20">
                    <div className="h-full w-2/3 rounded-full bg-white" />
                  </div>
                  <span className="absolute top-3 right-2.5 rounded-md bg-black/55 px-1.5 py-0.5 font-mono text-[10px] text-white">
                    0:52
                  </span>
                </div>
              </div>
            </div>
            <p className="mt-3 text-center text-xs font-medium tracking-wide text-ink-400">
              Clip 9:16
            </p>
          </div>
        </div>
      </div>

      <figcaption className="mt-1 text-center text-xs text-ink-500">
        Illustration schématique du principe.
      </figcaption>
    </figure>
  );
}
