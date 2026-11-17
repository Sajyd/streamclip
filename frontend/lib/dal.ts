import "server-only";

import { cacheLife } from "next/cache";
import { redirect } from "next/navigation";
import { cache } from "react";

import { api, type ApiResult } from "@/lib/api";
import { readSession } from "@/lib/session";
import type {
  AuthSession,
  BillingOverview,
  Clip,
  DataExport,
  Me,
  Meta,
  NotificationList,
  Onboarding,
  PlanCatalog,
  SocialAccountList,
  StreamKey,
  StreamSession,
} from "@/types/api";

/**
 * Data access layer for page rendering.
 *
 * Every read goes through the session resolved here, and the API re-checks
 * the token, the session and the tenant on each call: nothing is authorised
 * by the web application alone.
 */

export type SessionState =
  | { status: "authenticated"; token: string; me: Me }
  // The access token is missing or refused but a refresh token exists.
  | { status: "expired" }
  | { status: "anonymous" }
  | { status: "unavailable" };

/** Resolved once per request, however many components ask for it. */
export const loadSession = cache(async (): Promise<SessionState> => {
  const { access, refresh } = await readSession();
  if (!access) {
    return refresh ? { status: "expired" } : { status: "anonymous" };
  }
  const result = await api<Me>("/me", { token: access });
  if (result.ok) {
    return { status: "authenticated", token: access, me: result.data };
  }
  if (result.error.status === 401 || result.error.status === 403) {
    // The refresh route decides: new tokens, or cookies cleared and sign-in.
    return refresh ? { status: "expired" } : { status: "anonymous" };
  }
  return { status: "unavailable" };
});

export class ServiceUnavailableError extends Error {
  constructor() {
    super("The API is unavailable");
    this.name = "ServiceUnavailableError";
  }
}

/**
 * Session required to render a page. `next` is the page's own path: rendering
 * cannot write cookies, so an expired session takes a detour through the
 * refresh route and comes back.
 */
export async function requireSession(next: string): Promise<{ token: string; me: Me }> {
  const session = await loadSession();
  switch (session.status) {
    case "authenticated":
      return session;
    case "expired":
      redirect(`/auth/refresh?next=${encodeURIComponent(next)}`);
    case "unavailable":
      throw new ServiceUnavailableError();
    case "anonymous":
      redirect(`/login?next=${encodeURIComponent(next)}`);
  }
}

function unwrap<T>(result: ApiResult<T>, next: string): T {
  if (result.ok) {
    return result.data;
  }
  if (result.error.status === 401) {
    redirect(`/auth/refresh?next=${encodeURIComponent(next)}`);
  }
  throw new ServiceUnavailableError();
}

export async function getBillingOverview(token: string, next: string): Promise<BillingOverview> {
  return unwrap(await api<BillingOverview>("/billing/overview", { token }), next);
}

export async function getNotifications(token: string, next: string): Promise<NotificationList> {
  return unwrap(await api<NotificationList>("/notifications", { token }), next);
}

export async function getAuthSessions(token: string, next: string): Promise<AuthSession[]> {
  return unwrap(await api<AuthSession[]>("/auth/sessions", { token }), next);
}

export async function getDataExports(token: string, next: string): Promise<DataExport[]> {
  return unwrap(await api<{ items: DataExport[] }>("/account/exports", { token }), next).items;
}

export async function getIngestKey(token: string, next: string): Promise<StreamKey | null> {
  const result = await api<StreamKey>("/ingest/key", { token });
  if (result.ok) {
    return result.data;
  }
  if (result.error.status === 404) {
    return null;
  }
  return unwrap(result, next);
}

export async function getIngestSessions(token: string, next: string): Promise<StreamSession[]> {
  return unwrap(await api<{ items: StreamSession[] }>("/ingest/sessions", { token }), next).items;
}

export async function getOnboarding(token: string, next: string): Promise<Onboarding> {
  return unwrap(await api<Onboarding>("/onboarding", { token }), next);
}

export async function getClips(token: string, next: string): Promise<Clip[]> {
  return unwrap(await api<{ items: Clip[] }>("/clips", { token }), next).items;
}

export async function getSocialAccounts(token: string, next: string): Promise<SocialAccountList> {
  return unwrap(await api<SocialAccountList>("/social/accounts", { token }), next);
}

export type PublicInfo = { catalog: PlanCatalog; meta: Meta };

/**
 * Plans and platform capabilities: public, identical for every visitor, so
 * shared for a few minutes. Null when the API cannot be reached (failures
 * are never cached).
 */
export async function getPublicInfo(): Promise<PublicInfo | null> {
  try {
    return await fetchPublicInfo();
  } catch {
    return null;
  }
}

async function fetchPublicInfo(): Promise<PublicInfo> {
  "use cache";
  cacheLife("minutes");
  const [catalog, meta] = await Promise.all([
    api<PlanCatalog>("/plans", { forwardClient: false }),
    api<Meta>("/meta", { forwardClient: false }),
  ]);
  if (!catalog.ok || !meta.ok) {
    throw new Error("Public information is unavailable");
  }
  return { catalog: catalog.data, meta: meta.data };
}
