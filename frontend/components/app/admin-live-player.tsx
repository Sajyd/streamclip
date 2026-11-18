"use client";

import { useEffect, useState } from "react";

import { LivePlayer } from "@/components/app/live-player";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import type { LivePlayback } from "@/types/api";

async function fetchAdminPlayback(liveId: string, signal?: AbortSignal): Promise<LivePlayback> {
  try {
    const res = await fetch(`/api/live/admin/${encodeURIComponent(liveId)}/playback`, {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) {
      return {
        status: "offline",
        session_id: liveId,
        public_id: null,
        title: null,
        rtmp_url: null,
        preview_available: false,
        message: res.status === 401 ? "Session expirée" : "Aperçu indisponible",
        stream_key_hint: null,
        preview_token: null,
      };
    }
    return (await res.json()) as LivePlayback;
  } catch {
    return {
      status: "offline",
      session_id: liveId,
      public_id: null,
      title: null,
      rtmp_url: null,
      preview_available: false,
      message: "Aperçu indisponible",
      stream_key_hint: null,
      preview_token: null,
    };
  }
}

type Props = {
  liveId: string;
  initial: LivePlayback | null;
  streamKeyPublicId: string | null;
  streamKeyHint: string | null;
  rtmpUrl: string | null;
};

export function AdminLivePlayer({
  liveId,
  initial,
  streamKeyPublicId,
  streamKeyHint,
  rtmpUrl,
}: Props) {
  const [playback, setPlayback] = useState<LivePlayback>(
    initial ?? {
      status: "offline",
      session_id: liveId,
      public_id: streamKeyPublicId,
      title: null,
      rtmp_url: rtmpUrl,
      preview_available: false,
      message: "Chargement de l'aperçu…",
      stream_key_hint: streamKeyHint,
      preview_token: null,
    },
  );

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      const next = await fetchAdminPlayback(liveId, controller.signal);
      if (!cancelled) setPlayback(next);
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 5000);
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
  }, [liveId]);

  const src =
    playback.preview_available && playback.status === "live"
      ? `/admin/lives/${liveId}/stream/index.m3u8`
      : null;

  const host = playback.rtmp_url ?? rtmpUrl;
  const publicId = playback.public_id ?? streamKeyPublicId;

  return (
    <Card className="space-y-4 p-5">
      <div>
        <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Aperçu live</p>
        <CardTitle className="mt-2">Lecteur du live</CardTitle>
        <CardDescription>
          Prévisualisation via session staff
          {publicId ? (
            <>
              {" "}
              · flux <span className="font-mono text-ink-200">{publicId}</span>
              {streamKeyHint ? (
                <span className="font-mono text-ink-500"> (…{streamKeyHint})</span>
              ) : null}
            </>
          ) : null}
          {host ? (
            <>
              {" "}
              · <span className="font-mono text-ink-400">{host}</span>
            </>
          ) : null}
          .
        </CardDescription>
      </div>
      <LivePlayer
        src={src}
        status={playback.status}
        message={
          playback.status === "live"
            ? "Live en cours."
            : playback.message || "Aucun live en cours."
        }
      />
    </Card>
  );
}
