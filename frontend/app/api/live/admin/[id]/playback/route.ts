import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { accessTokenForMutation } from "@/lib/session";
import type { LivePlayback } from "@/types/api";

type Props = { params: Promise<{ id: string }> };

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

/** Admin live playback poll — Route Handler so nav Links stay responsive. */
export async function GET(_request: Request, { params }: Props) {
  const { id } = await params;
  const token = await accessTokenForMutation();
  if (!token) {
    return NextResponse.json(offline("Session expirée"), { status: 401 });
  }
  const result = await api<LivePlayback>(`/admin/lives/${id}/playback`, { token });
  if (!result.ok) {
    return NextResponse.json(offline(result.error.message));
  }
  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
