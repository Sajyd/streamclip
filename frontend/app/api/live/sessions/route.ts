import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { accessTokenForMutation } from "@/lib/session";
import type { StreamSession } from "@/types/api";

/** Client poll endpoint — avoids Server Actions so navbar Links stay responsive. */
export async function GET() {
  const token = await accessTokenForMutation();
  if (!token) {
    return NextResponse.json({ items: [] as StreamSession[] }, { status: 401 });
  }
  const result = await api<{ items: StreamSession[] }>("/ingest/sessions", { token });
  if (!result.ok) {
    return NextResponse.json({ items: [] as StreamSession[] });
  }
  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
