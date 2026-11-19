import type { Highlight } from "@/types/api";

/** Browser fetch poll. Null means the request failed; an empty list is a real result. */
export async function fetchHighlights(signal?: AbortSignal): Promise<Highlight[] | null> {
  try {
    const res = await fetch("/api/live/highlights", {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { items?: Highlight[] };
    return data.items ?? [];
  } catch {
    return null;
  }
}

export function mostRecentHighlights(items: Highlight[], limit = 6): Highlight[] {
  return [...items]
    .sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0))
    .slice(0, limit);
}
