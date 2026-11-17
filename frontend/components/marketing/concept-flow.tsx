"use client";

import { motion, useReducedMotion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

function ObsGlyph() {
  return (
    <svg viewBox="0 0 72 56" className="h-14 w-[4.5rem]" aria-hidden>
      <rect x="2" y="2" width="68" height="42" rx="6" fill="#030025" stroke="rgba(107,130,255,0.55)" strokeWidth="1.5" />
      <rect x="8" y="8" width="40" height="24" rx="3" fill="#0013de" opacity="0.35" />
      <circle cx="18" cy="18" r="5" fill="#6b82ff" opacity="0.9" />
      <rect x="28" y="14" width="14" height="3" rx="1" fill="rgba(208,214,240,0.55)" />
      <rect x="28" y="20" width="10" height="3" rx="1" fill="rgba(208,214,240,0.35)" />
      <rect x="52" y="10" width="12" height="8" rx="2" fill="rgba(0,19,222,0.45)" />
      <rect x="52" y="22" width="12" height="8" rx="2" fill="rgba(0,19,222,0.25)" />
      <rect x="24" y="48" width="24" height="3" rx="1.5" fill="rgba(107,130,255,0.4)" />
      <rect x="32" y="44" width="8" height="5" rx="1" fill="rgba(107,130,255,0.35)" />
    </svg>
  );
}

function StreamclipGlyph({ pulse = false }: { pulse?: boolean } = {}) {
  return (
    <svg viewBox="0 0 72 72" className="size-16" aria-hidden>
      <circle cx="36" cy="36" r="30" fill="#0013de" opacity="0.18" />
      <circle cx="36" cy="36" r="22" fill="none" stroke="rgba(107,130,255,0.55)" strokeWidth="1.5" />
      <motion.circle
        cx="36"
        cy="36"
        r="14"
        fill="#0021f3"
        initial={false}
        animate={pulse ? { opacity: [0.65, 1, 0.65] } : { opacity: 0.85 }}
        transition={pulse ? { duration: 3.2, repeat: Infinity, ease: "easeInOut" } : undefined}
      />
      <path
        d="M28 38 L34 28 L40 36 L46 24"
        fill="none"
        stroke="#eef0fa"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {[0, 60, 120, 180, 240, 300].map((deg) => {
        const rad = (deg * Math.PI) / 180;
        const x = 36 + Math.cos(rad) * 26;
        const y = 36 + Math.sin(rad) * 26;
        return <circle key={deg} cx={x} cy={y} r="1.6" fill="#6b82ff" opacity="0.7" />;
      })}
    </svg>
  );
}

function ClipGlyph() {
  return (
    <svg viewBox="0 0 44 72" className="h-16 w-10" aria-hidden>
      <rect x="2" y="2" width="40" height="68" rx="8" fill="#030025" stroke="rgba(107,130,255,0.55)" strokeWidth="1.5" />
      <rect x="7" y="10" width="30" height="44" rx="3" fill="#0013de" opacity="0.4" />
      <rect x="10" y="42" width="24" height="3" rx="1" fill="rgba(238,240,250,0.85)" />
      <rect x="10" y="48" width="16" height="2.5" rx="1" fill="rgba(238,240,250,0.45)" />
      <circle cx="22" cy="64" r="2.5" fill="rgba(107,130,255,0.55)" />
      <polygon points="18,26 18,38 28,32" fill="#eef0fa" opacity="0.9" />
    </svg>
  );
}

function SocialGlyph() {
  return (
    <svg viewBox="0 0 88 56" className="h-12 w-[5.5rem]" aria-hidden>
      <rect x="2" y="10" width="24" height="36" rx="6" fill="#0013de" opacity="0.55" />
      <rect x="32" y="4" width="24" height="48" rx="6" fill="#0021f3" opacity="0.7" />
      <rect x="62" y="10" width="24" height="36" rx="6" fill="#3358ff" opacity="0.5" />
      <circle cx="14" cy="22" r="4" fill="#eef0fa" opacity="0.35" />
      <circle cx="44" cy="18" r="4" fill="#eef0fa" opacity="0.45" />
      <circle cx="74" cy="22" r="4" fill="#eef0fa" opacity="0.35" />
      <rect x="8" y="34" width="12" height="2" rx="1" fill="rgba(238,240,250,0.4)" />
      <rect x="38" y="38" width="12" height="2" rx="1" fill="rgba(238,240,250,0.5)" />
      <rect x="68" y="34" width="12" height="2" rx="1" fill="rgba(238,240,250,0.4)" />
    </svg>
  );
}

const STAGES = [
  {
    id: "obs",
    label: "OBS / Streamlabs",
    sub: "Votre live, inchangé",
    Glyph: ObsGlyph,
  },
  {
    id: "streamclip",
    label: "STREAMCLIP",
    sub: "Analyse toutes les 5 min",
    Glyph: StreamclipGlyph,
  },
  {
    id: "clips",
    label: "Clips 9:16",
    sub: "Moments forts prêts",
    Glyph: ClipGlyph,
  },
  {
    id: "social",
    label: "Vos réseaux",
    sub: "Publication auto",
    Glyph: SocialGlyph,
  },
] as const;

/** Desktop path through the four stages (viewBox 1000×280). */
const FLOW_PATH =
  "M 80 140 C 180 140, 220 140, 280 140 S 420 60, 500 140 S 620 220, 720 140 S 820 140, 920 140";

export function ConceptFlow() {
  const reduceMotion = useReducedMotion();
  const animate = !reduceMotion;

  return (
    <div className="relative">
      <div className="mx-auto max-w-2xl text-center">
        <p className="text-xs font-medium tracking-[0.22em] text-brand-300 uppercase">Le concept</p>
        <h2 className="mt-3 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
          Une URL RTMP, des clips qui s&apos;enchaînent
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-300 sm:text-base">
          Vous diffusez comme d&apos;habitude. STREAMCLIP reçoit une copie du flux, détecte les
          moments forts et prépare des verticales prêtes à publier.
        </p>
      </div>

      <div className="relative mt-10 min-h-[28rem] overflow-hidden rounded-[2rem] border border-white/10 bg-ink-950/80 sm:mt-12 sm:min-h-[32rem] lg:min-h-[36rem]">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,rgba(0,19,222,0.28),transparent_55%),radial-gradient(ellipse_at_80%_70%,rgba(51,88,255,0.16),transparent_50%)]"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(107,130,255,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(107,130,255,0.08) 1px, transparent 1px)",
            backgroundSize: "48px 48px",
            maskImage: "radial-gradient(ellipse at center, black 35%, transparent 80%)",
          }}
        />

        {/* Desktop schematic */}
        <div className="relative hidden h-full min-h-[36rem] lg:block">
          <svg
            className="absolute inset-0 size-full"
            viewBox="0 0 1000 280"
            preserveAspectRatio="xMidYMid meet"
            aria-hidden
          >
            <defs>
              <linearGradient id="concept-flow-stroke" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#6b82ff" stopOpacity="0.15" />
                <stop offset="50%" stopColor="#0021f3" stopOpacity="0.85" />
                <stop offset="100%" stopColor="#9aabff" stopOpacity="0.35" />
              </linearGradient>
              <filter id="concept-glow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <motion.path
              d={FLOW_PATH}
              fill="none"
              stroke="url(#concept-flow-stroke)"
              strokeWidth="2.5"
              strokeLinecap="round"
              initial={animate ? { pathLength: 0, opacity: 0 } : { pathLength: 1, opacity: 1 }}
              whileInView={{ pathLength: 1, opacity: 1 }}
              viewport={{ once: true, amount: 0.4 }}
              transition={{ duration: 2.4, ease: EASE, delay: 0.35 }}
            />

            {animate
              ? [0, 1, 2].map((i) => (
                  <motion.circle
                    key={i}
                    r="5"
                    fill="#9aabff"
                    filter="url(#concept-glow)"
                    initial={{ opacity: 0 }}
                    whileInView={{ opacity: [0, 1, 1, 0] }}
                    viewport={{ once: true, amount: 0.4 }}
                    transition={{
                      duration: 5.5,
                      delay: 1.1 + i * 1.4,
                      ease: "linear",
                      times: [0, 0.08, 0.9, 1],
                    }}
                  >
                    <animateMotion
                      dur="5.5s"
                      begin={`${1.1 + i * 1.4}s`}
                      fill="freeze"
                      path={FLOW_PATH}
                    />
                  </motion.circle>
                ))
              : null}
          </svg>

          <ol className="absolute inset-0 grid grid-cols-4 px-6 py-16 xl:px-12">
            {STAGES.map((stage, index) => {
              const Glyph = stage.Glyph;
              const isCenter = stage.id === "streamclip";
              return (
                <motion.li
                  key={stage.id}
                  className="relative flex flex-col items-center justify-center text-center"
                  initial={animate ? { opacity: 0, y: 28 } : false}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.35 }}
                  transition={{ duration: 0.9, delay: 0.55 + index * 0.55, ease: EASE }}
                >
                  <div
                    className={
                      isCenter
                        ? "relative flex size-36 items-center justify-center rounded-full border border-brand-400/40 bg-brand-500/15 shadow-[0_0_48px_-12px_rgba(0,33,243,0.75)]"
                        : "relative flex size-32 items-center justify-center"
                    }
                  >
                    {!isCenter ? (
                      <span
                        aria-hidden
                        className="absolute inset-3 rounded-[1.75rem] border border-white/10 bg-ink-900/60"
                      />
                    ) : null}
                    <span className="relative z-10">
                      {stage.id === "streamclip" ? (
                        <StreamclipGlyph pulse={Boolean(animate)} />
                      ) : (
                        <Glyph />
                      )}
                    </span>
                    {animate && isCenter ? (
                      <motion.span
                        aria-hidden
                        className="pointer-events-none absolute inset-0 rounded-full border border-brand-300/40"
                        animate={{ scale: [1, 1.35], opacity: [0.55, 0] }}
                        transition={{ duration: 3.6, repeat: Infinity, ease: "easeOut" }}
                      />
                    ) : null}
                  </div>
                  <p className="mt-6 text-base font-semibold text-white">{stage.label}</p>
                  <p className="mt-1 max-w-[11rem] text-sm text-ink-300">{stage.sub}</p>
                  <span className="mt-3 font-mono text-[0.65rem] tracking-[0.18em] text-brand-300/80">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                </motion.li>
              );
            })}
          </ol>
        </div>

        {/* Mobile / tablet schematic */}
        <ol className="relative flex flex-col gap-0 px-6 py-10 sm:px-10 lg:hidden">
          {STAGES.map((stage, index) => {
            const Glyph = stage.Glyph;
            const last = index === STAGES.length - 1;
            return (
              <li key={stage.id} className="relative flex gap-5">
                <div className="flex w-16 shrink-0 flex-col items-center">
                  <motion.div
                    className="relative z-10 flex size-16 items-center justify-center rounded-2xl border border-white/10 bg-ink-900/80"
                    initial={animate ? { opacity: 0, scale: 0.9 } : false}
                    whileInView={{ opacity: 1, scale: 1 }}
                    viewport={{ once: true, amount: 0.5 }}
                    transition={{ duration: 0.8, delay: index * 0.45, ease: EASE }}
                  >
                    {stage.id === "streamclip" ? (
                      <StreamclipGlyph pulse={Boolean(animate)} />
                    ) : (
                      <Glyph />
                    )}
                  </motion.div>
                  {!last ? (
                    <motion.span
                      aria-hidden
                      className="my-1 w-px flex-1 bg-gradient-to-b from-brand-400/70 to-brand-400/10"
                      initial={animate ? { scaleY: 0 } : false}
                      whileInView={{ scaleY: 1 }}
                      viewport={{ once: true }}
                      style={{ originY: 0, minHeight: "3.5rem" }}
                      transition={{ duration: 0.9, delay: 0.35 + index * 0.45, ease: EASE }}
                    />
                  ) : null}
                </div>
                <motion.div
                  className="min-w-0 flex-1 pb-10 pt-3"
                  initial={animate ? { opacity: 0, x: 16 } : false}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, amount: 0.5 }}
                  transition={{ duration: 0.85, delay: 0.15 + index * 0.45, ease: EASE }}
                >
                  <p className="font-mono text-[0.65rem] tracking-[0.18em] text-brand-300/80">
                    {String(index + 1).padStart(2, "0")}
                  </p>
                  <p className="mt-1 text-lg font-semibold text-white">{stage.label}</p>
                  <p className="mt-1 text-sm text-ink-300">{stage.sub}</p>
                </motion.div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
