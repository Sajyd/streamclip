import "server-only";

import { notFound, redirect } from "next/navigation";

import { api } from "@/lib/api";
import { requireSession, ServiceUnavailableError } from "@/lib/dal";
import type { Me } from "@/types/api";

export async function requireStaff(next: string): Promise<{ token: string; me: Me }> {
  const session = await requireSession(next);
  if (session.me.user.platform_role === "user") {
    notFound();
  }
  return session;
}

export function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function adminFetch<T>(
  path: string,
  token: string,
  next: string,
): Promise<T> {
  const result = await api<T>(path, { token });
  if (!result.ok) {
    if (result.error.status === 401) {
      redirect(`/auth/refresh?next=${encodeURIComponent(next)}`);
    }
    if (result.error.status === 403) {
      notFound();
    }
    throw new ServiceUnavailableError();
  }
  return result.data;
}

export function deltaLabel(current: number, previous: number): { text: string; tone: "ok" | "danger" | "neutral" } {
  const diff = current - previous;
  if (diff === 0) {
    return { text: "identique à la période précédente", tone: "neutral" };
  }
  const sign = diff > 0 ? "+" : "";
  const pct = previous === 0 ? null : Math.round((diff / previous) * 100);
  return {
    text: pct === null ? `${sign}${diff} vs période précédente` : `${sign}${diff} (${sign}${pct} %)`,
    tone: diff > 0 ? "ok" : "danger",
  };
}
