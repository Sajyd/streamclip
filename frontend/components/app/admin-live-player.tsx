"use client";

import { useEffect, useState } from "react";

import { getAdminLivePlaybackAction } from "@/app/actions/live";
import { LivePlayer } from "@/components/app/live-player";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import type { LivePlayback } from "@/types/api";

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
    const tick = async () => {
      const next = await getAdminLivePlaybackAction(liveId);
      if (!cancelled) setPlayback(next);
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [liveId]);

  const src =
    playback.preview_available && playback.status === "live"
      ? `/admin/lives/${liveId}/stream/index.m3u8`
      : null;

  return (
    <Card className="space-y-4 p-5">
      <div>
        <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Aperçu live</p>
        <CardTitle className="mt-2">Lecteur du live</CardTitle>
        <CardDescription>
          Prévisualisation HLS de l&apos;instance dédiée — authentifiée par votre session staff,
          sans clé secrète OBS.
          {streamKeyPublicId ? (
            <>
              {" "}
              Flux <span className="font-mono text-ink-200">{streamKeyPublicId}</span>
              {streamKeyHint ? (
                <span className="font-mono text-ink-500"> (…{streamKeyHint})</span>
              ) : null}
              .
            </>
          ) : null}
        </CardDescription>
      </div>
      <LivePlayer
        src={src}
        status={playback.status}
        message={playback.message}
        rtmpUrl={playback.rtmp_url ?? rtmpUrl}
        publicId={playback.public_id ?? streamKeyPublicId}
      />
    </Card>
  );
}
