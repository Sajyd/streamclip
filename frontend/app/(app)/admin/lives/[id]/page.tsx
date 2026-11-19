import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { stopLiveAction } from "@/app/actions/admin";
import { StatusBadge } from "@/components/app/admin-analytics";
import { AdminLivePlayer } from "@/components/app/admin-live-player";
import { AdminShell } from "@/components/app/admin-shell";
import { buttonClasses } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Card, Skeleton } from "@/components/ui/primitives";
import { adminFetch, requireStaff } from "@/lib/admin";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { AdminLiveDetail } from "@/types/api";

export const metadata: Metadata = {
  title: "Administration — détail live",
  robots: { index: false },
};

/** Dynamic id + client nav hooks — do not prerender the shell. */
export const instant = false;

type Props = PageProps<"/admin/lives/[id]">;

async function LiveDetail({ params }: { params: Props["params"] }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  const path = `/admin/lives/${id}`;
  const { token, me } = await requireStaff(path);
  let detail: AdminLiveDetail;
  try {
    detail = await adminFetch<AdminLiveDetail>(`/admin/lives/${id}`, token, path);
  } catch {
    notFound();
  }
  const timeZone = me.user.timezone;
  const canStop = ["pending", "live", "interrupted", "finalizing"].includes(detail.status);

  return (
    <AdminShell
      title={detail.title || "Live sans titre"}
      description={`Journal pipeline · ${detail.owner_email ?? "—"} · ${detail.organization_name}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {canStop ? (
            <Form action={stopLiveAction} className="flex flex-wrap items-center gap-2 space-y-0">
              <input type="hidden" name="live_id" value={detail.id} />
              <SubmitButton variant="danger" size="sm" pendingLabel="Arrêt…">
                Arrêter le live
              </SubmitButton>
              <FormMessage />
            </Form>
          ) : null}
          <Link href="/admin/lives?all=1" className={buttonClasses({ variant: "secondary", size: "sm" })}>
            Retour aux lives
          </Link>
        </div>
      }
    >
      <AdminLivePlayer
        liveId={detail.id}
        initial={detail.playback}
        streamKeyPublicId={detail.stream_key_public_id}
        streamKeyHint={detail.stream_key_hint}
        rtmpUrl={detail.rtmp_url}
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={detail.status} />
            {detail.protocol ? (
              <span className="text-xs uppercase text-ink-400">{detail.protocol}</span>
            ) : null}
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-ink-400">Créé</dt>
            <dd className="text-ink-100">{formatDateTime(detail.created_at, timeZone)}</dd>
            <dt className="text-ink-400">Démarré</dt>
            <dd className="text-ink-100">
              {detail.started_at ? formatDateTime(detail.started_at, timeZone) : "—"}
            </dd>
            <dt className="text-ink-400">Dernier média</dt>
            <dd className="text-ink-100">
              {detail.last_media_at ? formatDateTime(detail.last_media_at, timeZone) : "—"}
            </dd>
            <dt className="text-ink-400">Terminé</dt>
            <dd className="text-ink-100">
              {detail.ended_at ? formatDateTime(detail.ended_at, timeZone) : "—"}
            </dd>
            <dt className="text-ink-400">Traité</dt>
            <dd className="text-ink-100">
              {formatDuration(Math.floor(detail.processed_ms / 1000))} · {detail.clips_count} clip
              {detail.clips_count > 1 ? "s" : ""}
            </dd>
            {detail.end_reason ? (
              <>
                <dt className="text-ink-400">Fin</dt>
                <dd className="text-ink-100">{detail.end_reason}</dd>
              </>
            ) : null}
            {detail.error_code || detail.error_message ? (
              <>
                <dt className="text-ink-400">Erreur</dt>
                <dd className="text-red-300">
                  {detail.error_code}
                  {detail.error_message ? ` — ${detail.error_message}` : ""}
                </dd>
              </>
            ) : null}
          </dl>
        </Card>

        <Card className="space-y-3 p-5">
          <h2 className="text-sm font-medium text-white">Instance dédiée</h2>
          {detail.ingest_node ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-ink-400">Statut</dt>
              <dd>
                <StatusBadge status={detail.ingest_node.status} />
              </dd>
              <dt className="text-ink-400">Host</dt>
              <dd className="font-mono text-xs text-ink-100">
                {detail.ingest_node.public_hostname ?? "—"}
              </dd>
              <dt className="text-ink-400">EC2</dt>
              <dd className="font-mono text-xs text-ink-100">
                {detail.ingest_node.instance_id ?? "—"}
              </dd>
              <dt className="text-ink-400">Agent</dt>
              <dd className="flex flex-wrap gap-2 text-sm">
                {detail.ingest_node.analysis_health_url ? (
                  <a
                    href={detail.ingest_node.analysis_health_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-emerald-300/90 underline-offset-2 hover:underline"
                  >
                    /health
                  </a>
                ) : (
                  <span className="text-ink-500">—</span>
                )}
                {detail.ingest_node.analysis_status_url ? (
                  <a
                    href={detail.ingest_node.analysis_status_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-emerald-300/90 underline-offset-2 hover:underline"
                  >
                    /status
                  </a>
                ) : null}
              </dd>
              {detail.ingest_node.launch_error ? (
                <>
                  <dt className="text-ink-400">Launch</dt>
                  <dd className="text-red-300">{detail.ingest_node.launch_error}</dd>
                </>
              ) : null}
            </dl>
          ) : (
            <p className="text-sm text-ink-400">Aucune instance liée.</p>
          )}
        </Card>
      </div>

      <Card className="space-y-3 p-5">
        <h2 className="text-sm font-medium text-white">
          Journal pipeline ({detail.pipeline_log.length})
        </h2>
        {detail.pipeline_log.length === 0 ? (
          <p className="text-sm text-ink-400">
            Aucun événement enregistré (les lives démarrés avant ce déploiement n&apos;ont pas de
            journal).
          </p>
        ) : (
          <ol className="max-h-[28rem] space-y-2 overflow-y-auto font-mono text-xs">
            {detail.pipeline_log.map((ev) => (
              <li
                key={ev.id}
                className="rounded border border-ink-700 bg-ink-950/60 px-3 py-2 text-ink-200"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-ink-500">{formatDateTime(ev.occurred_at, timeZone)}</span>
                  <span
                    className={
                      ev.outcome === "failure" ? "text-red-300" : "text-emerald-300/90"
                    }
                  >
                    {ev.outcome}
                  </span>
                  <span className="text-white">{ev.action}</span>
                  {ev.ip ? <span className="text-ink-500">{ev.ip}</span> : null}
                </div>
                {Object.keys(ev.details).length > 0 ? (
                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-ink-400">
                    {JSON.stringify(ev.details, null, 0)}
                  </pre>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3 p-5">
          <h2 className="text-sm font-medium text-white">Tasks ({detail.tasks.length})</h2>
          {detail.tasks.length === 0 ? (
            <p className="text-sm text-ink-400">Aucune task liée.</p>
          ) : (
            <ul className="max-h-80 space-y-2 overflow-y-auto text-xs">
              {detail.tasks.map((t) => (
                <li key={t.id} className="rounded border border-ink-700 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-ink-100">{t.kind}</span>
                    <StatusBadge status={t.status} />
                    <span className="text-ink-500">×{t.attempts}</span>
                  </div>
                  <p className="mt-1 text-ink-500">{formatDateTime(t.created_at, timeZone)}</p>
                  {t.last_error ? <p className="mt-1 text-red-300">{t.last_error}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="space-y-3 p-5">
          <h2 className="text-sm font-medium text-white">
            Highlights ({detail.highlights.length})
          </h2>
          {detail.highlights.length === 0 ? (
            <p className="text-sm text-ink-400">Aucun highlight pour ce live.</p>
          ) : (
            <ul className="max-h-80 space-y-2 overflow-y-auto text-sm">
              {detail.highlights.map((h) => (
                <li key={h.id} className="rounded border border-ink-700 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-white">{h.title}</span>
                    <StatusBadge status={h.status} />
                    <span className="text-xs text-ink-400">score {h.score.toFixed(2)}</span>
                  </div>
                  <p className="mt-1 text-xs text-ink-500">
                    {Math.round(h.start_ms / 1000)}s → {Math.round(h.end_ms / 1000)}s
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </AdminShell>
  );
}

export default function AdminLiveDetailPage({ params }: Props) {
  return (
    <Suspense
      fallback={
        <div className="space-y-3" aria-busy aria-label="Chargement du live">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40" />
          <Skeleton className="h-64" />
        </div>
      }
    >
      <LiveDetail params={params} />
    </Suspense>
  );
}
