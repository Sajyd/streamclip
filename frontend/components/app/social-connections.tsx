"use client";

import { useActionState, useEffect, useState } from "react";

import {
  connectSocialAction,
  disconnectSocialAction,
  updateAutoPublishAction,
  type SocialFormState,
} from "@/app/actions/social";
import { buttonClasses } from "@/components/ui/button";
import { Badge, Notice } from "@/components/ui/primitives";
import { idleState } from "@/lib/form-state";
import { cx } from "@/lib/format";
import type { SocialAccountList } from "@/types/api";

const PLATFORMS = [
  { id: "youtube", label: "YouTube Shorts" },
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram Reels" },
] as const;

const INITIAL: SocialFormState = { ...idleState };

export function SocialConnections({
  initial,
  canManage,
}: {
  initial: SocialAccountList;
  canManage: boolean;
}) {
  const [accounts, setAccounts] = useState(initial.items);
  const [auto, setAuto] = useState(
    () => new Set(initial.items.filter((a) => a.auto_publish).map((a) => a.platform)),
  );
  const [connectState, connectAction, connecting] = useActionState(connectSocialAction, INITIAL);
  const [autoState, autoAction, savingAuto] = useActionState(updateAutoPublishAction, INITIAL);
  const [disconnectState, disconnectAction, disconnecting] = useActionState(
    disconnectSocialAction,
    INITIAL,
  );

  useEffect(() => {
    if (connectState.authorizeUrl) {
      window.location.assign(connectState.authorizeUrl);
    }
  }, [connectState.authorizeUrl]);

  return (
    <div className="space-y-5">
      <Notice tone="neutral" title="Publication automatique">
        Connectez YouTube, TikTok et Instagram via leurs connexions officielles. Activez ensuite la
        publication auto : dès qu&apos;un clip est prêt, STREAMCLIP le pousse sur les réseaux choisis.
      </Notice>

      {!initial.oauth_available ? (
        <Notice tone="warn" title="Connexion sociale indisponible">
          La publication automatique n&apos;est pas activée sur cette plateforme.
        </Notice>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        {PLATFORMS.map((platform) => {
          const linked = accounts.find(
            (a) => a.platform === platform.id && a.status === "connected",
          );
          return (
            <div
              key={platform.id}
              className="rounded-2xl border border-white/10 bg-ink-950/60 p-4"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-medium text-white">{platform.label}</p>
                <Badge tone={linked ? "ok" : "warn"}>{linked ? "Connecté" : "Libre"}</Badge>
              </div>
              {linked ? (
                <p className="mt-2 truncate text-xs text-ink-400">{linked.display_name}</p>
              ) : (
                <p className="mt-2 text-xs text-ink-400">Autorisez STREAMCLIP à publier.</p>
              )}
              {canManage && initial.oauth_available ? (
                linked ? (
                  <form action={disconnectAction} className="mt-4">
                    <input type="hidden" name="account_id" value={linked.id} />
                    <button
                      type="submit"
                      disabled={disconnecting}
                      className={buttonClasses({ variant: "secondary", className: "w-full" })}
                      onClick={() =>
                        setAccounts((current) => current.filter((a) => a.id !== linked.id))
                      }
                    >
                      Déconnecter
                    </button>
                  </form>
                ) : (
                  <form action={connectAction} className="mt-4">
                    <input type="hidden" name="platform" value={platform.id} />
                    <button
                      type="submit"
                      disabled={connecting}
                      className={buttonClasses({ className: "w-full" })}
                    >
                      {connecting ? "Redirection…" : "Connecter"}
                    </button>
                  </form>
                )
              ) : null}
            </div>
          );
        })}
      </div>

      {canManage && initial.oauth_available ? (
        <form action={autoAction} className="space-y-3 rounded-2xl border border-white/10 p-4">
          <p className="text-sm font-medium text-white">Publier automatiquement sur</p>
          <div className="flex flex-wrap gap-3">
            {PLATFORMS.map((platform) => {
              const checked = auto.has(platform.id);
              return (
                <label
                  key={platform.id}
                  className={cx(
                    "flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2 text-sm",
                    checked ? "border-brand-400/50 bg-brand-500/10" : "border-white/10",
                  )}
                >
                  <input
                    type="checkbox"
                    name="platforms"
                    value={platform.id}
                    checked={checked}
                    onChange={() => {
                      setAuto((current) => {
                        const next = new Set(current);
                        if (next.has(platform.id)) next.delete(platform.id);
                        else next.add(platform.id);
                        return next;
                      });
                    }}
                  />
                  {platform.label}
                </label>
              );
            })}
          </div>
          <button
            type="submit"
            disabled={savingAuto}
            className={buttonClasses({ variant: "secondary" })}
          >
            {savingAuto ? "Enregistrement…" : "Enregistrer"}
          </button>
          {autoState.message ? (
            <p className="text-sm text-ink-300" role="status">
              {autoState.message}
            </p>
          ) : null}
        </form>
      ) : null}

      {connectState.status === "error" && connectState.message ? (
        <p role="alert" className="text-sm text-danger-400">
          {connectState.message}
        </p>
      ) : null}
      {disconnectState.status === "error" && disconnectState.message ? (
        <p role="alert" className="text-sm text-danger-400">
          {disconnectState.message}
        </p>
      ) : null}
    </div>
  );
}
