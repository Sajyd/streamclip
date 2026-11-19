"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { HighlightsGallery } from "@/components/app/highlights-gallery";
import { fetchHighlights, mostRecentHighlights } from "@/lib/highlights-poll";
import type { Highlight } from "@/types/api";

const LIMIT = 6;

type Props = {
  highlights: Highlight[];
  mediaUrlAction: (id: string) => Promise<{ url?: string; error?: string }>;
  showWatermark?: boolean;
  pollMs?: number;
};

function sameList(a: Highlight[], b: Highlight[]): boolean {
  if (a.length !== b.length) return false;
  return a.every(
    (item, index) =>
      item.id === b[index]?.id &&
      item.title === b[index]?.title &&
      item.score === b[index]?.score &&
      item.media_available === b[index]?.media_available,
  );
}

export function RecentHighlights({
  highlights,
  mediaUrlAction,
  showWatermark = false,
  pollMs = 5000,
}: Props) {
  const [current, setCurrent] = useState(() => mostRecentHighlights(highlights, LIMIT));

  useEffect(() => {
    setCurrent(mostRecentHighlights(highlights, LIMIT));
  }, [highlights]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      const next = await fetchHighlights(controller.signal);
      if (cancelled || !next) return;
      const recent = mostRecentHighlights(next, LIMIT);
      setCurrent((previous) => (sameList(previous, recent) ? previous : recent));
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

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Highlights</p>
          <h2 className="mt-2 text-xl font-semibold tracking-tight text-white">Les plus récents</h2>
        </div>
        <Link href="/highlights" className="text-sm text-brand-300 hover:text-brand-200">
          Voir tout
        </Link>
      </div>
      <HighlightsGallery
        highlights={current}
        mediaUrlAction={mediaUrlAction}
        showWatermark={showWatermark}
      />
    </section>
  );
}
