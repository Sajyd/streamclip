"use client";

import { Player } from "@remotion/player";
import { useEffect, useMemo, useState } from "react";

import { ViralHighlight, COMPOSITION } from "@/remotion/ViralHighlight";
import type { Highlight } from "@/types/api";
import { buttonClasses } from "@/components/ui/button";
import { Badge, Card, CardDescription, CardTitle } from "@/components/ui/primitives";

type Props = {
  highlight: Highlight;
  mediaUrlAction: (id: string) => Promise<{ url?: string; error?: string }>;
};

export function HighlightPlayer({ highlight, mediaUrlAction }: Props) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const durationInFrames = useMemo(() => {
    const ms = Math.max(1000, highlight.relative_end_ms - highlight.relative_start_ms);
    return Math.round((ms / 1000) * COMPOSITION.fps);
  }, [highlight.relative_end_ms, highlight.relative_start_ms]);

  async function loadMedia() {
    setLoading(true);
    setError(null);
    const result = await mediaUrlAction(highlight.id);
    setLoading(false);
    if (result.error || !result.url) {
      setError(result.error || "Extrait indisponible");
      return;
    }
    setSrc(result.url);
  }

  useEffect(() => {
    if (highlight.media_available && !src) {
      void loadMedia();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once per highlight
  }, [highlight.id]);

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">
            Score {Math.round(highlight.score * 100)}
          </p>
          <CardTitle className="mt-2 truncate">{highlight.title}</CardTitle>
          <CardDescription className="mt-1 line-clamp-2">{highlight.description}</CardDescription>
          {highlight.hashtags.length > 0 ? (
            <p className="mt-2 text-xs text-brand-300">{highlight.hashtags.join(" ")}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone="brand">{highlight.category}</Badge>
          {highlight.camera.detected ? <Badge tone="neutral">Cam streamer</Badge> : null}
        </div>
      </div>

      <div className="mt-5 overflow-hidden rounded-2xl bg-black">
        {src ? (
          <Player
            component={ViralHighlight}
            inputProps={{
              src,
              relativeStartMs: highlight.relative_start_ms,
              relativeEndMs: highlight.relative_end_ms,
              words: highlight.words,
              camera: highlight.camera,
              title: highlight.title,
            }}
            durationInFrames={durationInFrames}
            compositionWidth={COMPOSITION.width}
            compositionHeight={COMPOSITION.height}
            fps={COMPOSITION.fps}
            style={{ width: "100%", aspectRatio: "9 / 16", maxHeight: 560 }}
            controls
            loop
          />
        ) : (
          <div className="flex aspect-[9/16] max-h-[560px] items-center justify-center bg-ink-950">
            {highlight.media_available ? (
              <button
                type="button"
                className={buttonClasses({ variant: "secondary", size: "sm" })}
                disabled={loading}
                onClick={() => void loadMedia()}
              >
                {loading ? "Chargement…" : "Charger l’extrait"}
              </button>
            ) : (
              <p className="text-sm text-ink-400">Extrait 1080p bientôt disponible</p>
            )}
          </div>
        )}
      </div>
      {error ? <p className="mt-2 text-xs text-danger-400">{error}</p> : null}
    </Card>
  );
}
