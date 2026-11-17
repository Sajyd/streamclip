"use client";

import Hls from "hls.js";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/primitives";
import { cx } from "@/lib/format";

type Props = {
  /** Same-origin HLS playlist, e.g. `/live/stream/index.m3u8`. */
  src: string | null;
  status: string;
  message?: string;
  rtmpUrl?: string | null;
  publicId?: string | null;
  className?: string;
  compact?: boolean;
};

export function LivePlayer({
  src,
  status,
  message,
  rtmpUrl,
  publicId,
  className,
  compact = false,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src || status !== "live") {
      setPlaying(false);
      return;
    }
    setError(null);
    let hls: Hls | null = null;
    let cancelled = false;

    const onError = (msg: string) => {
      if (!cancelled) setError(msg);
    };

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      void video.play().then(() => setPlaying(true)).catch(() => {
        onError("Lecture bloquée — cliquez pour démarrer.");
      });
    } else if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        liveSyncDurationCount: 3,
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        void video.play().then(() => setPlaying(true)).catch(() => {
          onError("Lecture bloquée — cliquez pour démarrer.");
        });
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          hls?.startLoad();
          return;
        }
        onError("Flux indisponible pour le moment.");
        hls?.destroy();
      });
    } else {
      onError("Votre navigateur ne prend pas en charge la lecture HLS.");
    }

    return () => {
      cancelled = true;
      hls?.destroy();
      video.removeAttribute("src");
      video.load();
    };
  }, [src, status]);

  const live = status === "live";

  return (
    <div className={cx("overflow-hidden rounded-2xl border border-white/10 bg-ink-950", className)}>
      <div className="relative aspect-video bg-black">
        <video
          ref={videoRef}
          className="size-full object-contain"
          controls
          playsInline
          muted
          autoPlay
          onClick={() => {
            const video = videoRef.current;
            if (video && video.paused) {
              void video.play().then(() => {
                setPlaying(true);
                setError(null);
              });
            }
          }}
        />
        <div className="pointer-events-none absolute top-3 left-3 flex items-center gap-2">
          {live ? (
            <Badge tone="danger">
              <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-danger-400" />
              EN DIRECT
            </Badge>
          ) : status === "starting" ? (
            <Badge tone="warn">Démarrage…</Badge>
          ) : (
            <Badge tone="neutral">Hors ligne</Badge>
          )}
          {playing ? <Badge tone="ok">Aperçu</Badge> : null}
        </div>
        {!live || error ? (
          <div className="absolute inset-0 flex items-center justify-center bg-ink-950/80 px-6 text-center">
            <p className="text-sm text-ink-300">
              {error || message || "En attente du signal RTMP…"}
            </p>
          </div>
        ) : null}
      </div>
      {!compact && rtmpUrl ? (
        <div className="space-y-1 border-t border-white/5 px-4 py-3 font-mono text-xs text-ink-400">
          <p>
            <span className="text-ink-500">Serveur RTMP </span>
            {rtmpUrl}
            {publicId ? <span className="text-ink-600"> · path live/{publicId}</span> : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
