import { NextResponse } from "next/server";

import { api } from "@/lib/api";
import { accessTokenForMutation } from "@/lib/session";
import type { NotificationList } from "@/types/api";

/** Client poll endpoint — avoids Server Actions so navbar Links stay responsive. */
export async function GET() {
  const token = await accessTokenForMutation();
  if (!token) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const result = await api<NotificationList>("/notifications", { token });
  if (!result.ok) {
    return NextResponse.json({ error: result.error.code }, { status: result.error.status });
  }
  return NextResponse.json(result.data, {
    headers: { "Cache-Control": "no-store" },
  });
}
