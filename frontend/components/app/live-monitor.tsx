"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { LivePlayer } from "@/components/app/live-player";
import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { cx, formatDateTime } from "@/lib/format";
import { fetchLiveHighlights, fetchLivePlayback } from "@/lib/live-poll";
import type { Highlight, LivePlayback } from "@/types/api";

type Toast = { id: string; title: string; score: number };

type Props = {
  initialPlayback: LivePlayback;
  initialHighlights?: Highlight[];
  hlsBase: string;
  /** When true, also poll highlights for the active session. */
  pollHighlights?: boolean;
  timeZone?: string;
  /** Player only — for dashboard grid cards. */
  playerOnly?: boolean;
  showList?: boolean;
  className?: string;
};

export function LiveMonitor({
  initialPlayback,
  initialHighlights = [],
  hlsBase,
  pollHighlights = false,
  timeZone = "UTC",
  playerOnly = false,
  showList = true,
  className,
}: Props) {
  const [playback, setPlayback] = useState(initialPlayback);
  const [highlights, setHighlights] = useState(initialHighlights);
  const [toast, setToast] = useState<Toast | null>(null);
  const knownIds = useRef(new Set(initialHighlights.map((h) => h.id)));
  const primed = useRef(false);

  useEffect(() => {
    setPlayback(initialPlayback);
  }, [initialPlayback]);

  useEffect(() => {
    setHighlights(initialHighlights);
    if (!primed.current) {
      knownIds.current = new Set(initialHighlights.map((h) => h.id));
      primed.current = true;
    }
  }, [initialHighlights]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const next = await fetchLivePlayback(controller.signal);
        if (cancelled) return;
        setPlayback(next);
        if (!pollHighlights || playerOnly) return;
        const list = await fetchLiveHighlights(next.session_id, controller.signal);
        if (cancelled) return;
        setHighlights(list);
        for (const item of list) {
          if (knownIds.current.has(item.id)) continue;
          knownIds.current.add(item.id);
          setToast({ id: item.id, title: item.title, score: item.score });
          window.setTimeout(() => {
            setToast((current) => (current?.id === item.id ? null : current));
          }, 6000);
          break;
        }
      } catch {
        // Keep last known state on transient failures.
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 4000);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pollHighlights, playerOnly]);

  // Prefer media playlist; master (index) also works once rewritten by the proxy.
  const src =
    playback.preview_available && (playback.status === "live" || playback.status === "starting")
      ? `${hlsBase}/index.m3u8`
      : null;

  const sessionHighlights = playback.session_id
    ? highlights.filter((h) => h.stream_session_id === playback.session_id)
    : highlights;

  const friendlyMessage =
    playback.status === "live"
      ? "Votre live est en cours."
      : playback.status === "starting"
        ? "Préparation de l'aperçu…"
        : "Aucun live en cours pour le moment.";

  if (playerOnly) {
    return (
      <LivePlayer
        className={className}
        fill
        src={src}
        status={playback.status}
        message={friendlyMessage}
      />
    );
  }

  return (
    <div
      className={cx(
        "relative space-y-5 lg:grid lg:grid-cols-[1.4fr_1fr] lg:gap-5 lg:space-y-0",
        className,
      )}
    >
      {toast ? (
        <div
          role="status"
          className="fixed right-4 bottom-4 z-50 max-w-sm rounded-2xl border border-brand-500/40 bg-ink-900/95 px-4 py-3 shadow-xl backdrop-blur"
        >
          <p className="text-xs font-medium tracking-[0.14em] text-brand-300 uppercase">
            Moment fort détecté
          </p>
          <p className="mt-1 text-sm font-medium text-white">{toast.title}</p>
          <p className="mt-0.5 text-xs text-ink-400">
            Score {Math.round(toast.score * 100)} ·{" "}
            <Link href="/highlights" className="text-brand-300 hover:text-brand-200">
              Voir les highlights
            </Link>
          </p>
        </div>
      ) : null}

      <div className="space-y-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Live</p>
          <CardTitle className="mt-2">Aperçu en direct</CardTitle>
          <CardDescription>
            Suivez votre diffusion et les moments forts détectés automatiquement.
          </CardDescription>
        </div>
        <LivePlayer src={src} status={playback.status} message={friendlyMessage} />
      </div>

      {showList ? (
        <Card>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">
                Highlights
              </p>
              <CardTitle className="mt-1.5 text-base">
                Moments détectés
                {sessionHighlights.length > 0 ? ` (${sessionHighlights.length})` : ""}
              </CardTitle>
            </div>
            {playback.status === "live" ? <Badge tone="ok">Temps réel</Badge> : null}
          </div>
          {sessionHighlights.length === 0 ? (
            <p className="mt-4 text-sm text-ink-400">
              Les moments forts apparaîtront ici pendant votre live.
            </p>
          ) : (
            <ul className="mt-4 max-h-80 space-y-2 overflow-y-auto">
              {sessionHighlights.map((h) => (
                <li
                  key={h.id}
                  className="rounded-xl border border-white/5 bg-ink-950/50 px-3 py-2.5"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-white">{h.title}</p>
                    <Badge tone="brand">score {Math.round(h.score * 100)}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-ink-500">
                    {Math.round(h.start_ms / 1000)}s → {Math.round(h.end_ms / 1000)}s ·{" "}
                    {formatDateTime(h.created_at, timeZone)}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-4 text-xs text-ink-500">
            <Link href="/highlights" className="text-brand-300 hover:text-brand-200">
              Ouvrir la galerie highlights
            </Link>
          </p>
        </Card>
      ) : null}
    </div>
  );
}
