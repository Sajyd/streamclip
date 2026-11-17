import type { Metadata } from "next";
import { Suspense } from "react";

import { highlightMediaUrlAction } from "@/app/actions/highlights";
import { HighlightsGallery } from "@/components/app/highlights-gallery";
import { Skeleton } from "@/components/ui/primitives";
import { getBillingOverview, getHighlights, requireSession } from "@/lib/dal";

export const metadata: Metadata = { title: "Highlights" };

const PATH = "/highlights";

async function HighlightsContent() {
  const { token } = await requireSession(PATH);
  const [highlights, overview] = await Promise.all([
    getHighlights(token, PATH),
    getBillingOverview(token, PATH),
  ]);
  return (
    <HighlightsGallery
      highlights={highlights}
      mediaUrlAction={highlightMediaUrlAction}
      showWatermark={!overview.is_paid}
    />
  );
}

export default function HighlightsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Highlights</h1>
        <p className="mt-1 text-sm text-ink-300">
          Moments viraux détectés sur vos lives, prêts à publier en format vertical avec
          sous-titres et cam streamer si détectée.
        </p>
      </div>
      <Suspense
        fallback={
          <div aria-busy aria-label="Chargement des highlights">
            <Skeleton className="h-96 rounded-3xl" />
          </div>
        }
      >
        <HighlightsContent />
      </Suspense>
    </div>
  );
}
