"use client";

import { HighlightPlayer } from "@/components/app/highlight-player";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import type { Highlight } from "@/types/api";

type Props = {
  highlights: Highlight[];
  mediaUrlAction: (id: string) => Promise<{ url?: string; error?: string }>;
};

export function HighlightsGallery({ highlights, mediaUrlAction }: Props) {
  if (highlights.length === 0) {
    return (
      <Card>
        <CardTitle>Aucun highlight pour l’instant</CardTitle>
        <CardDescription className="mt-2">
          Dès qu’un live est analysé (segments de 5 minutes), les moments viraux apparaissent ici
          avec sous-titres et score de viralité.
        </CardDescription>
      </Card>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {highlights.map((h) => (
        <HighlightPlayer key={h.id} highlight={h} mediaUrlAction={mediaUrlAction} />
      ))}
    </div>
  );
}
