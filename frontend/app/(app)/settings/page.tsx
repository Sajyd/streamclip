import type { Metadata } from "next";
import { Suspense } from "react";

import {
  changePasswordAction,
  deleteAccountAction,
  logoutEverywhereAction,
  renameOrganizationAction,
  requestExportAction,
  revokeSessionAction,
  updateProfileAction,
} from "@/app/actions/account";
import { resendVerificationAction } from "@/app/actions/auth";
import { AutoRefresh } from "@/components/app/auto-refresh";
import { StreamKeyManager } from "@/components/app/ingest-credentials";
import { SocialConnections } from "@/components/app/social-connections";
import { buttonClasses } from "@/components/ui/button";
import { Field, Form, FormMessage, SelectField, SubmitButton } from "@/components/ui/form";
import { Badge, Card, CardDescription, CardTitle, Notice, Skeleton } from "@/components/ui/primitives";
import { PASSWORD_MIN_LENGTH, SUPPORTED_TIME_ZONES } from "@/lib/constants";
import {
  getAuthSessions,
  getDataExports,
  getIngestKey,
  getSocialAccounts,
  requireSession,
} from "@/lib/dal";
import { describeUserAgent, formatBytes, formatDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Paramètres" };

const PATH = "/settings";

async function Settings() {
  const { token, me } = await requireSession(PATH);
  const { user, organization, capabilities } = me;
  const canManage = organization.role === "owner" || organization.role === "admin";
  const [sessions, exports, ingestKey, social] = await Promise.all([
    getAuthSessions(token, PATH),
    capabilities.storage && canManage ? getDataExports(token, PATH) : Promise.resolve([]),
    capabilities.ingest_keys && canManage ? getIngestKey(token, PATH) : Promise.resolve(null),
    capabilities.social_oauth && canManage
      ? getSocialAccounts(token, PATH)
      : Promise.resolve({ items: [], oauth_available: false, platforms: [] }),
  ]);
  const timeZone = user.timezone;
  const timeZones = SUPPORTED_TIME_ZONES.includes(timeZone as (typeof SUPPORTED_TIME_ZONES)[number])
    ? SUPPORTED_TIME_ZONES
    : [timeZone, ...SUPPORTED_TIME_ZONES];
  const pendingExport = exports.some((item) => item.status === "pending");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Paramètres</h1>
        <p className="mt-1 text-sm text-ink-300">Votre profil, votre sécurité et vos données.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardTitle>Profil</CardTitle>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-300">
            <span>{user.email}</span>
            {user.email_verified ? (
              <Badge tone="ok">Adresse confirmée</Badge>
            ) : (
              <Badge tone="warn">Adresse non confirmée</Badge>
            )}
          </div>
          {!user.email_verified && capabilities.email_delivery ? (
            <Form action={resendVerificationAction} className="mt-3 space-y-2">
              <SubmitButton variant="secondary" size="sm" pendingLabel="Envoi…">
                Renvoyer l&apos;e-mail de confirmation
              </SubmitButton>
            </Form>
          ) : null}
          <Form action={updateProfileAction} className="mt-5">
            <Field
              name="display_name"
              label="Nom ou pseudo"
              defaultValue={user.display_name ?? ""}
              maxLength={120}
              autoComplete="nickname"
            />
            <SelectField
              name="timezone"
              label="Fuseau horaire"
              options={timeZones}
              defaultValue={timeZone}
            />
            <SubmitButton pendingLabel="Enregistrement…">Enregistrer</SubmitButton>
          </Form>
        </Card>

        <Card>
          <CardTitle>Espace de travail</CardTitle>
          <CardDescription>
            Vos lives, vos clips et votre abonnement sont rattachés à cet espace.
          </CardDescription>
          {canManage ? (
            <Form action={renameOrganizationAction} className="mt-5">
              <Field name="name" label="Nom de l'espace" defaultValue={organization.name} maxLength={120} required />
              <SubmitButton pendingLabel="Enregistrement…">Renommer</SubmitButton>
            </Form>
          ) : (
            <p className="mt-5 text-sm text-ink-200">{organization.name}</p>
          )}
        </Card>

        <Card>
          <CardTitle>Mot de passe</CardTitle>
          <CardDescription>
            Après un changement, vos autres appareils sont déconnectés.
          </CardDescription>
          <Form action={changePasswordAction} className="mt-5">
            <Field
              name="current_password"
              type="password"
              label="Mot de passe actuel"
              autoComplete="current-password"
              required
            />
            <Field
              name="password"
              type="password"
              label="Nouveau mot de passe"
              autoComplete="new-password"
              minLength={PASSWORD_MIN_LENGTH}
              required
              hint={`Au moins ${PASSWORD_MIN_LENGTH} caractères.`}
            />
            <SubmitButton pendingLabel="Modification…">Modifier le mot de passe</SubmitButton>
          </Form>
        </Card>

        {capabilities.ingest_keys && canManage ? (
          <Card>
            <CardTitle>Clé d&apos;ingestion</CardTitle>
            <CardDescription>
              Une URL RTMP + votre clé secrète (affichée une seule fois). Au live, l&apos;analyse
              démarre automatiquement.
            </CardDescription>
            <div className="mt-5">
              <StreamKeyManager
                canManage={canManage}
                ingestOnline={capabilities.ingest_online}
                rtmpUrl={capabilities.ingest_rtmp_url}
                existingKey={ingestKey}
                timeZone={timeZone}
              />
            </div>
          </Card>
        ) : null}

        {capabilities.social_oauth && canManage ? (
          <Card>
            <CardTitle>Réseaux sociaux</CardTitle>
            <CardDescription>
              Connectez YouTube, TikTok et Instagram pour publier automatiquement vos clips.
            </CardDescription>
            <div className="mt-5">
              <SocialConnections initial={social} canManage={canManage} />
            </div>
          </Card>
        ) : null}

        <Card>
          <CardTitle>Appareils connectés</CardTitle>
          <CardDescription>Les sessions ouvertes sur votre compte.</CardDescription>
          <ul className="mt-5 divide-y divide-ink-700">
            {sessions.map((session) => (
              <li key={session.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm text-white">
                    {describeUserAgent(session.user_agent)}
                    {session.current ? <Badge tone="brand">Cet appareil</Badge> : null}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-ink-400">
                    {session.ip ?? "Adresse inconnue"} · dernière activité{" "}
                    {formatDateTime(session.last_seen_at ?? session.created_at, timeZone)}
                  </p>
                </div>
                {session.current ? null : (
                  <Form action={revokeSessionAction} quiet className="shrink-0 space-y-0">
                    <input type="hidden" name="session_id" value={session.id} />
                    <SubmitButton variant="secondary" size="sm" pendingLabel="…">
                      Déconnecter
                    </SubmitButton>
                  </Form>
                )}
              </li>
            ))}
          </ul>
          <Form action={logoutEverywhereAction} className="mt-4 space-y-2">
            <SubmitButton variant="secondary" size="sm" pendingLabel="Déconnexion…">
              Déconnecter tous les appareils
            </SubmitButton>
          </Form>
        </Card>
      </div>

      {canManage ? (
        <Card>
          <CardTitle>Mes données</CardTitle>
          <CardDescription>
            Téléchargez une copie de toutes les données associées à votre compte (format JSON). Un
            export reste disponible 7 jours.
          </CardDescription>
          {capabilities.storage ? (
            <>
              {pendingExport ? <AutoRefresh /> : null}
              {exports.length > 0 ? (
                <ul className="mt-5 divide-y divide-ink-700">
                  {exports.map((item) => (
                    <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                      <div>
                        <p className="text-sm text-white">
                          Export du {formatDateTime(item.created_at, timeZone)}
                        </p>
                        <p className="mt-0.5 text-xs text-ink-400">
                          {item.status === "available" && item.size_bytes !== null
                            ? `${formatBytes(item.size_bytes)}${item.expires_at ? ` · disponible jusqu'au ${formatDateTime(item.expires_at, timeZone)}` : ""}`
                            : "Préparation en cours…"}
                        </p>
                      </div>
                      {item.status === "available" ? (
                        // A plain link: the route checks ownership, then redirects
                        // to a download address valid for a few minutes.
                        <a
                          href={`/settings/exports/${item.id}`}
                          className={buttonClasses({ variant: "secondary", size: "sm" })}
                        >
                          Télécharger
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              <Form action={requestExportAction} className="mt-4 space-y-2">
                <SubmitButton variant="secondary" pendingLabel="Préparation…">
                  Demander un export
                </SubmitButton>
              </Form>
            </>
          ) : (
            <Notice tone="neutral" className="mt-5">
              L&apos;export en ligne n&apos;est pas activé sur cette plateforme pour le moment.
            </Notice>
          )}
        </Card>
      ) : null}

      {canManage ? (
        <Card className="border-danger-500/40">
          <CardTitle>Supprimer mon compte</CardTitle>
          <CardDescription>
            Votre compte est fermé immédiatement, puis votre espace, vos fichiers et vos données sont
            effacés. Un abonnement en cours est résilié. Cette action est définitive ; les factures
            déjà émises restent conservées par notre prestataire de paiement, comme la loi l&apos;impose.
          </CardDescription>
          <Form action={deleteAccountAction} quiet className="mt-5 max-w-md">
            <Field
              name="current_password"
              type="password"
              label="Mot de passe"
              autoComplete="current-password"
              required
            />
            <Field
              name="confirmation"
              label="Saisissez SUPPRIMER pour confirmer"
              autoComplete="off"
              autoCapitalize="characters"
              required
            />
            <FormMessage />
            <SubmitButton variant="danger" pendingLabel="Suppression…">
              Supprimer définitivement mon compte
            </SubmitButton>
          </Form>
        </Card>
      ) : null}
    </div>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Chargement des paramètres">
      <Skeleton className="h-10 w-48" />
      <div className="grid gap-6 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-64" />
        ))}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<SettingsSkeleton />}>
      <Settings />
    </Suspense>
  );
}
