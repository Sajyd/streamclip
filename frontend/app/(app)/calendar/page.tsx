import type { Metadata } from "next";
import { Suspense } from "react";

import { ButtonLink } from "@/components/ui/button";
import { Card, CardDescription, CardTitle, Skeleton } from "@/components/ui/primitives";
import { requireSession } from "@/lib/dal";

export const metadata: Metadata = { title: "Calendrier" };

const PATH = "/calendar";

async function Calendar() {
  await requireSession(PATH);
  return (
    <div className="space-y-8">
      <div>
        <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Calendrier</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
          Publications programmées
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-300">
          Retrouvez ici chaque publication planifiée : highlight ou clip, titre, description et
          date. Vous pourrez modifier ou supprimer une entrée avant qu’elle parte sur vos réseaux.
        </p>
      </div>

      <Card>
        <CardTitle>Bientôt disponible</CardTitle>
        <CardDescription className="mt-2 max-w-xl leading-relaxed">
          La programmation depuis les highlights, le rendu Remotion au moment de la publication et
          ce calendrier arrivent ensuite. En attendant, branchez OBS via le guide et consultez vos
          highlights.
        </CardDescription>
        <div className="mt-6 flex flex-wrap gap-2">
          <ButtonLink href="/guide" size="sm">
            Ouvrir le guide
          </ButtonLink>
          <ButtonLink href="/highlights" variant="secondary" size="sm">
            Voir les highlights
          </ButtonLink>
        </div>
      </Card>
    </div>
  );
}

export default function CalendarPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full" />}>
      <Calendar />
    </Suspense>
  );
}
