import type { Metadata } from "next";
import { Suspense } from "react";

import {
  getLiveHighlightsAction,
  getLivePlaybackAction,
} from "@/app/actions/live";
import { LiveMonitor } from "@/components/app/live-monitor";
import { ButtonLink } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { getHighlights, getLivePlayback, requireSession } from "@/lib/dal";

export const metadata: Metadata = { title: "Live" };

const PATH = "/live";

async function LiveContent() {
  const { token, me } = await requireSession(PATH);
  if (!me.capabilities.ingest_keys) {
    return (
      <p className="text-sm text-ink-300">
        L&apos;aperçu live n&apos;est pas disponible sur cet environnement.
      </p>
    );
  }
  const [playback, highlights] = await Promise.all([
    getLivePlayback(token, PATH),
    getHighlights(token, PATH),
  ]);
  const scoped = playback.session_id
    ? highlights.filter((h) => h.stream_session_id === playback.session_id)
    : highlights;

  return (
    <LiveMonitor
      initialPlayback={playback}
      initialHighlights={scoped}
      hlsBase="/live/stream"
      refreshPlayback={getLivePlaybackAction}
      refreshHighlights={getLiveHighlightsAction}
      timeZone={me.user.timezone}
    />
  );
}

export default function LivePage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Live</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Suivi en direct
          </h1>
          <p className="mt-1.5 text-sm text-ink-300">
            Visualisez votre diffusion et les moments forts détectés en temps réel.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/guide" variant="secondary" size="sm">
            Guide
          </ButtonLink>
          <ButtonLink href="/highlights" variant="secondary" size="sm">
            Highlights
          </ButtonLink>
        </div>
      </div>
      <Suspense
        fallback={
          <div className="space-y-4" aria-busy aria-label="Chargement du live">
            <Skeleton className="aspect-video rounded-2xl" />
            <Skeleton className="h-40 rounded-3xl" />
          </div>
        }
      >
        <LiveContent />
      </Suspense>
    </div>
  );
}
