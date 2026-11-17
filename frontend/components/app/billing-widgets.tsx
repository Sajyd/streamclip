import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { cx, formatDate, formatDuration, formatHours, formatPrice } from "@/lib/format";
import type { BillingOverview } from "@/types/api";

const STATUS_LABELS: Record<string, { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  active: { label: "Actif", tone: "ok" },
  trialing: { label: "Période d'essai", tone: "ok" },
  past_due: { label: "Paiement en retard", tone: "warn" },
  unpaid: { label: "Impayé", tone: "danger" },
  canceled: { label: "Résilié", tone: "neutral" },
  incomplete: { label: "Paiement à finaliser", tone: "warn" },
  incomplete_expired: { label: "Paiement expiré", tone: "neutral" },
  paused: { label: "En pause", tone: "neutral" },
};

export function subscriptionStatus(overview: BillingOverview) {
  if (!overview.is_paid) {
    return { label: "Offre gratuite", tone: "neutral" as const };
  }
  return STATUS_LABELS[overview.status] ?? { label: overview.status, tone: "neutral" as const };
}

export function PlanSummary({ overview, timeZone }: { overview: BillingOverview; timeZone: string }) {
  const status = subscriptionStatus(overview);
  return (
    <Card className="h-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Offre</p>
          <CardTitle className="mt-2 text-lg">{overview.plan.name}</CardTitle>
          <CardDescription>{overview.plan.description}</CardDescription>
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      <p className="mt-6 text-3xl font-semibold tracking-tight text-white">
        {formatPrice(overview.plan.price_cents, overview.plan.currency)}
        <span className="ml-1.5 text-sm font-normal text-ink-400">
          {overview.is_paid ? "TTC / mois" : "sans engagement"}
        </span>
      </p>
      <p className="mt-3 text-sm leading-relaxed text-ink-300">
        {overview.is_paid
          ? overview.cancel_at_period_end
            ? `Résiliation programmée : votre offre reste active jusqu'au ${formatDate(overview.current_period_end, timeZone)}.`
            : `Prochain renouvellement le ${formatDate(overview.current_period_end, timeZone)}.`
          : `Votre quota se renouvelle le ${formatDate(overview.current_period_end, timeZone)}.`}
      </p>
    </Card>
  );
}

export function QuotaSummary({ overview, timeZone }: { overview: BillingOverview; timeZone: string }) {
  const { quota } = overview;
  const percent = Math.min(100, Math.round(quota.used_ratio * 100));
  const tone = quota.exhausted ? "bg-danger-500" : quota.warning ? "bg-warn-400" : "bg-brand-500";
  return (
    <Card className="h-full">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Consommation</p>
          <CardTitle className="mt-2 text-lg">Ce mois-ci</CardTitle>
          <CardDescription>
            Période en cours jusqu&apos;au {formatDate(overview.current_period_end, timeZone)}.
          </CardDescription>
        </div>
        {quota.exhausted ? (
          <Badge tone="danger">Quota atteint</Badge>
        ) : quota.warning ? (
          <Badge tone="warn">Bientôt atteint</Badge>
        ) : null}
      </div>
      <p className="mt-6 text-3xl font-semibold tracking-tight text-white">
        {formatDuration(quota.consumed_seconds)}
        <span className="ml-1.5 text-sm font-normal text-ink-400">
          sur {formatHours(quota.included_seconds)}
        </span>
      </p>
      <div
        role="progressbar"
        aria-label="Part du quota mensuel consommée"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="mt-5 h-2 overflow-hidden rounded-full bg-ink-800"
      >
        <div
          className={cx("h-full rounded-full transition-all duration-500", tone)}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink-300">
        {quota.exhausted
          ? "Le traitement est suspendu jusqu'à la prochaine période. Une offre supérieure le rétablit immédiatement."
          : `Il vous reste ${formatDuration(quota.remaining_seconds)} de traitement.`}
      </p>
    </Card>
  );
}
