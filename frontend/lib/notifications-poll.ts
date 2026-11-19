import type { NotificationList } from "@/types/api";

/** Browser fetch poll — do not use Server Actions (they block App Router navigations). */
export async function fetchNotifications(signal?: AbortSignal): Promise<NotificationList | null> {
  try {
    const res = await fetch("/api/notifications", {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) return null;
    return (await res.json()) as NotificationList;
  } catch {
    return null;
  }
}
