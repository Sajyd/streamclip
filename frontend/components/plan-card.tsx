import type { ReactNode } from "react";

import { Badge } from "@/components/ui/primitives";
import { cx, formatHours, formatPrice } from "@/lib/format";
import type { Plan } from "@/types/api";

function planFeatures(plan: Plan): string[] {
  const features = [`${formatHours(plan.included_seconds)} de live analysées par mois`];
  features.push(
    plan.max_clips_per_session === null
      ? "Clips illimités par live"
      : `${plan.max_clips_per_session} clips maximum par live`,
  );
  features.push(
    plan.max_concurrent_streams > 1
      ? `${plan.max_concurrent_streams} lives simultanés`
      : "1 live à la fois",
  );
  if (plan.clip_retention_days !== null) {
    features.push(`Clips conservés ${plan.clip_retention_days} jours`);
  }
  return [...features, ...plan.features];
}

type PlanCardProps = {
  plan: Plan;
  highlighted?: boolean;
  current?: boolean;
  /** Call to action rendered at the bottom of the card. */
  action?: ReactNode;
};

export function PlanCard({ plan, highlighted = false, current = false, action }: PlanCardProps) {
  return (
    <article
      className={cx(
        "relative flex flex-col rounded-3xl border p-6 transition-all",
        highlighted
          ? "border-brand-400/45 bg-gradient-to-b from-brand-500/20 via-ink-900/85 to-ink-950 shadow-[0_24px_50px_-24px_rgba(37,99,235,0.55),inset_0_1px_0_rgba(255,255,255,0.1)]"
          : "border-white/10 bg-ink-950/55 shadow-[0_18px_40px_-28px_rgba(0,0,0,0.9),inset_0_1px_0_rgba(255,255,255,0.05)] hover:border-white/18 hover:bg-ink-900/70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold tracking-tight text-white">{plan.name}</h3>
        {current ? <Badge tone="ok">Offre actuelle</Badge> : null}
        {!current && highlighted ? <Badge tone="brand">Le plus choisi</Badge> : null}
      </div>
      <p className="mt-2 min-h-10 text-sm leading-relaxed text-ink-300">{plan.description}</p>
      <p className="mt-5 flex items-baseline gap-1.5">
        <span className="text-4xl font-semibold tracking-tight text-white">
          {formatPrice(plan.price_cents, plan.currency)}
        </span>
        <span className="text-sm text-ink-400">
          {plan.price_cents === 0 ? "pour toujours" : "TTC / mois"}
        </span>
      </p>
      <ul className="mt-6 flex-1 space-y-2.5 text-sm text-ink-200">
        {planFeatures(plan).map((feature) => (
          <li key={feature} className="flex gap-2.5">
            <svg viewBox="0 0 20 20" aria-hidden className="mt-0.5 size-4 shrink-0 text-brand-400">
              <path
                fill="currentColor"
                d="M8.1 13.3 4.9 10l-1.2 1.2 4.4 4.4 8.4-8.4-1.2-1.2z"
              />
            </svg>
            <span>{feature}</span>
          </li>
        ))}
      </ul>
      {action ? <div className="mt-6">{action}</div> : null}
    </article>
  );
}

export function PlanGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">{children}</div>;
}
