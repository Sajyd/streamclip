"use client";

import { motion, useReducedMotion } from "framer-motion";

const EASE = [0.22, 1, 0.36, 1] as const;

function ObsGlyph() {
  return (
    <svg viewBox="0 0 72 56" className="h-9 w-12" aria-hidden>
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
    <svg viewBox="0 0 72 72" className="size-11" aria-hidden>
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
    <svg viewBox="0 0 44 72" className="h-11 w-7" aria-hidden>
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
    <svg viewBox="0 0 88 56" className="h-8 w-14" aria-hidden>
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
    label: "Vous diffusez",
    sub: "Comme d’habitude sur Twitch, YouTube ou Kick",
    detail:
      "Ajoutez STREAMCLIP comme destination en plus dans OBS ou Streamlabs : votre live principal continue normalement, on reçoit juste une copie.",
    Glyph: ObsGlyph,
  },
  {
    id: "streamclip",
    label: "STREAMCLIP analyse",
    sub: "Les meilleurs moments sont repérés en continu",
    detail:
      "Pendant le live, on repère automatiquement les passages qui valent le coup — rires, actions, punches — sans que vous ayez à tout revoir après.",
    Glyph: StreamclipGlyph,
  },
  {
    id: "clips",
    label: "Des clips prêts",
    sub: "Courts, verticaux et sous-titrés",
    detail:
      "Chaque moment fort devient un clip mobile déjà découpé, recadré et sous-titré, prêt pour Shorts, TikTok et Reels.",
    Glyph: ClipGlyph,
  },
  {
    id: "social",
    label: "Vous publiez",
    sub: "En un clic, ou automatiquement",
    detail:
      "Publiez directement sur YouTube, TikTok et Instagram, ou téléchargez les clips pour le faire vous-même.",
    Glyph: SocialGlyph,
  },
] as const;

export function ConceptFlow() {
  const reduceMotion = useReducedMotion();
  const animate = !reduceMotion;

  return (
    <div id="fonctionnement" className="relative scroll-mt-20">
      <div className="mx-auto max-w-2xl text-center">
        <p className="text-xs font-medium tracking-[0.22em] text-brand-300 uppercase">
          Fonctionnement
        </p>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          Du direct au clip, sans montage
        </h2>
        <p className="mt-4 text-base leading-relaxed text-ink-300">
          STREAMCLIP regarde votre live à votre place et en sort les meilleurs moments en clips
          prêts à poster — vous n’avez qu’à brancher une destination en plus dans OBS.
        </p>
      </div>

      <div className="relative mx-auto mt-10 max-w-3xl overflow-hidden rounded-[2rem] border border-white/10 bg-ink-950/80 sm:mt-12">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,rgba(0,19,222,0.28),transparent_55%),radial-gradient(ellipse_at_80%_70%,rgba(51,88,255,0.16),transparent_50%)]"
        />

        <ol className="relative flex flex-col px-6 py-10 sm:px-10 sm:py-12">
          {STAGES.map((stage, index) => {
            const Glyph = stage.Glyph;
            const last = index === STAGES.length - 1;
            return (
              <li key={stage.id} className="relative flex gap-5 sm:gap-6">
                <div className="flex w-14 shrink-0 flex-col items-center sm:w-16">
                  <motion.div
                    className="relative z-10 flex size-14 items-center justify-center rounded-2xl border border-white/10 bg-ink-900/80 sm:size-16"
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
                      style={{ originY: 0, minHeight: "3.25rem" }}
                      transition={{ duration: 0.9, delay: 0.35 + index * 0.45, ease: EASE }}
                    />
                  ) : null}
                </div>
                <motion.div
                  className={`min-w-0 flex-1 pt-2.5 ${last ? "pb-2" : "pb-10 sm:pb-12"}`}
                  initial={animate ? { opacity: 0, x: 16 } : false}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true, amount: 0.5 }}
                  transition={{ duration: 0.85, delay: 0.15 + index * 0.45, ease: EASE }}
                >
                  <p className="font-mono text-[0.65rem] tracking-[0.18em] text-brand-300/80">
                    {String(index + 1).padStart(2, "0")}
                  </p>
                  <p className="mt-1 text-lg font-semibold text-white sm:text-xl">{stage.label}</p>
                  <p className="mt-1 text-sm text-ink-300 sm:text-base">{stage.sub}</p>
                  <p className="mt-2 text-sm leading-relaxed text-ink-400">{stage.detail}</p>
                </motion.div>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
