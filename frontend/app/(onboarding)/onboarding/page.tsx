import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";

import { OnboardingWizard } from "@/components/app/onboarding-wizard";
import { Skeleton } from "@/components/ui/primitives";
import {
  getBillingOverview,
  getIngestKey,
  getIngestSessions,
  getPublicInfo,
  requireSession,
} from "@/lib/dal";

export const metadata: Metadata = { title: "Bienvenue" };

const PATH = "/onboarding";

async function OnboardingContent() {
  const { token, me } = await requireSession(PATH);
  if (me.onboarding.completed) {
    redirect("/dashboard");
  }
  const { user, organization, capabilities } = me;
  const canManage = organization.role === "owner" || organization.role === "admin";
  const [overview, info, ingestKey, sessions] = await Promise.all([
    getBillingOverview(token, PATH),
    getPublicInfo(),
    capabilities.ingest_keys ? getIngestKey(token, PATH) : Promise.resolve(null),
    capabilities.ingest_keys ? getIngestSessions(token, PATH) : Promise.resolve([]),
  ]);

  return (
    <OnboardingWizard
      initial={me.onboarding}
      displayName={user.display_name}
      canManage={canManage}
      ingestOnline={capabilities.ingest_online}
      ingestKey={ingestKey}
      sessions={sessions}
      plans={info?.catalog.items ?? []}
      overview={overview}
      socialOauth={capabilities.social_oauth}
    />
  );
}

export default function OnboardingPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6" aria-busy aria-label="Chargement de l'onboarding">
          <Skeleton className="h-2 w-full rounded-full" />
          <Skeleton className="h-64 rounded-3xl" />
        </div>
      }
    >
      <OnboardingContent />
    </Suspense>
  );
}
