import Link from "next/link";

import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { deltaLabel } from "@/lib/admin";
import { cx, formatDateTime, formatPrice } from "@/lib/format";
import type { AdminAnalytics, AdminAnalyticsPeriod } from "@/types/api";

const PERIODS: { value: AdminAnalyticsPeriod; label: string }[] = [
  { value: "day", label: "Jour" },
  { value: "week", label: "Semaine" },
  { value: "month", label: "Mois" },
  { value: "year", label: "Année" },
];

function Delta({ current, previous }: { current: number; previous: number }) {
  const delta = deltaLabel(current, previous);
  return (
    <p
      className={cx(
        "mt-2 text-xs",
        delta.tone === "ok" && "text-ok-400",
        delta.tone === "danger" && "text-danger-400",
        delta.tone === "neutral" && "text-ink-400",
      )}
    >
      {delta.text}
    </p>
  );
}

function SeriesChart({
  series,
  field,
  label,
  timeZone,
}: {
  series: AdminAnalytics["series"];
  field: "users_new" | "clips_created" | "lives_started" | "exports_created" | "clip_downloads";
  label: string;
  timeZone: string;
}) {
  const values = series.map((bucket) => bucket[field]);
  const max = Math.max(...values, 1);
  return (
    <Card className="p-5">
      <CardTitle>{label}</CardTitle>
      <CardDescription className="mt-1">
        {series.length} points · max {max}
      </CardDescription>
      <div className="mt-4 flex h-36 items-end gap-1">
        {series.map((bucket) => {
          const value = bucket[field];
          const height = Math.max(4, Math.round((value / max) * 100));
          return (
            <div
              key={`${field}-${bucket.bucket_start}`}
              className="group relative flex min-w-0 flex-1 flex-col items-center justify-end"
              title={`${formatDateTime(bucket.bucket_start, timeZone)} : ${value}`}
            >
              <div
                className="w-full rounded-t-md bg-brand-500/70 transition-colors group-hover:bg-brand-400"
                style={{ height: `${height}%` }}
              />
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function AdminPeriodSwitcher({
  period,
  basePath = "/admin",
}: {
  period: AdminAnalyticsPeriod;
  basePath?: string;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-xl border border-ink-700 bg-ink-900/60 p-1">
      {PERIODS.map((item) => {
        const active = item.value === period;
        return (
          <Link
            key={item.value}
            href={`${basePath}?period=${item.value}`}
            aria-current={active ? "page" : undefined}
            className={cx(
              "rounded-lg px-3 py-1.5 text-sm transition-colors",
              active ? "bg-white/10 text-white" : "text-ink-300 hover:text-white",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}

export function AdminAnalyticsPanel({
  data,
  timeZone,
}: {
  data: AdminAnalytics;
  timeZone: string;
}) {
  const { totals, plans, series, currency } = data;
  return (
    <div className="space-y-6">
      <p className="text-xs text-ink-400">
        Période du {formatDateTime(data.range_start, timeZone)} au{" "}
        {formatDateTime(data.range_end, timeZone)} · comparé à la fenêtre précédente
      </p>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">MRR</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {formatPrice(totals.mrr_cents, currency)}
          </p>
          <p className="mt-1 text-xs text-ink-400">
            {totals.paying_subscribers} abonnés payants
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Utilisateurs
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.users_total}
          </p>
          <p className="mt-1 text-xs text-ink-400">+{totals.users_new} sur la période</p>
          <Delta current={totals.users_new} previous={totals.users_new_previous} />
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Lives actifs
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.lives_active}
          </p>
          <p className="mt-1 text-xs text-ink-400">
            {totals.lives_started} démarrés sur la période
          </p>
          <Delta current={totals.lives_started} previous={totals.lives_started_previous} />
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">Clips</p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.clips_total}
          </p>
          <p className="mt-1 text-xs text-ink-400">+{totals.clips_created} sur la période</p>
          <Delta current={totals.clips_created} previous={totals.clips_created_previous} />
        </Card>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Nouveaux abonnements
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.subscriptions_new}
          </p>
          <Delta
            current={totals.subscriptions_new}
            previous={totals.subscriptions_new_previous}
          />
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Exports données
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.exports_created}
          </p>
          <Delta current={totals.exports_created} previous={totals.exports_created_previous} />
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Téléchargements clips
          </p>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-white">
            {totals.clip_downloads}
          </p>
          <Delta current={totals.clip_downloads} previous={totals.clip_downloads_previous} />
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Répartition MRR
          </p>
          <ul className="mt-3 space-y-2">
            {plans.length === 0 ? (
              <li className="text-sm text-ink-400">Aucun abonnement payant.</li>
            ) : (
              plans.map((plan) => (
                <li key={plan.plan_code} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-ink-200">
                    {plan.plan_name}{" "}
                    <span className="text-ink-500">×{plan.subscribers}</span>
                  </span>
                  <span className="text-white">{formatPrice(plan.mrr_cents, plan.currency)}</span>
                </li>
              ))
            )}
          </ul>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <SeriesChart series={series} field="users_new" label="Inscriptions" timeZone={timeZone} />
        <SeriesChart series={series} field="clips_created" label="Clips créés" timeZone={timeZone} />
        <SeriesChart
          series={series}
          field="lives_started"
          label="Lives démarrés"
          timeZone={timeZone}
        />
        <SeriesChart
          series={series}
          field="clip_downloads"
          label="Téléchargements clips"
          timeZone={timeZone}
        />
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "active" || status === "live" || status === "ready" || status === "available"
      ? ("ok" as const)
      : status === "suspended" || status === "failed" || status === "past_due"
        ? ("danger" as const)
        : status === "trialing" || status === "pending" || status === "rendering"
          ? ("warn" as const)
          : ("neutral" as const);
  return <Badge tone={tone}>{status}</Badge>;
}
