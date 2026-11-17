import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { StatusBadge } from "@/components/app/admin-analytics";
import { AdminShell } from "@/components/app/admin-shell";
import { buttonClasses } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/primitives";
import { adminFetch, one, requireStaff } from "@/lib/admin";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AdminClipList } from "@/types/api";

export const metadata: Metadata = {
  title: "Administration — clips",
  robots: { index: false },
};

const PATH = "/admin/clips";

type SearchParams = PageProps<"/admin/clips">["searchParams"];

async function Clips({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireStaff(PATH);
  const query = await searchParams;
  const search = one(query.q).trim().slice(0, 100);
  const cursor = one(query.cursor);
  const params = new URLSearchParams({ limit: "50" });
  if (search) params.set("search", search);
  if (/^[0-9a-f-]{36}$/i.test(cursor)) params.set("cursor", cursor);

  const data = await adminFetch<AdminClipList>(`/admin/clips?${params}`, token, PATH);
  const { items, next_cursor: nextCursor } = data;
  const timeZone = me.user.timezone;
  const nextParams = new URLSearchParams();
  if (search) nextParams.set("q", search);
  if (nextCursor) nextParams.set("cursor", nextCursor);

  return (
    <AdminShell
      title="Clips"
      description="Tous les clips générés par les utilisateurs, du plus récent au plus ancien."
    >
      <form action={PATH} className="flex max-w-md gap-2">
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
          <p className="text-sm text-ink-300">Aucun clip trouvé.</p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => (
            <li key={item.id}>
              <Card className="p-5">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="min-w-0 truncate text-sm font-medium text-white">{item.title}</p>
                  <StatusBadge status={item.status} />
                  <span className="text-xs text-ink-400">{item.category}</span>
                  {item.is_favorite ? <span className="text-xs text-warn-400">Favori</span> : null}
                </div>
                <p className="mt-1.5 text-xs text-ink-400">
                  {item.owner_email ?? "—"} · score {item.score.toFixed(2)} ·{" "}
                  {formatDuration(Math.floor(item.duration_ms / 1000))} · créé{" "}
                  {formatDateTime(item.created_at, timeZone)}
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

export default function AdminClipsPage({ searchParams }: PageProps<"/admin/clips">) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement des clips">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-24" />
        </div>
      }
    >
      <Clips searchParams={searchParams} />
    </Suspense>
  );
}
