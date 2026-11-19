import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { stopLiveAction } from "@/app/actions/admin";
import { StatusBadge } from "@/components/app/admin-analytics";
import { AdminShell } from "@/components/app/admin-shell";
import { buttonClasses } from "@/components/ui/button";
import { Form, SubmitButton } from "@/components/ui/form";
import { Card, Skeleton } from "@/components/ui/primitives";
import { adminFetch, one, requireStaff } from "@/lib/admin";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AdminLiveList } from "@/types/api";

export const metadata: Metadata = {
  title: "Administration — lives",
  robots: { index: false },
};

const PATH = "/admin/lives";

type SearchParams = PageProps<"/admin/lives">["searchParams"];

async function Lives({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireStaff(PATH);
  const query = await searchParams;
  const search = one(query.q).trim().slice(0, 100);
  const cursor = one(query.cursor);
  const activeOnly = one(query.all) !== "1";
  const params = new URLSearchParams({
    limit: "50",
    active_only: activeOnly ? "true" : "false",
  });
  if (search) params.set("search", search);
  if (/^[0-9a-f-]{36}$/i.test(cursor)) params.set("cursor", cursor);

  const data = await adminFetch<AdminLiveList>(`/admin/lives?${params}`, token, PATH);
  const { items, next_cursor: nextCursor } = data;
  const timeZone = me.user.timezone;
  const nextParams = new URLSearchParams();
  if (search) nextParams.set("q", search);
  if (!activeOnly) nextParams.set("all", "1");
  if (nextCursor) nextParams.set("cursor", nextCursor);

  return (
    <AdminShell
      title="Lives"
      description="Sessions en cours et historique des lives sur la plateforme."
      actions={
        <Link
          href={activeOnly ? `${PATH}?all=1` : PATH}
          className={buttonClasses({ variant: "secondary", size: "sm" })}
        >
          {activeOnly ? "Voir tout l'historique" : "Lives en cours seulement"}
        </Link>
      }
    >
      <form action={PATH} className="flex max-w-md gap-2">
        {!activeOnly ? <input type="hidden" name="all" value="1" /> : null}
        <label htmlFor="q" className="sr-only">
          Rechercher par e-mail
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
          <p className="text-sm text-ink-300">
            {activeOnly ? "Aucun live en cours." : "Aucun live trouvé."}
          </p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <Card className="p-5 transition hover:border-ink-500">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <Link href={`/admin/lives/${item.id}`} className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 truncate text-sm font-medium text-white">
                      {item.title || "Live sans titre"}
                    </p>
                    <StatusBadge status={item.status} />
                    {item.protocol ? (
                      <span className="text-xs uppercase text-ink-400">{item.protocol}</span>
                    ) : null}
                  </div>
                  <p className="mt-1.5 text-xs text-ink-400">
                    {item.owner_email ?? "—"} · {item.organization_name} ·{" "}
                    {item.started_at
                      ? `démarré ${formatDateTime(item.started_at, timeZone)}`
                      : `créé ${formatDateTime(item.created_at, timeZone)}`}
                    {item.ended_at ? ` · terminé ${formatDateTime(item.ended_at, timeZone)}` : ""} ·{" "}
                    {formatDuration(Math.floor(item.processed_ms / 1000))} traités ·{" "}
                    {item.clips_count} clip{item.clips_count > 1 ? "s" : ""}
                  </p>
                  </Link>
                  {activeOnly ? (
                    <Form action={stopLiveAction} className="space-y-0">
                      <input type="hidden" name="live_id" value={item.id} />
                      <SubmitButton variant="danger" size="sm" pendingLabel="Arrêt…">
                        Arrêter
                      </SubmitButton>
                    </Form>
                  ) : null}
                </div>
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

export default function AdminLivesPage({ searchParams }: PageProps<"/admin/lives">) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement des lives">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-24" />
        </div>
      }
    >
      <Lives searchParams={searchParams} />
    </Suspense>
  );
}
