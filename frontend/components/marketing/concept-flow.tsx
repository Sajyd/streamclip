"use client";

import { motion } from "framer-motion";

const NODES = [
  { id: "obs", label: "OBS / Streamlabs", sub: "Votre live habituel" },
  { id: "streamclip", label: "STREAMCLIP", sub: "Analyse en continu" },
  { id: "clips", label: "Clips 9:16", sub: "Moments forts prêts" },
  { id: "social", label: "TikTok · YouTube · Instagram", sub: "Publication auto" },
] as const;

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.18, delayChildren: 0.1 },
  },
};

const item = {
  hidden: { opacity: 0, y: 18, scale: 0.96 },
  show: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: "spring" as const, stiffness: 320, damping: 24 },
  },
};

export function ConceptFlow() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-ink-950/70 p-6 sm:p-8">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(0,19,222,0.22),transparent_55%)]"
      />
      <motion.ol
        className="relative grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, amount: 0.35 }}
      >
        {NODES.map((node, index) => (
          <motion.li key={node.id} variants={item} className="relative">
            <div className="surface h-full p-5">
              <div className="flex items-center gap-3">
                <span className="flex size-9 items-center justify-center rounded-xl bg-brand-500/20 font-mono text-sm font-semibold text-brand-200">
                  {String(index + 1).padStart(2, "0")}
                </span>
                {index < NODES.length - 1 ? (
                  <motion.span
                    aria-hidden
                    className="hidden h-px flex-1 bg-gradient-to-r from-brand-400/70 to-transparent lg:block"
                    initial={{ scaleX: 0, originX: 0 }}
                    whileInView={{ scaleX: 1 }}
                    transition={{ delay: 0.35 + index * 0.15, duration: 0.55 }}
                    viewport={{ once: true }}
                  />
                ) : null}
              </div>
              <p className="mt-4 text-base font-semibold text-white">{node.label}</p>
              <p className="mt-1 text-sm text-ink-300">{node.sub}</p>
            </div>
            {index < NODES.length - 1 ? (
              <motion.div
                aria-hidden
                className="absolute -right-3 top-1/2 z-10 hidden size-6 -translate-y-1/2 items-center justify-center rounded-full border border-brand-400/40 bg-ink-950 text-brand-300 lg:flex"
                animate={{ x: [0, 4, 0], opacity: [0.55, 1, 0.55] }}
                transition={{ repeat: Infinity, duration: 1.8, delay: index * 0.2 }}
              >
                →
              </motion.div>
            ) : null}
          </motion.li>
        ))}
      </motion.ol>

      <motion.div
        className="relative mt-8 grid gap-3 sm:grid-cols-3"
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ delay: 0.5 }}
      >
        {[
          "Une URL RTMP + votre clé secrète",
          "Moments viraux détectés toutes les 5 min",
          "Publication sur vos réseaux connectés",
        ].map((line) => (
          <p
            key={line}
            className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-ink-200"
          >
            {line}
          </p>
        ))}
      </motion.div>
    </div>
  );
}
