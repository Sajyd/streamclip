import type { BillingOverview } from "@/types/api";

/** Browser fetch poll — do not use Server Actions (they block App Router navigations). */
export async function fetchBillingOverview(signal?: AbortSignal): Promise<BillingOverview | null> {
  try {
    const res = await fetch("/api/billing/overview", {
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
    if (!res.ok) return null;
    return (await res.json()) as BillingOverview;
  } catch {
    return null;
  }
}
