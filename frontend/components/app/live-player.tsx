"use client";

import Hls from "hls.js";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/primitives";
import { cx } from "@/lib/format";

type Props = {
  /** Same-origin playlist, e.g. `/live/stream/index.m3u8`. */
  src: string | null;
  status: string;
  message?: string;
  className?: string;
  /** Stretch to fill the grid cell (dashboard). */
  fill?: boolean;
};

export function LivePlayer({ src, status, message, className, fill = false }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [needsGesture, setNeedsGesture] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    const canPreview = status === "live" || status === "starting";
    if (!video || !src || !canPreview) {
      setPlaying(false);
      setNeedsGesture(false);
      setLoading(false);
      hlsRef.current?.destroy();
      hlsRef.current = null;
      return;
    }

    setError(null);
    setNeedsGesture(false);
    setLoading(true);
    let cancelled = false;
    let hls: Hls | null = null;
    let networkRetries = 0;

    const tryPlay = async () => {
      if (!video || cancelled) return;
      try {
        video.muted = true;
        video.defaultMuted = true;
        await video.play();
        if (!cancelled) {
          setPlaying(true);
          setNeedsGesture(false);
          setError(null);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setNeedsGesture(true);
          setPlaying(false);
          setLoading(false);
        }
      }
    };

    const onFatal = (msg: string) => {
      if (!cancelled) {
        setError(msg);
        setPlaying(false);
        setLoading(false);
        setNeedsGesture(false);
      }
    };

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      video.addEventListener("loadedmetadata", () => void tryPlay(), { once: true });
      video.addEventListener(
        "error",
        () => onFatal("Aperçu indisponible pour le moment."),
        { once: true },
      );
    } else if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        liveSyncDurationCount: 3,
        // Manifest may appear a few seconds after going live.
        manifestLoadingMaxRetry: 6,
        manifestLoadingRetryDelay: 1500,
        levelLoadingMaxRetry: 6,
        fragLoadingMaxRetry: 6,
      });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        networkRetries = 0;
        void tryPlay();
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          networkRetries += 1;
          if (networkRetries <= 8) {
            window.setTimeout(() => hls?.startLoad(), 1000);
            return;
          }
          onFatal("Aperçu indisponible — réessayez dans un instant.");
          hls?.destroy();
          hlsRef.current = null;
          return;
        }
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          try {
            hls?.recoverMediaError();
            return;
          } catch {
            // fall through
          }
        }
        onFatal("Aperçu indisponible pour le moment.");
        hls?.destroy();
        hlsRef.current = null;
      });
    } else {
      onFatal("Lecture non supportée sur ce navigateur.");
    }

    return () => {
      cancelled = true;
      hls?.destroy();
      hlsRef.current = null;
      video.removeAttribute("src");
      video.load();
    };
  }, [src, status]);

  async function startPlayback() {
    const video = videoRef.current;
    if (!video) return;
    // If HLS never attached (src arrived late), remount is handled by effect.
    try {
      video.muted = true;
      video.defaultMuted = true;
      await video.play();
      setPlaying(true);
      setNeedsGesture(false);
      setError(null);
      setLoading(false);
    } catch {
      setNeedsGesture(true);
    }
  }

  const isLive = status === "live";
  const canPreview = isLive || status === "starting";
  const showOverlay =
    !canPreview || Boolean(error) || needsGesture || (loading && !playing);

  return (
    <div
      className={cx(
        "overflow-hidden rounded-2xl border border-white/10 bg-ink-950",
        fill ? "relative h-full min-h-[22rem]" : null,
        className,
      )}
    >
      <div className={cx("relative bg-black", fill ? "absolute inset-0" : "aspect-video")}>
        <video
          ref={videoRef}
          className="size-full object-contain"
          controls
          playsInline
          muted
          autoPlay
          preload="auto"
        />
        <div className="pointer-events-none absolute top-3 left-3 z-10 flex items-center gap-2">
          {isLive ? (
            <Badge tone="danger">
              <span className="mr-1.5 inline-block size-1.5 animate-pulse rounded-full bg-danger-400" />
              EN DIRECT
            </Badge>
          ) : status === "starting" ? (
            <Badge tone="warn">Démarrage…</Badge>
          ) : (
            <Badge tone="neutral">Hors ligne</Badge>
          )}
        </div>
        {showOverlay ? (
          <button
            type="button"
            className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-ink-950/80 px-6 text-center"
            onClick={() => {
              if (canPreview && !error) void startPlayback();
            }}
            disabled={!canPreview || Boolean(error)}
          >
            {needsGesture && canPreview && !error ? (
              <>
                <span className="flex size-14 items-center justify-center rounded-full bg-white/15 text-2xl text-white">
                  ▶
                </span>
                <p className="text-sm text-ink-200">Appuyez pour lancer l&apos;aperçu</p>
              </>
            ) : (
              <p className="text-sm text-ink-300">
                {error ||
                  (loading && canPreview
                    ? "Chargement de l'aperçu…"
                    : message ||
                      (canPreview
                        ? "Chargement de l'aperçu…"
                        : "En attente de votre diffusion…"))}
              </p>
            )}
          </button>
        ) : null}
      </div>
    </div>
  );
}
