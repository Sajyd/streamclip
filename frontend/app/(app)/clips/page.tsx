import type { Metadata } from "next";
import { Suspense } from "react";

import { ClipsLibrary } from "@/components/app/clips-library";
import { Skeleton } from "@/components/ui/primitives";
import { getClips, requireSession } from "@/lib/dal";

export const metadata: Metadata = { title: "Clips" };

const PATH = "/clips";

async function ClipsContent() {
  const { token, me } = await requireSession(PATH);
  const clips = await getClips(token, PATH);
  return <ClipsLibrary clips={clips} timeZone={me.user.timezone} />;
}

export default function ClipsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Clips</h1>
        <p className="mt-1 text-sm text-ink-300">
          Tous vos clips générés — téléchargez-les et publiez-les où vous voulez.
        </p>
      </div>
      <Suspense
        fallback={
          <div aria-busy aria-label="Chargement des clips">
            <Skeleton className="h-64 rounded-3xl" />
          </div>
        }
      >
        <ClipsContent />
      </Suspense>
    </div>
  );
}
