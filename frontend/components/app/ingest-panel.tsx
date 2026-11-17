"use client";

import { useActionState } from "react";

import {
  issueIngestKeyAction,
  revokeIngestKeyAction,
  rotateIngestKeyAction,
  type IssueKeyState,
} from "@/app/actions/ingest";
import { buttonClasses } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Badge, Card, CardDescription, CardTitle, Notice } from "@/components/ui/primitives";
import { idleState, type FormState } from "@/lib/form-state";
import { cx, formatDateTime } from "@/lib/format";
import type { StreamKey, StreamSession } from "@/types/api";

const INITIAL: IssueKeyState = { ...idleState };

function CopyBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">{label}</p>
      <code className="block overflow-x-auto rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm break-all text-ink-100">
        {value}
      </code>
    </div>
  );
}

function IssuedSecret({ keyData }: { keyData: StreamKey }) {
  if (!keyData.stream_key) {
    return null;
  }
  return (
    <Notice tone="warn" title="Copiez ces valeurs maintenant">
      <p className="mb-3 text-sm">
        La clé secrète ne sera plus jamais réaffichée. Si vous la perdez, générez-en une nouvelle.
      </p>
      <div className="space-y-3">
        {keyData.rtmps_url ? (
          <CopyBlock label="Serveur RTMPS (OBS)" value={keyData.rtmps_url} />
        ) : null}
        <CopyBlock label="Clé de stream" value={keyData.stream_key} />
        {keyData.srt_url ? <CopyBlock label="URL SRT" value={keyData.srt_url} /> : null}
      </div>
    </Notice>
  );
}

function PendingButton({
  pending,
  pendingLabel,
  children,
  variant = "primary",
}: {
  pending: boolean;
  pendingLabel: string;
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "danger";
}) {
  return (
    <button type="submit" disabled={pending} className={buttonClasses({ variant })}>
      {pending ? pendingLabel : children}
    </button>
  );
}

function IssueForm({
  action,
  submitLabel,
  pendingLabel,
  defaultLabel,
}: {
  action: (state: IssueKeyState, formData: FormData) => Promise<IssueKeyState>;
  submitLabel: string;
  pendingLabel: string;
  defaultLabel?: string;
}) {
  const [state, formAction, pending] = useActionState(action, INITIAL);
  return (
    <div className="space-y-4">
      {state.key ? <IssuedSecret keyData={state.key} /> : null}
      <form action={formAction} className="space-y-4">
        <label className="block space-y-1.5 text-sm">
          <span className="font-medium text-ink-200">Libellé (facultatif)</span>
          <input
            name="label"
            maxLength={80}
            defaultValue={defaultLabel ?? state.values?.label ?? ""}
            placeholder="OBS principal"
            className={cx(
              "h-10 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 text-ink-100",
              "placeholder:text-ink-500 focus:border-brand-400 focus:outline-none",
            )}
          />
        </label>
        <PendingButton pending={pending} pendingLabel={pendingLabel}>
          {submitLabel}
        </PendingButton>
        {state.status !== "idle" && state.message ? (
          <p
            role={state.status === "error" ? "alert" : "status"}
            className={cx(
              "rounded-lg border px-3 py-2 text-sm",
              state.status === "error"
                ? "border-danger-500/40 bg-danger-500/10 text-danger-400"
                : "border-ok-500/40 bg-ok-500/10 text-ok-400",
            )}
          >
            {state.message}
          </p>
        ) : null}
      </form>
    </div>
  );
}

export function IngestPanel({
  canManage,
  ingestOnline,
  liveProcessing,
  existingKey,
  sessions,
  timeZone,
}: {
  canManage: boolean;
  ingestOnline: boolean;
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
            <CardTitle className="mt-2">Connexion OBS</CardTitle>
            <CardDescription>
              Ajoutez STREAMCLIP AI comme destination supplémentaire. Vos clés Twitch, YouTube ou
              Kick ne sont jamais demandées.
            </CardDescription>
          </div>
          <Badge tone={ingestOnline ? "ok" : "warn"}>
            {ingestOnline ? "Serveur d'ingestion configuré" : "Serveur d'ingestion hors ligne"}
          </Badge>
        </div>

        {!ingestOnline ? (
          <Notice tone="neutral" title="Ingestion pas encore joignable" className="mt-4">
            Vous pouvez déjà créer votre clé personnelle. Les adresses RTMPS/SRT apparaîtront quand
            le serveur d&apos;ingestion sera mis en ligne.
          </Notice>
        ) : null}

        {!liveProcessing ? (
          <p className="mt-4 text-sm text-ink-300">
            La génération de clips n&apos;est pas encore ouverte : un live reçu permettra de valider
            l&apos;ingestion, sans production de clips.
          </p>
        ) : null}

        {existingKey ? (
          <div className="mt-5 space-y-3 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-white">Clé active</span>
              <Badge>…{existingKey.key_hint}</Badge>
              {existingKey.label ? <span className="text-ink-400">{existingKey.label}</span> : null}
            </div>
            {existingKey.rtmps_url ? (
              <CopyBlock label="Serveur RTMPS" value={existingKey.rtmps_url} />
            ) : null}
            <p className="text-xs text-ink-400">
              Créée le {formatDateTime(existingKey.created_at, timeZone)}
              {existingKey.last_used_at
                ? ` · dernière utilisation ${formatDateTime(existingKey.last_used_at, timeZone)}`
                : ""}
              . Le secret n&apos;est plus affiché.
            </p>
          </div>
        ) : null}

        {canManage ? (
          <div className="mt-5 space-y-4">
            {!existingKey ? (
              <IssueForm
                action={issueIngestKeyAction}
                submitLabel="Créer ma clé d'ingestion"
                pendingLabel="Création…"
              />
            ) : (
              <div className="space-y-4">
                <IssueForm
                  action={rotateIngestKeyAction}
                  submitLabel="Régénérer la clé"
                  pendingLabel="Rotation…"
                  defaultLabel={existingKey.label}
                />
                <Form
                  action={revokeIngestKeyAction as (state: FormState) => Promise<FormState>}
                  className="space-y-2"
                >
                  <SubmitButton variant="danger" pendingLabel="Révocation…">
                    Révoquer la clé
                  </SubmitButton>
                  <FormMessage />
                </Form>
              </div>
            )}
          </div>
        ) : (
          <p className="mt-4 text-sm text-ink-400">
            Seul un administrateur de l&apos;espace peut créer ou régénérer la clé.
          </p>
        )}
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
