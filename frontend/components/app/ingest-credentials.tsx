"use client";

import { useActionState, useState } from "react";

import {
  issueIngestKeyAction,
  revokeIngestKeyAction,
  rotateIngestKeyAction,
  resolveIngestAction,
  type IssueKeyState,
  type ResolveState,
} from "@/app/actions/ingest";
import { buttonClasses } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Badge, Notice } from "@/components/ui/primitives";
import { idleState, type FormState } from "@/lib/form-state";
import { cx, formatDateTime } from "@/lib/format";
import type { StreamKey } from "@/types/api";

const INITIAL: IssueKeyState = { ...idleState };
const RESOLVE_INITIAL: ResolveState = { ...idleState };

/** Full-value copy field — long keys must wrap, never truncate. */
export function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">{label}</p>
        <button
          type="button"
          className="shrink-0 text-xs font-medium text-brand-300 hover:text-brand-200"
          onClick={async () => {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copié" : "Copier"}
        </button>
      </div>
      <code className="block max-h-40 overflow-y-auto rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm leading-relaxed break-all whitespace-pre-wrap text-ink-100 select-all">
        {value}
      </code>
    </div>
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

function IssueOrRotateForm({
  action,
  submitLabel,
  pendingLabel,
  defaultLabel,
  apiUrl,
}: {
  action: (state: IssueKeyState, formData: FormData) => Promise<IssueKeyState>;
  submitLabel: string;
  pendingLabel: string;
  defaultLabel?: string;
  apiUrl: string | null;
}) {
  const [state, formAction, pending] = useActionState(action, INITIAL);
  const issued = state.key;
  const resolveUrl = issued?.ingest_api_url ?? apiUrl;

  return (
    <div className="space-y-4">
      {issued?.stream_key ? (
        <div className="space-y-3">
          <Notice tone="warn" title="Copiez ces valeurs maintenant">
            La clé secrète ne sera plus jamais réaffichée. Si vous la perdez, régénérez-en une depuis
            Paramètres. L&apos;URL API démarre votre instance spot et renvoie l&apos;adresse RTMP.
          </Notice>
          {resolveUrl ? <CopyField label="URL API (resolve → RTMP)" value={resolveUrl} /> : null}
          <CopyField label="Clé secrète (stream key)" value={issued.stream_key} />
          {issued.rtmps_url ? (
            <CopyField label="Serveur RTMP (instance prête)" value={issued.rtmps_url} />
          ) : null}
        </div>
      ) : null}
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

function PrepareLiveForm({ apiUrl }: { apiUrl: string | null }) {
  const [state, formAction, pending] = useActionState(resolveIngestAction, RESOLVE_INITIAL);
  const resolved = state.resolve;

  return (
    <div className="space-y-3 rounded-2xl border border-white/10 bg-ink-950/50 p-4">
      <p className="text-sm font-medium text-white">Préparer mon live</p>
      <p className="text-xs leading-relaxed text-ink-400">
        Démarre votre EC2 spot dédié (MediaMTX + analyse). L&apos;API renvoie l&apos;URL RTMP à
        coller dans OBS avec votre clé secrète (conservée de votre côté).
      </p>
      {apiUrl ? <CopyField label="URL API" value={apiUrl} /> : null}
      <form action={formAction} className="space-y-3">
        <PendingButton pending={pending} pendingLabel="Démarrage de l'instance…">
          Démarrer mon instance
        </PendingButton>
      </form>
      {resolved ? (
        <div className="space-y-3 border-t border-white/5 pt-3">
          <Badge tone={resolved.status === "ready" ? "ok" : "warn"}>{resolved.status}</Badge>
          <p className="text-sm text-ink-300">{resolved.message}</p>
          {resolved.rtmp_url ? (
            <CopyField label="Serveur RTMP (OBS / Streamlabs)" value={resolved.rtmp_url} />
          ) : null}
          {resolved.analysis_url ? (
            <CopyField label="Port analyse (instance)" value={resolved.analysis_url} />
          ) : null}
        </div>
      ) : null}
      {state.status === "error" && state.message ? (
        <p role="alert" className="text-sm text-danger-400">
          {state.message}
        </p>
      ) : null}
    </div>
  );
}

/** Create / rotate / revoke + resolve dedicated RTMP instance (show-once secret). */
export function StreamKeyManager({
  canManage,
  ingestOnline,
  apiUrl,
  existingKey,
  timeZone,
  defaultLabel,
}: {
  canManage: boolean;
  ingestOnline: boolean;
  apiUrl: string | null;
  existingKey: StreamKey | null;
  timeZone?: string;
  defaultLabel?: string;
}) {
  const resolveUrl = existingKey?.ingest_api_url ?? apiUrl;

  return (
    <div className="space-y-4">
      <Notice tone="neutral" title="Comment ça marche">
        Une seule <strong className="font-medium text-ink-100">URL API</strong> pour tout le monde.
        Avec votre clé secrète, elle démarre votre instance spot dédiée et renvoie{" "}
        <code className="text-ink-200">rtmp://…</code> (MediaMTX). Toutes les 5&nbsp;min, FFmpeg
        enregistre puis l&apos;analyse met à jour la base — le tableau de bord affiche le résultat.
      </Notice>

      {!ingestOnline ? (
        <Notice tone="warn" title="Data plane en cours de déploiement">
          Vous pouvez déjà créer votre clé et utiliser l&apos;URL API. L&apos;instance spot se
          lancera dès que le provisionnement EC2 est actif.
        </Notice>
      ) : null}

      {resolveUrl ? (
        <div className="rounded-2xl border border-white/10 bg-ink-950/70 p-4">
          <CopyField label="URL API (resolve → RTMP)" value={resolveUrl} />
        </div>
      ) : null}

      {existingKey ? (
        <div className="space-y-3 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium text-white">Clé active</span>
            <Badge>…{existingKey.key_hint}</Badge>
            {existingKey.label ? <span className="text-ink-400">{existingKey.label}</span> : null}
          </div>
          {existingKey.rtmps_url ? (
            <CopyField label="Serveur RTMP (instance prête)" value={existingKey.rtmps_url} />
          ) : null}
          <p className="text-xs text-ink-400">
            {timeZone
              ? `Créée le ${formatDateTime(existingKey.created_at, timeZone)}${
                  existingKey.last_used_at
                    ? ` · dernière utilisation ${formatDateTime(existingKey.last_used_at, timeZone)}`
                    : ""
                }. `
              : null}
            Le secret n&apos;est plus affiché — régénérez-le pour en obtenir un nouveau.
          </p>
        </div>
      ) : null}

      {canManage ? (
        !existingKey ? (
          <IssueOrRotateForm
            action={issueIngestKeyAction}
            submitLabel="Créer ma clé d'ingestion"
            pendingLabel="Création…"
            defaultLabel={defaultLabel}
            apiUrl={apiUrl}
          />
        ) : (
          <div className="space-y-4">
            <PrepareLiveForm apiUrl={resolveUrl} />
            <IssueOrRotateForm
              action={rotateIngestKeyAction}
              submitLabel="Régénérer la clé"
              pendingLabel="Régénération…"
              defaultLabel={existingKey.label || defaultLabel}
              apiUrl={apiUrl}
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
        )
      ) : (
        <p className="text-sm text-ink-400">
          Seul un administrateur de l&apos;espace peut créer ou régénérer la clé.
        </p>
      )}
    </div>
  );
}
