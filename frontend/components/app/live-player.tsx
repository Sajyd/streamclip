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
    let retryTimer = 0;
    let attempt = 0;

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

    const scheduleRetry = () => {
      attempt += 1;
      if (attempt > 40) {
        onFatal("Aperçu indisponible — réessayez dans un instant.");
        return;
      }
      window.clearTimeout(retryTimer);
      retryTimer = window.setTimeout(() => {
        if (!cancelled) attach();
      }, 1500);
    };

    let clearNative = () => {};

    const attach = () => {
      if (!video || cancelled) return;
      clearNative();
      hls?.destroy();
      hls = null;
      hlsRef.current = null;
      video.removeAttribute("src");
      setError(null);
      setLoading(true);

      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        const onReady = () => void tryPlay();
        const onError = () => scheduleRetry();
        video.addEventListener("loadedmetadata", onReady);
        video.addEventListener("error", onError);
        clearNative = () => {
          video.removeEventListener("loadedmetadata", onReady);
          video.removeEventListener("error", onError);
        };
        video.src = src;
        return;
      }
      if (!Hls.isSupported()) {
        onFatal("Lecture non supportée sur ce navigateur.");
        return;
      }
      hls = new Hls({
        // Blob workers are blocked by the page CSP; demux on the main thread.
        enableWorker: false,
        lowLatencyMode: true,
        liveSyncDurationCount: 3,
        manifestLoadingMaxRetry: 4,
        manifestLoadingRetryDelay: 1000,
        levelLoadingMaxRetry: 4,
        fragLoadingMaxRetry: 4,
        xhrSetup: (xhr) => {
          xhr.withCredentials = true;
        },
      });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        attempt = 0;
        void tryPlay();
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal || cancelled) return;
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          try {
            hls?.recoverMediaError();
            return;
          } catch {
            // Reattach below.
          }
        }
        hls?.destroy();
        hls = null;
        hlsRef.current = null;
        scheduleRetry();
      });
    };

    attach();

    return () => {
      cancelled = true;
      window.clearTimeout(retryTimer);
      clearNative();
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
        "relative isolate z-0 overflow-hidden rounded-2xl border border-white/10 bg-ink-950 [contain:paint]",
        fill ? "min-h-[16rem]" : null,
        className,
      )}
    >
      <div className="relative aspect-video bg-black">
        <video
          ref={videoRef}
          className="absolute inset-0 size-full object-contain"
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
          <div className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-ink-950/75 px-6 text-center">
            {needsGesture && canPreview && !error ? (
              <button
                type="button"
                className="pointer-events-auto flex flex-col items-center gap-3"
                onClick={() => void startPlayback()}
              >
                <span className="flex size-14 items-center justify-center rounded-full bg-white/15 text-2xl text-white">
                  ▶
                </span>
                <p className="text-sm text-ink-200">Appuyez pour lancer l&apos;aperçu</p>
              </button>
            ) : (
              <p className="text-sm text-ink-300">
                {error ||
                  (loading && canPreview
                    ? "Connexion à l'aperçu…"
                    : message ||
                      (canPreview
                        ? "Connexion à l'aperçu…"
                        : "En attente de votre diffusion…"))}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
