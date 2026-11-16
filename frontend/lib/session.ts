import "server-only";

import { cookies } from "next/headers";

import { api } from "@/lib/api";
import type { Tokens } from "@/types/api";

/**
 * Session cookies.
 *
 * Tokens issued by the API live in two HttpOnly cookies that page scripts
 * cannot read. The access token is short-lived; its cookie expires slightly
 * before the token does, so "no access cookie" simply means "refresh first".
 * Cookies can only be written from Server Actions and Route Handlers: page
 * rendering never refreshes a session itself (see app/auth/refresh).
 */

const secure = process.env.NODE_ENV === "production";
// The __Host- prefix makes browsers refuse the cookie unless it is Secure,
// host-only and scoped to "/": it cannot be planted from a sibling subdomain.
const ACCESS_COOKIE = secure ? "__Host-sc_access" : "sc_access";
const REFRESH_COOKIE = secure ? "__Host-sc_refresh" : "sc_refresh";
const ACCESS_EXPIRY_MARGIN_MS = 30_000;

type CookieStore = Awaited<ReturnType<typeof cookies>>;

const baseOptions = { httpOnly: true, secure, sameSite: "lax", path: "/" } as const;

export function writeSession(store: CookieStore, tokens: Tokens): void {
  store.set(ACCESS_COOKIE, tokens.access_token, {
    ...baseOptions,
    expires: new Date(new Date(tokens.access_expires_at).getTime() - ACCESS_EXPIRY_MARGIN_MS),
  });
  store.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...baseOptions,
    expires: new Date(tokens.refresh_expires_at),
  });
}

export function clearSession(store: CookieStore): void {
  store.set(ACCESS_COOKIE, "", { ...baseOptions, maxAge: 0 });
  store.set(REFRESH_COOKIE, "", { ...baseOptions, maxAge: 0 });
}

export async function readSession(): Promise<{ access: string | null; refresh: string | null }> {
  const store = await cookies();
  return {
    access: store.get(ACCESS_COOKIE)?.value || null,
    refresh: store.get(REFRESH_COOKIE)?.value || null,
  };
}

export type RotationResult =
  | { ok: true; token: string }
  // missing: no refresh cookie. rejected: expired, revoked or reused token.
  // suspended: the account is suspended. unavailable: transient API failure.
  | { ok: false; reason: "missing" | "rejected" | "suspended" | "unavailable" };

/**
 * Exchange the refresh token for a new pair and store it.
 * Only callable where cookies can be written (Server Action, Route Handler).
 */
export async function rotateSession(): Promise<RotationResult> {
  const store = await cookies();
  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (!refresh) {
    return { ok: false, reason: "missing" };
  }
  const result = await api<Tokens>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refresh },
  });
  if (result.ok) {
    writeSession(store, result.data);
    return { ok: true, token: result.data.access_token };
  }
  if (result.error.status === 401 || result.error.status === 403) {
    clearSession(store);
    return { ok: false, reason: result.error.status === 403 ? "suspended" : "rejected" };
  }
  // Transient failure: the cookies are kept, the session may still be valid.
  return { ok: false, reason: "unavailable" };
}

/** Access token for a Server Action or Route Handler, refreshed if needed. */
export async function accessTokenForMutation(): Promise<string | null> {
  const { access } = await readSession();
  if (access) {
    return access;
  }
  const rotation = await rotateSession();
  return rotation.ok ? rotation.token : null;
}

/** Only same-origin paths are accepted as post-login destinations. */
export function safeNextPath(value: unknown, fallback = "/dashboard"): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return fallback;
  }
  if (value.includes("\\") || value.includes("\n") || value.includes("\r")) {
    return fallback;
  }
  return value;
}
