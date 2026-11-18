import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { accessTokenForMutation } from "@/lib/session";
import type { Highlight } from "@/types/api";

/** Client poll endpoint — avoids Server Actions so navbar Links stay responsive. */
export async function GET(request: Request) {
  const token = await accessTokenForMutation();
  if (!token) {
    return NextResponse.json({ items: [] as Highlight[] }, { status: 401 });
  }
  const { searchParams } = new URL(request.url);
  const sessionId = searchParams.get("stream_session_id");
  const query = sessionId ? `?stream_session_id=${encodeURIComponent(sessionId)}` : "";
  const result = await api<{ items: Highlight[] }>(`/highlights${query}`, { token });
  if (!result.ok) {
    return NextResponse.json({ items: [] as Highlight[] });
  }
  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
