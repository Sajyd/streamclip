"use client";

import { useEffect, useState } from "react";

import { QuotaSummary } from "@/components/app/billing-widgets";
import { fetchBillingOverview } from "@/lib/billing-poll";
import type { BillingOverview } from "@/types/api";

type Props = {
  overview: BillingOverview;
  timeZone: string;
  pollMs?: number;
};

export function LiveQuota({ overview, timeZone, pollMs = 5000 }: Props) {
  const [current, setCurrent] = useState(overview);

  useEffect(() => {
    setCurrent(overview);
  }, [overview]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      const next = await fetchBillingOverview(controller.signal);
      if (cancelled || !next) return;
      setCurrent(next);
    };
    const timer = window.setInterval(() => void tick(), pollMs);
    const onVis = () => {
      if (document.visibilityState === "visible") void tick();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [pollMs]);

  return <QuotaSummary overview={current} timeZone={timeZone} />;
}
