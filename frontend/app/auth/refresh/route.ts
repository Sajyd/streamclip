import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { NextRequest } from "next/server";

import { api } from "@/lib/api";
import { clearSession, rotateSession, safeNextPath } from "@/lib/session";
import type { Me } from "@/types/api";

/**
 * Renews an expired session, then returns to the page that asked for it.
 *
 * Page rendering cannot write cookies, so a page that finds its access token
 * missing or refused redirects here. The new token is checked before going
 * back: if the API still refuses it, the visitor is signed out instead of
 * bouncing between the page and this route.
 */
const UNAVAILABLE = "/service-indisponible";

export async function GET(request: NextRequest) {
  const next = safeNextPath(request.nextUrl.searchParams.get("next"));
  const signIn = (reason: string) =>
    `/login?reason=${reason}&next=${encodeURIComponent(next)}`;

  const rotation = await rotateSession();
  if (!rotation.ok) {
    if (rotation.reason === "unavailable") {
      // The session cookies are kept. Not the sign-in page: it would send a
      // visitor who still has cookies straight back here.
      redirect(UNAVAILABLE);
    }
    redirect(signIn(rotation.reason === "suspended" ? "suspended" : "expired"));
  }

  const check = await api<Me>("/me", { token: rotation.token });
  if (!check.ok) {
    if (check.error.status === 401 || check.error.status === 403) {
      clearSession(await cookies());
      redirect(signIn(check.error.status === 403 ? "suspended" : "expired"));
    }
    redirect(UNAVAILABLE);
  }
  redirect(next);
}
