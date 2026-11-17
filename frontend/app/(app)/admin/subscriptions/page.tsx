import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { StatusBadge } from "@/components/app/admin-analytics";
import { AdminShell } from "@/components/app/admin-shell";
import { buttonClasses } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/primitives";
import { adminFetch, one, requireStaff } from "@/lib/admin";
import { formatDateTime, formatPrice } from "@/lib/format";
import type { AdminSubscriptionList } from "@/types/api";

export const metadata: Metadata = {
  title: "Administration — abonnements",
  robots: { index: false },
};

const PATH = "/admin/subscriptions";

type SearchParams = PageProps<"/admin/subscriptions">["searchParams"];

async function Subscriptions({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireStaff(PATH);
  const query = await searchParams;
  const search = one(query.q).trim().slice(0, 100);
  const cursor = one(query.cursor);
  const params = new URLSearchParams({ limit: "50" });
  if (search) params.set("search", search);
  if (/^[0-9a-f-]{36}$/i.test(cursor)) params.set("cursor", cursor);

  const data = await adminFetch<AdminSubscriptionList>(
    `/admin/subscriptions?${params}`,
    token,
    PATH,
  );
  const { items, next_cursor: nextCursor, summary } = data;
  const timeZone = me.user.timezone;
  const nextParams = new URLSearchParams();
  if (search) nextParams.set("q", search);
  if (nextCursor) nextParams.set("cursor", nextCursor);

  return (
    <AdminShell
      title="Abonnements & MRR"
      description="Revenus récurrents mensuels et détail des abonnements actifs par organisation."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">MRR</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {formatPrice(summary.mrr_cents, summary.currency)}
          </p>
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">
            Payants
          </p>
          <p className="mt-2 text-2xl font-semibold text-white">{summary.paying_subscribers}</p>
        </Card>
        <Card className="p-5">
          <p className="text-xs font-medium tracking-[0.14em] text-ink-400 uppercase">Free</p>
          <p className="mt-2 text-2xl font-semibold text-white">{summary.free_subscribers}</p>
        </Card>
      </div>

      {summary.plans.length > 0 ? (
        <Card className="p-5">
          <p className="text-sm font-medium text-white">Répartition par offre</p>
          <ul className="mt-3 divide-y divide-ink-700">
            {summary.plans.map((plan) => (
              <li
                key={plan.plan_code}
                className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
              >
                <span className="text-ink-200">
                  {plan.plan_name} · {formatPrice(plan.price_cents, plan.currency)}/mois ·{" "}
                  {plan.subscribers} abonné{plan.subscribers > 1 ? "s" : ""}
                </span>
                <span className="text-white">{formatPrice(plan.mrr_cents, plan.currency)}</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <form action={PATH} className="flex max-w-md gap-2">
        <label htmlFor="q" className="sr-only">
          Rechercher par e-mail propriétaire
        </label>
        <input
          id="q"
          name="q"
          type="search"
          defaultValue={search}
          maxLength={100}
          placeholder="E-mail du propriétaire"
          className="block w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500"
        />
        <button type="submit" className={buttonClasses({ variant: "secondary", size: "sm" })}>
          Rechercher
        </button>
      </form>

      {items.length === 0 ? (
        <Card>
          <p className="text-sm text-ink-300">Aucun abonnement ne correspond.</p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <Card className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-white">
                    {item.owner_email ?? item.organization_name}
                  </p>
                  <StatusBadge status={item.status} />
                  {item.is_paid ? (
                    <StatusBadge status="active" />
                  ) : (
                    <span className="text-xs text-ink-400">Free</span>
                  )}
                  {item.payment_failed ? <StatusBadge status="failed" /> : null}
                  {item.cancel_at_period_end ? (
                    <span className="text-xs text-warn-400">Résiliation en fin de période</span>
                  ) : null}
                </div>
                <p className="mt-1.5 text-xs text-ink-400">
                  {item.plan_name} · {formatPrice(item.price_cents, item.currency)}/mois · période{" "}
                  {formatDateTime(item.current_period_start, timeZone)} →{" "}
                  {formatDateTime(item.current_period_end, timeZone)} · espace{" "}
                  {item.organization_name}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {nextCursor ? (
        <Link href={`${PATH}?${nextParams}`} className={buttonClasses({ variant: "secondary", size: "sm" })}>
          Suivants
        </Link>
      ) : null}
    </AdminShell>
  );
}

export default function AdminSubscriptionsPage({
  searchParams,
}: PageProps<"/admin/subscriptions">) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement des abonnements">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-24" />
        </div>
      }
    >
      <Subscriptions searchParams={searchParams} />
    </Suspense>
  );
}
