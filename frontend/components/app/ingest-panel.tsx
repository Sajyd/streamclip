"use client";

import { StreamKeyManager } from "@/components/app/ingest-credentials";
import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { formatDateTime } from "@/lib/format";
import type { StreamKey, StreamSession } from "@/types/api";

export function IngestPanel({
  canManage,
  ingestOnline,
  apiUrl,
  liveProcessing,
  existingKey,
  sessions,
  timeZone,
}: {
  canManage: boolean;
  ingestOnline: boolean;
  apiUrl: string | null;
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
              Une URL API unique : avec votre clé, elle démarre votre instance spot dédiée et
              renvoie l&apos;adresse RTMP. Vos clés Twitch, YouTube ou Kick ne sont jamais demandées.
            </CardDescription>
          </div>
          <Badge tone={ingestOnline ? "ok" : "warn"}>
            {ingestOnline ? "Instances d'ingestion prêtes" : "Instances en déploiement"}
          </Badge>
        </div>

        {!liveProcessing ? (
          <p className="mt-4 text-sm text-ink-300">
            La génération de clips n&apos;est pas encore ouverte : un live reçu permettra de valider
            l&apos;ingestion, sans production de clips.
          </p>
        ) : null}

        <div className="mt-5">
          <StreamKeyManager
            canManage={canManage}
            ingestOnline={ingestOnline}
            apiUrl={apiUrl}
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
