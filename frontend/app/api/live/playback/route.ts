import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { accessTokenForMutation } from "@/lib/session";
import type { LivePlayback } from "@/types/api";

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

/** Client poll endpoint — avoids Server Actions so navbar Links stay responsive. */
export async function GET() {
  const token = await accessTokenForMutation();
  if (!token) {
    return NextResponse.json(offline("Session expirée"), { status: 401 });
  }
  const result = await api<LivePlayback>("/ingest/playback", { token });
  if (!result.ok) {
    return NextResponse.json(offline(result.error.message));
  }
  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
