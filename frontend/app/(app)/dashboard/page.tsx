import type { Metadata } from "next";
import { Suspense } from "react";

import { markNotificationsReadAction } from "@/app/actions/account";
import { resendVerificationAction } from "@/app/actions/auth";
import { PlanSummary, QuotaSummary } from "@/components/app/billing-widgets";
import { IngestPanel } from "@/components/app/ingest-panel";
import { ButtonLink } from "@/components/ui/button";
import { Form, FormMessage, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle, Notice, Skeleton } from "@/components/ui/primitives";
import {
  getBillingOverview,
  getIngestKey,
  getIngestSessions,
  getNotifications,
  requireSession,
} from "@/lib/dal";
import { cx, formatDateTime } from "@/lib/format";
import type { Notification } from "@/types/api";

export const metadata: Metadata = { title: "Tableau de bord" };

const PATH = "/dashboard";

const SEVERITY_DOT: Record<Notification["severity"], string> = {
  info: "bg-brand-400",
  success: "bg-ok-400",
  warning: "bg-warn-400",
  error: "bg-danger-400",
};

async function Dashboard() {
  const { token, me } = await requireSession(PATH);
  const { user, organization, capabilities } = me;
  const canManage = organization.role === "owner" || organization.role === "admin";
  const [overview, notifications, ingestKey, ingestSessions] = await Promise.all([
    getBillingOverview(token, PATH),
    getNotifications(token, PATH),
    capabilities.ingest_keys ? getIngestKey(token, PATH) : Promise.resolve(null),
    capabilities.ingest_keys ? getIngestSessions(token, PATH) : Promise.resolve([]),
  ]);
  const timeZone = user.timezone;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">
          Bonjour{user.display_name ? ` ${user.display_name}` : ""}
        </h1>
        <p className="mt-1 text-sm text-ink-300">Votre offre, votre consommation et vos notifications.</p>
      </div>

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

      <div className="grid gap-6 lg:grid-cols-2">
        <QuotaSummary overview={overview} timeZone={timeZone} />
        <div className="flex flex-col gap-4">
          <PlanSummary overview={overview} timeZone={timeZone} />
          <ButtonLink href="/billing" variant="secondary" className="self-start">
            {overview.is_paid ? "Gérer mon abonnement" : "Voir les offres"}
          </ButtonLink>
        </div>
      </div>

      {capabilities.ingest_keys ? (
        <IngestPanel
          canManage={canManage}
          ingestOnline={capabilities.ingest_online}
          liveProcessing={capabilities.live_processing}
          existingKey={ingestKey}
          sessions={ingestSessions}
          timeZone={timeZone}
        />
      ) : (
        <Card>
          <CardTitle>Lives et clips</CardTitle>
          <CardDescription>
            La connexion de votre logiciel de diffusion et la génération de clips ne sont pas encore
            ouvertes sur la plateforme. Votre compte et votre offre sont prêts : cet espace affichera
            vos lives et vos clips dès l&apos;ouverture du traitement.
          </CardDescription>
        </Card>
      )}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle>Notifications</CardTitle>
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
          <p className="mt-5 text-sm text-ink-400">Aucune notification pour le moment.</p>
        ) : (
          <ul className="mt-5 divide-y divide-ink-700">
            {notifications.items.map((notification) => (
              <li key={notification.id} className="flex gap-3 py-3.5">
                <span
                  aria-hidden
                  className={cx(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    notification.read_at ? "bg-ink-600" : SEVERITY_DOT[notification.severity],
                  )}
                />
                <div className="min-w-0">
                  <p className={cx("text-sm", notification.read_at ? "text-ink-200" : "font-medium text-white")}>
                    {notification.title}
                  </p>
                  <p className="mt-0.5 text-sm text-ink-300">{notification.body}</p>
                  <p className="mt-1 text-xs text-ink-500">
                    {formatDateTime(notification.created_at, timeZone)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Chargement du tableau de bord">
      <Skeleton className="h-10 w-64" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
      <Skeleton className="h-48" />
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
