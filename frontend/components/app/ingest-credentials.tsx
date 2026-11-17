"use client";

import { useActionState, useEffect, useState } from "react";

import {
  issueIngestKeyAction,
  revokeIngestKeyAction,
  rotateIngestKeyAction,
  type IssueKeyState,
} from "@/app/actions/ingest";
import { buttonClasses } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Notice } from "@/components/ui/primitives";
import { idleState, type FormState } from "@/lib/form-state";
import { cx, formatDateTime } from "@/lib/format";
import type { StreamKey } from "@/types/api";

const INITIAL: IssueKeyState = { ...idleState };

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
  onIssued,
}: {
  action: (state: IssueKeyState, formData: FormData) => Promise<IssueKeyState>;
  submitLabel: string;
  pendingLabel: string;
  defaultLabel?: string;
  onIssued?: (key: StreamKey) => void;
}) {
  const [state, formAction, pending] = useActionState(action, INITIAL);
  const issued = state.key;

  useEffect(() => {
    if (issued?.stream_key) {
      onIssued?.(issued);
    }
  }, [issued, onIssued]);

  return (
    <div className="space-y-4">
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

/** Create / rotate / revoke — one RTMP URL + stream key for OBS. */
export function StreamKeyManager({
  canManage,
  ingestOnline,
  rtmpUrl,
  existingKey,
  timeZone,
  defaultLabel,
  onIssued,
  compact = false,
}: {
  canManage: boolean;
  ingestOnline: boolean;
  rtmpUrl: string | null;
  existingKey: StreamKey | null;
  timeZone?: string;
  defaultLabel?: string;
  onIssued?: (key: StreamKey) => void;
  /** Shorter copy for onboarding. */
  compact?: boolean;
}) {
  const [freshKey, setFreshKey] = useState<StreamKey | null>(null);
  const edgeRtmp = freshKey?.rtmps_url ?? existingKey?.rtmps_url ?? rtmpUrl;
  const activeMeta = freshKey ?? existingKey;
  const clearSecret = freshKey?.stream_key ?? null;

  function handleIssued(key: StreamKey) {
    setFreshKey(key);
    onIssued?.(key);
  }

  return (
    <div className="space-y-4">
      {!compact ? (
        <Notice tone="neutral" title="Connexion OBS / Streamlabs">
          Une URL serveur unique pour tous. Votre clé secrète identifie votre compte : au démarrage
          du live, STREAMCLIP vérifie votre abonnement et vos heures restantes, puis analyse le
          flux automatiquement.
        </Notice>
      ) : null}

      {!ingestOnline ? (
        <Notice tone="warn" title="Serveur hors ligne">
          Vous pouvez créer votre clé ; la connexion OBS sera possible dès le retour en ligne.
        </Notice>
      ) : null}

      {edgeRtmp && !compact ? (
        <div className="rounded-2xl border border-white/10 bg-ink-950/70 p-4">
          <CopyField label="Serveur OBS / Streamlabs" value={edgeRtmp} />
          <p className="mt-2 text-xs text-ink-400">
            Service = Personnalisé · collez ensuite votre clé de stream.
          </p>
        </div>
      ) : null}

      {activeMeta || clearSecret ? (
        <div className="space-y-3 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
          <p className="text-sm font-medium text-white">
            {compact ? "Votre clé STREAMCLIP" : "Clé active"}
            {!compact && activeMeta?.label ? (
              <span className="ml-2 font-normal text-ink-400">· {activeMeta.label}</span>
            ) : null}
          </p>
          {clearSecret ? (
            <>
              <Notice tone="warn" title="Copiez la clé maintenant">
                Elle ne sera plus réaffichée après avoir quitté cette page. L&apos;ancienne clé ne
                fonctionne plus.
              </Notice>
              {edgeRtmp ? <CopyField label="Serveur" value={edgeRtmp} /> : null}
              <CopyField label="Clé secrète" value={clearSecret} />
            </>
          ) : (
            <p className="text-sm leading-relaxed text-ink-400">
              {compact
                ? "Le secret n’est plus visible. Régénérez pour l’afficher, puis collez-le dans votre logiciel."
                : timeZone && activeMeta
                  ? `Créée le ${formatDateTime(activeMeta.created_at, timeZone)}${
                      activeMeta.last_used_at
                        ? ` · dernière utilisation ${formatDateTime(activeMeta.last_used_at, timeZone)}`
                        : ""
                    }. Le secret n’est plus affiché — régénérez-le pour en obtenir un nouveau.`
                  : "Le secret n’est plus affiché — régénérez-le pour en obtenir un nouveau."}
            </p>
          )}
        </div>
      ) : null}

      {canManage ? (
        !existingKey && !freshKey ? (
          <IssueOrRotateForm
            action={issueIngestKeyAction}
            submitLabel="Créer ma clé"
            pendingLabel="Création…"
            defaultLabel={defaultLabel}
            onIssued={handleIssued}
          />
        ) : (
          <div className="space-y-4">
            <IssueOrRotateForm
              action={rotateIngestKeyAction}
              submitLabel={compact ? "Régénérer pour afficher le secret" : "Régénérer la clé"}
              pendingLabel="Régénération…"
              defaultLabel={activeMeta?.label || defaultLabel}
              onIssued={handleIssued}
            />
            {!compact ? (
              <Form
                action={revokeIngestKeyAction as (state: FormState) => Promise<FormState>}
                className="space-y-2"
              >
                <SubmitButton variant="danger" pendingLabel="Révocation…">
                  Révoquer la clé
                </SubmitButton>
                <FormMessage />
              </Form>
            ) : null}
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
