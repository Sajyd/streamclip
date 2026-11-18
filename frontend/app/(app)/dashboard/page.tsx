import type { Metadata } from "next";
import { Suspense } from "react";

import { markNotificationsReadAction } from "@/app/actions/account";
import { resendVerificationAction } from "@/app/actions/auth";
import { PlanSummary, QuotaSummary } from "@/components/app/billing-widgets";
import { ClipsLibrary } from "@/components/app/clips-library";
import { LiveDetector } from "@/components/app/live-detector";
import { LiveMonitor } from "@/components/app/live-monitor";
import { ButtonLink } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle, Notice, Skeleton } from "@/components/ui/primitives";
import {
  getBillingOverview,
  getClips,
  getIngestSessions,
  getLivePlayback,
  getNotifications,
  requireSession,
} from "@/lib/dal";
import { cx, formatDateTime } from "@/lib/format";
import type { Notification, NotificationList } from "@/types/api";

export const metadata: Metadata = { title: "Tableau de bord" };

const PATH = "/dashboard";

const SEVERITY_DOT: Record<Notification["severity"], string> = {
  info: "bg-brand-400",
  success: "bg-ok-400",
  warning: "bg-warn-400",
  error: "bg-danger-400",
};

function NotificationsCard({
  notifications,
  timeZone,
}: {
  notifications: NotificationList;
  timeZone: string;
}) {
  return (
    <Card className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Activité</p>
          <CardTitle className="mt-2">Notifications</CardTitle>
          <CardDescription>
            {notifications.unread_count > 0
              ? `${notifications.unread_count} non lue${notifications.unread_count > 1 ? "s" : ""}`
              : "Vous êtes à jour."}
          </CardDescription>
        </div>
        {notifications.unread_count > 0 ? (
          <Form action={markNotificationsReadAction} className="space-y-0">
            <SubmitButton variant="ghost" size="sm">
              Tout marquer comme lu
            </SubmitButton>
          </Form>
        ) : null}
      </div>
      {notifications.items.length === 0 ? (
        <p className="mt-6 text-sm text-ink-400">Aucune notification pour le moment.</p>
      ) : (
        <ul className="mt-4 max-h-56 flex-1 divide-y divide-white/5 overflow-y-auto">
          {notifications.items.slice(0, 6).map((notification) => (
            <li key={notification.id} className="flex gap-3 py-3 first:pt-1">
              <span
                aria-hidden
                className={cx(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  notification.read_at ? "bg-ink-600" : SEVERITY_DOT[notification.severity],
                )}
              />
              <div className="min-w-0">
                <p
                  className={cx(
                    "text-sm",
                    notification.read_at ? "text-ink-200" : "font-medium text-white",
                  )}
                >
                  {notification.title}
                </p>
                <p className="mt-0.5 line-clamp-2 text-sm leading-relaxed text-ink-300">
                  {notification.body}
                </p>
                <p className="mt-1 text-xs text-ink-500">
                  {formatDateTime(notification.created_at, timeZone)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

async function Dashboard() {
  const { token, me } = await requireSession(PATH);
  const { user, capabilities } = me;
  const [overview, notifications, ingestSessions, clips, playback] = await Promise.all([
    getBillingOverview(token, PATH),
    getNotifications(token, PATH),
    capabilities.ingest_keys ? getIngestSessions(token, PATH) : Promise.resolve([]),
    getClips(token, PATH),
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
            Lancez votre live — STREAMCLIP détecte et prépare vos clips.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ButtonLink href="/live" variant="secondary" size="sm">
            Live
          </ButtonLink>
          <ButtonLink href="/guide" variant="secondary" size="sm">
            Guide
          </ButtonLink>
          <ButtonLink href="/clips" variant="secondary" size="sm">
            Clips
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
        <QuotaSummary overview={overview} timeZone={timeZone} />
        <NotificationsCard notifications={notifications} timeZone={timeZone} />
        <PlanSummary overview={overview} timeZone={timeZone} />
      </div>

      <ClipsLibrary clips={clips} timeZone={timeZone} />
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
