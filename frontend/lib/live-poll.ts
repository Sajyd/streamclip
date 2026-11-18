import type { Highlight, LivePlayback, StreamSession } from "@/types/api";

function offline(message: string): LivePlayback {
  return {
    status: "offline",
    session_id: null,
    public_id: null,
    title: null,
    rtmp_url: null,
    preview_available: false,
    message,
    stream_key_hint: null,
    preview_token: null,
  };
}

/** Browser fetch polls — do not use Server Actions (they block App Router navigations). */
export async function fetchLivePlayback(signal?: AbortSignal): Promise<LivePlayback> {
  try {
    const res = await fetch("/api/live/playback", {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) {
      return offline(res.status === 401 ? "Session expirée" : "Aperçu indisponible");
    }
    return (await res.json()) as LivePlayback;
  } catch {
    return offline("Aperçu indisponible");
  }
}

export async function fetchIngestSessions(signal?: AbortSignal): Promise<StreamSession[]> {
  try {
    const res = await fetch("/api/live/sessions", {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) return [];
    const data = (await res.json()) as { items: StreamSession[] };
    return data.items ?? [];
  } catch {
    return [];
  }
}

export async function fetchLiveHighlights(
  sessionId: string | null,
  signal?: AbortSignal,
): Promise<Highlight[]> {
  try {
    const query = sessionId ? `?stream_session_id=${encodeURIComponent(sessionId)}` : "";
    const res = await fetch(`/api/live/highlights${query}`, {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) return [];
    const data = (await res.json()) as { items: Highlight[] };
    return data.items ?? [];
  } catch {
    return [];
  }
}
