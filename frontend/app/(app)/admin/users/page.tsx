import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";

import { reactivateUserAction, suspendUserAction } from "@/app/actions/admin";
import { buttonClasses } from "@/components/ui/button";
import { Field, Form, SubmitButton } from "@/components/ui/form";
import { Badge, Card, Skeleton } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { requireSession, ServiceUnavailableError } from "@/lib/dal";
import { formatDateTime } from "@/lib/format";
import type { AdminUser, AdminUserList } from "@/types/api";

export const metadata: Metadata = { title: "Administration — utilisateurs", robots: { index: false } };

const PATH = "/admin/users";

type SearchParams = PageProps<"/admin/users">["searchParams"];

const STATUS: Record<AdminUser["status"], { label: string; tone: "ok" | "warn" | "danger" | "neutral" }> = {
  active: { label: "Actif", tone: "ok" },
  suspended: { label: "Suspendu", tone: "danger" },
  pending_deletion: { label: "Suppression en cours", tone: "warn" },
  deleted: { label: "Supprimé", tone: "neutral" },
};

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

async function Users({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireSession(PATH);
  if (me.user.platform_role === "user") {
    // The API refuses anyway; the page does not reveal that it exists.
    notFound();
  }
  const query = await searchParams;
  const search = one(query.q).trim().slice(0, 100);
  const cursor = one(query.cursor);
  const params = new URLSearchParams({ limit: "50" });
  if (search) params.set("search", search);
  if (/^[0-9a-f-]{36}$/i.test(cursor)) params.set("cursor", cursor);

  const result = await api<AdminUserList>(`/admin/users?${params}`, { token });
  if (!result.ok) {
    if (result.error.status === 401) {
      redirect(`/auth/refresh?next=${encodeURIComponent(PATH)}`);
    }
    if (result.error.status === 403) {
      notFound();
    }
    throw new ServiceUnavailableError();
  }
  const { items, next_cursor: nextCursor } = result.data;
  const isAdmin = me.user.platform_role === "admin";
  const timeZone = me.user.timezone;
  const nextParams = new URLSearchParams();
  if (search) nextParams.set("q", search);
  if (nextCursor) nextParams.set("cursor", nextCursor);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Utilisateurs</h1>
        <p className="mt-1 text-sm text-ink-300">
          Comptes de la plateforme, du plus récent au plus ancien. Chaque suspension est journalisée.
        </p>
      </div>

      <form action={PATH} className="flex max-w-md gap-2">
        <label htmlFor="q" className="sr-only">
          Rechercher par adresse e-mail
        </label>
        <input
          id="q"
          name="q"
          type="search"
          defaultValue={search}
          maxLength={100}
          placeholder="Rechercher par adresse e-mail"
          className="block w-full rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-ink-100 placeholder:text-ink-500"
        />
        <button type="submit" className={buttonClasses({ variant: "secondary", size: "sm" })}>
          Rechercher
        </button>
      </form>

      {items.length === 0 ? (
        <Card>
          <p className="text-sm text-ink-300">Aucun compte ne correspond.</p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((user) => {
            const status = STATUS[user.status] ?? { label: user.status, tone: "neutral" as const };
            return (
              <li key={user.id}>
                <Card className="p-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 truncate text-sm font-medium text-white">{user.email}</p>
                    <Badge tone={status.tone}>{status.label}</Badge>
                    {user.platform_role !== "user" ? <Badge tone="brand">{user.platform_role}</Badge> : null}
                    {user.email_verified ? null : <Badge tone="warn">E-mail non confirmé</Badge>}
                  </div>
                  <p className="mt-1.5 text-xs text-ink-400">
                    {user.display_name ? `${user.display_name} · ` : ""}
                    Offre {user.plan_code ?? "—"} · inscrit le {formatDateTime(user.created_at, timeZone)} ·{" "}
                    {user.last_login_at
                      ? `dernière connexion le ${formatDateTime(user.last_login_at, timeZone)}`
                      : "jamais connecté"}
                  </p>
                  {isAdmin && user.id !== me.user.id && user.status === "active" ? (
                    <Form action={suspendUserAction} className="mt-4 flex flex-wrap items-end gap-3 space-y-0">
                      <input type="hidden" name="user_id" value={user.id} />
                      <Field
                        name="reason"
                        label="Motif de la suspension"
                        maxLength={500}
                        required
                        className="min-w-56 flex-1"
                      />
                      <SubmitButton variant="danger" size="sm" pendingLabel="Suspension…">
                        Suspendre
                      </SubmitButton>
                    </Form>
                  ) : null}
                  {isAdmin && user.status === "suspended" ? (
                    <Form action={reactivateUserAction} className="mt-4 space-y-2">
                      <input type="hidden" name="user_id" value={user.id} />
                      <SubmitButton variant="secondary" size="sm" pendingLabel="Réactivation…">
                        Réactiver
                      </SubmitButton>
                    </Form>
                  ) : null}
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {nextCursor ? (
        <Link href={`${PATH}?${nextParams}`} className={buttonClasses({ variant: "secondary", size: "sm" })}>
          Comptes suivants
        </Link>
      ) : null}
    </div>
  );
}

export default function AdminUsersPage({ searchParams }: PageProps<"/admin/users">) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement des utilisateurs">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      }
    >
      <Users searchParams={searchParams} />
    </Suspense>
  );
}
