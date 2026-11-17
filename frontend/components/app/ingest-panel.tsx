"use client";

import { StreamKeyManager } from "@/components/app/ingest-credentials";
import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/format";
import type { StreamKey, StreamSession } from "@/types/api";

export function IngestPanel({
  canManage,
  ingestOnline,
  rtmpUrl,
  liveProcessing,
  existingKey,
  sessions,
  timeZone,
}: {
  canManage: boolean;
  ingestOnline: boolean;
  rtmpUrl: string | null;
  liveProcessing: boolean;
  existingKey: StreamKey | null;
  sessions: StreamSession[];
  timeZone: string;
}) {
  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Ingestion</p>
            <CardTitle className="mt-2">Connexion OBS / Streamlabs</CardTitle>
            <CardDescription>
              Une URL RTMP unique + votre clé secrète. Au live, STREAMCLIP analyse le flux et
              prépare vos clips. Vos clés Twitch / YouTube / Kick ne sont jamais demandées.
            </CardDescription>
          </div>
          <Badge tone={ingestOnline ? "ok" : "warn"}>
            {ingestOnline ? "Serveur RTMP en ligne" : "Serveur RTMP hors ligne"}
          </Badge>
        </div>

        {liveProcessing ? (
          <p className="mt-4 text-sm text-ink-300">
            Pendant le live, l&apos;analyse tourne toutes les 5&nbsp;min. Les moments détectés
            apparaissent dans Highlights / Clips.
          </p>
        ) : (
          <p className="mt-4 text-sm text-ink-300">
            L&apos;ingestion est prête ; la génération de clips sera activée dès que le traitement
            live sera ouvert sur cette plateforme.
          </p>
        )}

        <div className="mt-5">
          <StreamKeyManager
            canManage={canManage}
            ingestOnline={ingestOnline}
            rtmpUrl={rtmpUrl}
            existingKey={existingKey}
            timeZone={timeZone}
          />
        </div>
      </Card>

      <Card>
        <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Historique</p>
        <CardTitle className="mt-2">Lives récents</CardTitle>
        <CardDescription>Sessions d&apos;ingestion enregistrées pour cet espace.</CardDescription>
        {sessions.length === 0 ? (
          <p className="mt-5 text-sm text-ink-400">Aucun live pour le moment.</p>
        ) : (
          <ul className="mt-5 divide-y divide-white/5">
            {sessions.map((session) => (
              <li
                key={session.id}
                className="flex flex-wrap items-center justify-between gap-2 py-3.5 text-sm"
              >
                <div>
                  <p className="font-medium text-white capitalize">{session.status}</p>
                  <p className="text-ink-400">
                    {session.started_at
                      ? formatDateTime(session.started_at, timeZone)
                      : formatDateTime(session.created_at, timeZone)}
                    {session.protocol ? ` · ${session.protocol}` : ""}
                  </p>
                </div>
                <p className="text-ink-300">
                  {Math.round(session.processed_ms / 1000)} s traités
                  {session.clips_count > 0 ? ` · ${session.clips_count} clips` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
