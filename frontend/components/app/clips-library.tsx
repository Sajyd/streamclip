"use client";

import { useActionState, useEffect } from "react";

import { clipDownloadUrlAction, type DownloadState } from "@/app/actions/clips";
import { buttonClasses } from "@/components/ui/button";
import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { idleState } from "@/lib/form-state";
import { cx, formatDateTime } from "@/lib/format";
import type { Clip } from "@/types/api";

const CATEGORY_LABELS: Record<string, string> = {
  funny_story: "Histoire drôle",
  punchline: "Punchline",
  debate: "Débat",
  revelation: "Révélation",
  unexpected_reaction: "Réaction",
  victory: "Victoire",
  epic_fail: "Fail",
  impressive_action: "Action",
  absurd_situation: "Absurde",
  emotional_moment: "Émotion",
  performance: "Performance",
  interesting_exchange: "Échange",
  other: "Moment fort",
};

function formatDuration(ms: number | null): string {
  if (!ms || ms <= 0) return "—";
  const total = Math.round(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes > 0 ? `${minutes}:${String(seconds).padStart(2, "0")}` : `${seconds}s`;
}

function DownloadButton({ clip }: { clip: Clip }) {
  const [state, formAction, pending] = useActionState(
    clipDownloadUrlAction,
    idleState as DownloadState,
  );

  useEffect(() => {
    if (state.status === "success" && state.url) {
      window.open(state.url, "_blank", "noopener,noreferrer");
    }
  }, [state]);

  if (!clip.download_available) {
    return (
      <span className="text-xs text-ink-500">
        {clip.status === "ready" ? "Fichier bientôt disponible" : "En préparation"}
      </span>
    );
  }

  return (
    <form action={formAction}>
      <input type="hidden" name="clip_id" value={clip.id} />
      <button type="submit" disabled={pending} className={buttonClasses({ variant: "secondary", size: "sm" })}>
        {pending ? "Préparation…" : "Télécharger"}
      </button>
      {state.status === "error" && state.message ? (
        <p className="mt-1 text-xs text-danger-400">{state.message}</p>
      ) : null}
    </form>
  );
}

export function ClipsLibrary({ clips, timeZone }: { clips: Clip[]; timeZone: string }) {
  return (
    <Card>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Bibliothèque</p>
          <CardTitle className="mt-2">Vos clips</CardTitle>
          <CardDescription>
            Téléchargez-les ou publiez-les vous-même sur YouTube, TikTok ou Instagram.
          </CardDescription>
        </div>
        <Badge tone={clips.length > 0 ? "brand" : "neutral"}>
          {clips.length} clip{clips.length === 1 ? "" : "s"}
        </Badge>
      </div>

      {clips.length === 0 ? (
        <div className="mt-6 rounded-2xl border border-dashed border-white/10 bg-ink-950/50 px-5 py-8 text-center">
          <p className="text-sm font-medium text-white">Aucun clip pour le moment</p>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-400">
            Lancez un live avec votre clé STREAMCLIP. Les moments forts apparaîtront ici, prêts à
            télécharger et à publier.
          </p>
        </div>
      ) : (
        <ul className="mt-6 divide-y divide-white/5">
          {clips.map((clip) => (
            <li
              key={clip.id}
              className="flex flex-wrap items-center justify-between gap-4 py-4 first:pt-2"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate font-medium text-white">{clip.title}</p>
                  <Badge tone={clip.status === "ready" ? "ok" : "neutral"}>
                    {clip.status === "ready" ? "Prêt" : clip.status}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-ink-400">
                  {CATEGORY_LABELS[clip.category] ?? clip.category}
                  {" · "}
                  {formatDuration(clip.duration_ms)}
                  {" · "}
                  {formatDateTime(clip.created_at, timeZone)}
                </p>
                {clip.description ? (
                  <p className={cx("mt-1 line-clamp-2 text-sm text-ink-300")}>{clip.description}</p>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                <DownloadButton clip={clip} />
                {clip.download_available ? (
                  <p className="text-xs text-ink-500">Puis publiez depuis votre téléphone ou PC</p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
