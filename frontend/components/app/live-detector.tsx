"use client";

import { useEffect, useRef, useState } from "react";

import { saveOnboardingAction } from "@/app/actions/onboarding";
import { Badge } from "@/components/ui/primitives";
import { fetchIngestSessions } from "@/lib/live-poll";
import type { StreamSession } from "@/types/api";

const LIVE_STATUSES = new Set(["pending", "live"]);

function findLive(sessions: StreamSession[]) {
  return sessions.find((session) => LIVE_STATUSES.has(session.status));
}

export function LiveDetector({
  sessions: initialSessions,
  onDetected,
  pollMs = 4000,
}: {
  sessions: StreamSession[];
  onDetected?: () => void;
  pollMs?: number;
}) {
  const [sessions, setSessions] = useState(initialSessions);
  const announced = useRef(false);
  const live = findLive(sessions);

  useEffect(() => {
    setSessions(initialSessions);
  }, [initialSessions]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const next = await fetchIngestSessions(controller.signal);
        if (!cancelled) setSessions(next);
      } catch {
        // Keep last known state on transient failures.
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), pollMs);
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
  }, [pollMs]);

  useEffect(() => {
    if (!live || announced.current) return;
    announced.current = true;
    void saveOnboardingAction({ live_detected: true, step: "live" }).then(() => {
      onDetected?.();
    });
  }, [live, onDetected]);

  if (live) {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-ok-500/40 bg-ok-500/10 px-4 py-3.5">
        <span className="relative flex size-3">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok-400 opacity-60" />
          <span className="relative inline-flex size-3 rounded-full bg-ok-400" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ok-400">Live détecté</p>
          <p className="text-sm text-ink-200">
            STREAMCLIP reçoit votre signal. Vous pouvez laisser tourner — les clips apparaîtront ici
            dès qu&apos;ils sont prêts.
          </p>
        </div>
        <Badge tone="ok">En direct</Badge>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 rounded-2xl border border-brand-500/30 bg-brand-500/10 px-4 py-3.5">
      <span className="size-3 shrink-0 animate-pulse rounded-full bg-brand-400" />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-brand-200">En attente de votre live</p>
        <p className="text-sm text-ink-200">
          Démarrez la diffusion dans OBS ou Streamlabs. La détection est automatique — rien à
          cliquer.
        </p>
      </div>
    </div>
  );
}
