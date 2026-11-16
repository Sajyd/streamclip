"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Re-reads the page from the server at intervals while something is pending
 * (a payment being confirmed, an export being generated), then stops.
 */
export function AutoRefresh({ intervalMs = 3000, attempts = 15 }: { intervalMs?: number; attempts?: number }) {
  const router = useRouter();
  useEffect(() => {
    let remaining = attempts;
    const timer = setInterval(() => {
      remaining -= 1;
      router.refresh();
      if (remaining <= 0) {
        clearInterval(timer);
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }, [router, intervalMs, attempts]);
  return null;
}
