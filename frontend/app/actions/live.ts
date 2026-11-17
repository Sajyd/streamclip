"use server";

import { api } from "@/lib/api";
import { readSession } from "@/lib/session";
import type { Highlight, LivePlayback } from "@/types/api";

export async function getLivePlaybackAction(): Promise<LivePlayback> {
  const { access } = await readSession();
  if (!access) {
    return offline("Session expirée");
  }
  const result = await api<LivePlayback>("/ingest/playback", { token: access });
  if (!result.ok) {
    return offline(result.error.message);
  }
  return result.data;
}

export async function getLiveHighlightsAction(
  sessionId: string | null,
): Promise<Highlight[]> {
  const { access } = await readSession();
  if (!access) return [];
  const query = sessionId ? `?stream_session_id=${encodeURIComponent(sessionId)}` : "";
  const result = await api<{ items: Highlight[] }>(`/highlights${query}`, { token: access });
  if (!result.ok) return [];
  return result.data.items;
}

export async function getAdminLivePlaybackAction(liveId: string): Promise<LivePlayback> {
  const { access } = await readSession();
  if (!access) {
    return offline("Session expirée");
  }
  const result = await api<LivePlayback>(`/admin/lives/${liveId}/playback`, { token: access });
  if (!result.ok) {
    return offline(result.error.message);
  }
  return result.data;
}

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
