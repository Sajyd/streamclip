import type { Metadata } from "next";
import { Suspense } from "react";

import { AdminAnalyticsPanel, AdminPeriodSwitcher } from "@/components/app/admin-analytics";
import { AdminShell } from "@/components/app/admin-shell";
import { Skeleton } from "@/components/ui/primitives";
import { adminFetch, one, requireStaff } from "@/lib/admin";
import type { AdminAnalytics, AdminAnalyticsPeriod } from "@/types/api";

export const metadata: Metadata = {
  title: "Administration",
  robots: { index: false },
};

const PATH = "/admin";
const PERIODS = new Set<AdminAnalyticsPeriod>(["day", "week", "month", "year"]);

type SearchParams = PageProps<"/admin">["searchParams"];

async function Overview({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireStaff(PATH);
  const query = await searchParams;
  const raw = one(query.period);
  const period: AdminAnalyticsPeriod = PERIODS.has(raw as AdminAnalyticsPeriod)
    ? (raw as AdminAnalyticsPeriod)
    : "week";
  const data = await adminFetch<AdminAnalytics>(`/admin/analytics?period=${period}`, token, PATH);

  return (
    <AdminShell
      title="Vue d'ensemble"
      description="Indicateurs plateforme : utilisateurs, MRR, lives, clips et exports — filtrables par jour, semaine, mois ou année."
      actions={<AdminPeriodSwitcher period={period} />}
    >
      <AdminAnalyticsPanel data={data} timeZone={me.user.timezone} />
    </AdminShell>
  );
}

export default function AdminOverviewPage({ searchParams }: PageProps<"/admin">) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement de l'administration">
          <Skeleton className="h-10 w-56" />
          <Skeleton className="h-32" />
          <Skeleton className="h-48" />
        </div>
      }
    >
      <Overview searchParams={searchParams} />
    </Suspense>
  );
}
