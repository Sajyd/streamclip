"use server";

import { api } from "@/lib/api";
import { readSession } from "@/lib/session";

export async function highlightMediaUrlAction(
  highlightId: string,
): Promise<{ url?: string; error?: string }> {
  const { access } = await readSession();
  if (!access) {
    return { error: "Session expirée" };
  }
  const result = await api<{ url: string }>(`/highlights/${highlightId}/media-url`, {
    token: access,
  });
  if (!result.ok) {
    return { error: result.error.message || "Extrait indisponible" };
  }
  return { url: result.data.url };
}
