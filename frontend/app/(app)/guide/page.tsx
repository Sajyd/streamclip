import type { Metadata } from "next";
import { Suspense } from "react";

import { SetupTutorial } from "@/components/app/setup-tutorial";
import { ButtonLink } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { getIngestKey, requireSession } from "@/lib/dal";

export const metadata: Metadata = { title: "Guide de connexion" };

const PATH = "/guide";

async function Guide() {
  const { token, me } = await requireSession(PATH);
  const { user, organization, capabilities } = me;
  const canManage = organization.role === "owner" || organization.role === "admin";
  const ingestKey =
    capabilities.ingest_keys && canManage ? await getIngestKey(token, PATH) : null;
  const software =
    me.onboarding.software === "streamlabs" || me.onboarding.software === "obs"
      ? me.onboarding.software
      : "obs";

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Guide</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Brancher OBS ou Streamlabs
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-300">
            Tutoriel pas à pas, même après l’onboarding. Ajoutez STREAMCLIP en destination
            supplémentaire — votre diffusion principale ne change pas.
          </p>
        </div>
        <ButtonLink href="/settings" variant="secondary" size="sm">
          Paramètres & clé
        </ButtonLink>
      </div>

      {capabilities.ingest_keys ? (
        <SetupTutorial
          canManage={canManage}
          ingestOnline={capabilities.ingest_online}
          rtmpUrl={capabilities.ingest_rtmp_url}
          existingKey={ingestKey}
          timeZone={user.timezone}
          initialPlatform={software}
        />
      ) : (
        <p className="text-sm text-ink-300">
          La connexion live n’est pas encore activée sur cette plateforme.
        </p>
      )}
    </div>
  );
}

export default function GuidePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <Guide />
    </Suspense>
  );
}
