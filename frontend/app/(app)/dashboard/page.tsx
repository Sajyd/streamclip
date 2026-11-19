import type { Metadata } from "next";
import { Suspense } from "react";

import { resendVerificationAction } from "@/app/actions/auth";
import { highlightMediaUrlAction } from "@/app/actions/highlights";
import { PlanSummary } from "@/components/app/billing-widgets";
import { LiveDetector } from "@/components/app/live-detector";
import { LiveMonitor } from "@/components/app/live-monitor";
import { LiveNotifications } from "@/components/app/live-notifications";
import { LiveQuota } from "@/components/app/live-quota";
import { RecentHighlights } from "@/components/app/recent-highlights";
import { ButtonLink } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Notice, Skeleton } from "@/components/ui/primitives";
import {
  getBillingOverview,
  getHighlights,
  getIngestSessions,
  getLivePlayback,
  getNotifications,
  requireSession,
} from "@/lib/dal";

export const metadata: Metadata = { title: "Tableau de bord" };

const PATH = "/dashboard";

async function Dashboard() {
  const { token, me } = await requireSession(PATH);
  const { user, capabilities } = me;
  const [overview, notifications, ingestSessions, highlights, playback] = await Promise.all([
    getBillingOverview(token, PATH),
    getNotifications(token, PATH),
    capabilities.ingest_keys ? getIngestSessions(token, PATH) : Promise.resolve([]),
    getHighlights(token, PATH),
    capabilities.ingest_keys
      ? getLivePlayback(token, PATH)
      : Promise.resolve({
          status: "offline" as const,
          session_id: null,
          public_id: null,
          title: null,
          rtmp_url: null,
          preview_available: false,
          message: "",
          stream_key_hint: null,
          preview_token: null,
        }),
  ]);
  const timeZone = user.timezone;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">
            Tableau de bord
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
            Bonjour{user.display_name ? ` ${user.display_name}` : ""}
          </h1>
          <p className="mt-1.5 text-sm text-ink-300">
            Lancez votre live — STREAMCLIP détecte et prépare vos highlights.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/live" variant="secondary" size="sm">
            Live
          </ButtonLink>
          <ButtonLink href="/guide" variant="secondary" size="sm">
            Guide
          </ButtonLink>
          <ButtonLink href="/highlights" variant="secondary" size="sm">
            Highlights
          </ButtonLink>
          <ButtonLink href="/billing" variant="secondary" size="sm">
            {overview.is_paid ? "Abonnement" : "Offres"}
          </ButtonLink>
        </div>
      </div>

      {capabilities.ingest_keys ? (
        <LiveDetector sessions={ingestSessions} persistDetection={false} />
      ) : null}

      {overview.payment_failed ? (
        <Notice tone="danger" title="Le dernier paiement a échoué">
          Mettez à jour votre moyen de paiement depuis la page Abonnement pour conserver votre offre.
        </Notice>
      ) : null}

      {!user.email_verified && capabilities.email_delivery ? (
        <Notice tone="warn" title="Confirmez votre adresse e-mail">
          <p>
            Un e-mail de confirmation a été envoyé à {user.email}. Il permet de récupérer votre compte
            en cas d&apos;oubli du mot de passe.
          </p>
          <Form action={resendVerificationAction} quiet className="mt-3 space-y-2">
            <SubmitButton variant="secondary" size="sm" pendingLabel="Envoi…">
              Renvoyer l&apos;e-mail
            </SubmitButton>
            <FormMessage />
          </Form>
        </Notice>
      ) : null}

      <div className="grid items-stretch gap-5 lg:grid-cols-2">
        {capabilities.ingest_keys ? (
          <LiveMonitor
            initialPlayback={playback}
            hlsBase="/live/stream"
            playerOnly
          />
        ) : (
          <div className="flex min-h-[22rem] items-center justify-center rounded-2xl border border-white/10 bg-ink-950 px-6 text-center text-sm text-ink-400">
            Aperçu live indisponible
          </div>
        )}
        <LiveQuota overview={overview} timeZone={timeZone} />
        <LiveNotifications notifications={notifications} timeZone={timeZone} />
        <PlanSummary overview={overview} timeZone={timeZone} />
      </div>

      <RecentHighlights
        highlights={highlights}
        mediaUrlAction={highlightMediaUrlAction}
        showWatermark={!overview.is_paid}
      />
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-8" aria-busy aria-label="Chargement du tableau de bord">
      <Skeleton className="h-14 w-72" />
      <div className="grid gap-5 lg:grid-cols-2">
        <Skeleton className="h-52 rounded-3xl" />
        <Skeleton className="h-52 rounded-3xl" />
        <Skeleton className="h-52 rounded-3xl" />
        <Skeleton className="h-52 rounded-3xl" />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <Dashboard />
    </Suspense>
  );
}
