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
};

export function LivePlayer({ src, status, message, className }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [needsGesture, setNeedsGesture] = useState(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !src || status !== "live") {
      setPlaying(false);
      setNeedsGesture(false);
      hlsRef.current?.destroy();
      hlsRef.current = null;
      return;
    }

    setError(null);
    setNeedsGesture(false);
    let cancelled = false;
    let hls: Hls | null = null;

    const tryPlay = async () => {
      if (!video || cancelled) return;
      try {
        video.muted = true;
        await video.play();
        if (!cancelled) {
          setPlaying(true);
          setNeedsGesture(false);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setNeedsGesture(true);
          setPlaying(false);
        }
      }
    };

    const onFatal = (msg: string) => {
      if (!cancelled) {
        setError(msg);
        setPlaying(false);
      }
    };

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      void tryPlay();
    } else if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        liveSyncDurationCount: 3,
      });
      hlsRef.current = hls;
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        void tryPlay();
      });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          hls?.startLoad();
          return;
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
    try {
      video.muted = true;
      await video.play();
      setPlaying(true);
      setNeedsGesture(false);
      setError(null);
    } catch {
      setNeedsGesture(true);
    }
  }

  const live = status === "live";
  const showOverlay = !live || Boolean(error) || needsGesture;

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
        {showOverlay ? (
          <button
            type="button"
            className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-ink-950/80 px-6 text-center"
            onClick={() => {
              if (live && !error) void startPlayback();
            }}
            disabled={!live || Boolean(error)}
          >
            {needsGesture && live && !error ? (
              <>
                <span className="flex size-14 items-center justify-center rounded-full bg-white/15 text-2xl text-white">
                  ▶
                </span>
                <p className="text-sm text-ink-200">Appuyez pour lancer l&apos;aperçu</p>
              </>
            ) : (
              <p className="text-sm text-ink-300">
                {error ||
                  message ||
                  (live ? "Chargement de l'aperçu…" : "En attente de votre diffusion…")}
              </p>
            )}
          </button>
        ) : null}
      </div>
    </div>
  );
}
