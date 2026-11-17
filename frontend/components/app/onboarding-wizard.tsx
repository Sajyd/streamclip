"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { checkoutAction } from "@/app/actions/billing";
import {
  completeOnboardingAction,
  saveOnboardingAction,
  type OnboardingPatch,
} from "@/app/actions/onboarding";
import { LiveDetector } from "@/components/app/live-detector";
import { ObsRtmpGuide } from "@/components/app/obs-rtmp-guide";
import { PlanCard } from "@/components/plan-card";
import { buttonClasses } from "@/components/ui/button";
import { Form, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle, Notice } from "@/components/ui/primitives";
import { cx } from "@/lib/format";
import type { BillingOverview, Onboarding, Plan, StreamKey, StreamSession } from "@/types/api";

type StepId =
  | "welcome"
  | "referral"
  | "usage"
  | "software"
  | "obs-guide"
  | "social"
  | "premium"
  | "live";

const STEPS: StepId[] = [
  "welcome",
  "referral",
  "usage",
  "software",
  "obs-guide",
  "social",
  "premium",
  "live",
];

const REFERRALS = [
  { id: "youtube", label: "YouTube" },
  { id: "twitch", label: "Twitch" },
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram" },
  { id: "x", label: "X / Twitter" },
  { id: "discord", label: "Discord" },
  { id: "friend", label: "Un ami / bouche-à-oreille" },
  { id: "search", label: "Recherche Google" },
  { id: "other", label: "Autre" },
] as const;

const USAGES = [
  { id: "gaming", label: "Gaming", hint: "Jeux, ranked, chill" },
  { id: "vlog", label: "Vlog", hint: "Quotidien, lifestyle" },
  { id: "podcast", label: "Podcast", hint: "Talk, débats" },
  { id: "concert", label: "Concert / musique", hint: "Scène, DJ, perf" },
  { id: "interview", label: "Interview", hint: "Invités, plateaux" },
  { id: "just_chatting", label: "Just chatting", hint: "Discussion live" },
  { id: "irl", label: "IRL", hint: "En extérieur" },
  { id: "conference", label: "Conférence", hint: "Talks, events" },
  { id: "other", label: "Autre", hint: "On s’adapte" },
] as const;

const SOCIALS = [
  { id: "youtube" as const, label: "YouTube Shorts", color: "from-red-500/20 to-red-500/5" },
  { id: "tiktok" as const, label: "TikTok", color: "from-cyan-400/20 to-pink-500/5" },
  { id: "instagram" as const, label: "Instagram Reels", color: "from-fuchsia-500/20 to-amber-400/5" },
];

function Progress({ step }: { step: StepId }) {
  const index = Math.max(0, STEPS.indexOf(step));
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between text-xs text-ink-400">
        <span>
          Étape {index + 1} sur {STEPS.length}
        </span>
        <span>{Math.round(((index + 1) / STEPS.length) * 100)} %</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-flare-400 transition-all duration-500"
          style={{ width: `${((index + 1) / STEPS.length) * 100}%` }}
        />
      </div>
    </div>
  );
}

function ChoiceGrid({
  options,
  value,
  onChange,
  columns = 3,
}: {
  options: ReadonlyArray<{ id: string; label: string; hint?: string }>;
  value: string | null;
  onChange: (id: string) => void;
  columns?: 2 | 3;
}) {
  return (
    <div
      className={cx(
        "grid gap-2.5",
        columns === 2 ? "sm:grid-cols-2" : "sm:grid-cols-2 lg:grid-cols-3",
      )}
    >
      {options.map((option) => {
        const selected = value === option.id;
        return (
          <button
            key={option.id}
            type="button"
            onClick={() => onChange(option.id)}
            className={cx(
              "rounded-2xl border px-4 py-3.5 text-left transition-all",
              selected
                ? "border-brand-400/60 bg-brand-500/15 shadow-lg shadow-brand-500/10"
                : "border-white/10 bg-ink-950/60 hover:border-white/20 hover:bg-ink-900/70",
            )}
          >
            <p className="text-sm font-medium text-white">{option.label}</p>
            {option.hint ? <p className="mt-0.5 text-xs text-ink-400">{option.hint}</p> : null}
          </button>
        );
      })}
    </div>
  );
}

export function OnboardingWizard({
  initial,
  displayName,
  canManage,
  ingestOnline,
  ingestRtmpUrl,
  ingestKey,
  sessions,
  plans,
  overview,
  socialOauth,
}: {
  initial: Onboarding;
  displayName: string | null;
  canManage: boolean;
  ingestOnline: boolean;
  ingestRtmpUrl: string | null;
  ingestKey: StreamKey | null;
  sessions: StreamSession[];
  plans: Plan[];
  overview: BillingOverview;
  socialOauth: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const startStep = (STEPS.includes(initial.step as StepId) ? initial.step : "welcome") as StepId;
  const [step, setStep] = useState<StepId>(initial.completed ? "live" : startStep);
  const [referral, setReferral] = useState<string | null>(initial.referral_source);
  const [usage, setUsage] = useState<string | null>(initial.usage);
  const [software, setSoftware] = useState<"obs" | "streamlabs" | null>(initial.software);
  const [socials, setSocials] = useState<Array<"youtube" | "tiktok" | "instagram">>(
    initial.social_platforms,
  );

  function persist(patch: OnboardingPatch, next?: StepId) {
    setError(null);
    startTransition(async () => {
      const result = await saveOnboardingAction(patch);
      if (result.status === "error") {
        setError(result.message ?? "Enregistrement impossible.");
        return;
      }
      if (next) setStep(next);
      router.refresh();
    });
  }

  function goNext() {
    const index = STEPS.indexOf(step);
    const next = STEPS[Math.min(index + 1, STEPS.length - 1)] ?? "live";
    if (step === "welcome") {
      persist({ step: next }, next);
      return;
    }
    if (step === "referral") {
      if (!referral) {
        setError("Choisissez une option pour continuer.");
        return;
      }
      persist({ step: next, referral_source: referral }, next);
      return;
    }
    if (step === "usage") {
      if (!usage) {
        setError("Indiquez le type de contenu que vous diffusez.");
        return;
      }
      persist({ step: next, usage }, next);
      return;
    }
    if (step === "software") {
      if (!software) {
        setError("Choisissez OBS ou Streamlabs.");
        return;
      }
      persist({ step: next, software }, next);
      return;
    }
    if (step === "obs-guide") {
      persist({ step: next, ingest_ready: true, software: software ?? "obs" }, next);
      return;
    }
    if (step === "social") {
      persist({ step: next, social_platforms: socials }, next);
      return;
    }
    if (step === "premium") {
      persist({ step: next, premium_choice: "free" }, next);
      return;
    }
  }

  function goBack() {
    const index = STEPS.indexOf(step);
    if (index <= 0) return;
    const previous = STEPS[index - 1];
    if (!previous) return;
    setError(null);
    setStep(previous);
  }

  function finish(liveDetected = false) {
    setError(null);
    startTransition(async () => {
      const result = await completeOnboardingAction({
        live_detected: liveDetected || initial.live_detected,
        premium_choice: initial.premium_choice ?? "free",
        social_platforms: socials,
        software: software ?? undefined,
        usage: usage ?? undefined,
        referral_source: referral ?? undefined,
        ingest_ready: true,
      });
      if (result.status === "error") {
        setError(result.message ?? "Impossible de terminer l’onboarding.");
        return;
      }
      router.replace("/dashboard");
      router.refresh();
    });
  }

  const highlighted = plans.find((plan) => plan.code === "creator") ?? plans.find((p) => p.price_cents > 0);
  const freePlan = plans.find((plan) => plan.price_cents === 0);

  return (
    <div className="animate-fade-up">
      <Progress step={step} />

      {step === "welcome" ? (
        <Card className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-brand-500/20 to-transparent" />
          <p className="relative text-xs font-medium tracking-[0.16em] text-brand-300 uppercase">
            Bienvenue
          </p>
          <CardTitle className="relative mt-3 text-2xl sm:text-3xl">
            {displayName ? `Salut ${displayName}` : "Salut"} — branchons votre live
          </CardTitle>
          <CardDescription className="relative mt-3 max-w-xl text-base">
            En quelques minutes : branchez OBS ou Streamlabs, connectez vos réseaux, et STREAMCLIP
            détecte votre live pour préparer vos clips. Vous gardez le contrôle pour télécharger et
            publier.
          </CardDescription>
          <ul className="relative mt-6 space-y-2 text-sm text-ink-200">
            {[
              "Guide pas à pas OBS / Streamlabs",
              "Détection automatique du live",
              "Bibliothèque de clips à télécharger ou publier",
            ].map((item) => (
              <li key={item} className="flex gap-2">
                <span className="text-brand-400">✓</span>
                {item}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {step === "referral" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Découverte</p>
          <CardTitle className="mt-2 text-xl">Comment avez-vous connu STREAMCLIP ?</CardTitle>
          <CardDescription>Ça nous aide à savoir où être utiles — une seule réponse.</CardDescription>
          <div className="mt-6">
            <ChoiceGrid
              options={REFERRALS}
              value={referral}
              onChange={setReferral}
              columns={2}
            />
          </div>
        </Card>
      ) : null}

      {step === "usage" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Usage</p>
          <CardTitle className="mt-2 text-xl">Quel type de contenu diffusez-vous ?</CardTitle>
          <CardDescription>
            Gaming, vlog, podcast, concert… on adapte la détection des moments forts.
          </CardDescription>
          <div className="mt-6">
            <ChoiceGrid options={USAGES} value={usage} onChange={setUsage} />
          </div>
        </Card>
      ) : null}

      {step === "software" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Logiciel</p>
          <CardTitle className="mt-2 text-xl">Quel logiciel utilisez-vous ?</CardTitle>
          <CardDescription>
            STREAMCLIP s’ajoute comme destination — vos clés Twitch / YouTube restent chez vous.
          </CardDescription>
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {(
              [
                {
                  id: "obs" as const,
                  title: "OBS Studio",
                  body: "Guide détaillé : installer Multiple RTMP Outputs, puis ajouter STREAMCLIP en parallèle de Twitch/YouTube.",
                },
                {
                  id: "streamlabs" as const,
                  title: "Streamlabs Desktop",
                  body: "Guide détaillé : destination Custom RTMP / Multistream, ou plugin OBS en secours.",
                },
              ] as const
            ).map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => setSoftware(option.id)}
                className={cx(
                  "rounded-3xl border p-5 text-left transition-all",
                  software === option.id
                    ? "border-brand-400/60 bg-brand-500/15"
                    : "border-white/10 bg-ink-950/50 hover:border-white/20",
                )}
              >
                <p className="text-lg font-semibold text-white">{option.title}</p>
                <p className="mt-2 text-sm leading-relaxed text-ink-300">{option.body}</p>
              </button>
            ))}
          </div>
        </Card>
      ) : null}

      {step === "obs-guide" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Branchement</p>
          <CardTitle className="mt-2 text-xl">
            {software === "streamlabs"
              ? "Installer & brancher Streamlabs"
              : "Installer le plugin Multiple RTMP (OBS)"}
          </CardTitle>
          <CardDescription>
            Étapes détaillées pour installer la sortie Multiple RTMP, créer votre clé, puis coller
            le serveur RTMP unique + la clé dans{" "}
            {software === "streamlabs" ? "Streamlabs Desktop" : "OBS Studio"}.
          </CardDescription>
          <div className="mt-6">
            <ObsRtmpGuide
              software={software ?? "obs"}
              existingKey={ingestKey}
              canManage={canManage}
              ingestOnline={ingestOnline}
              rtmpUrl={ingestRtmpUrl}
            />
          </div>
        </Card>
      ) : null}

      {step === "social" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Réseaux</p>
          <CardTitle className="mt-2 text-xl">Où publiez-vous vos clips ?</CardTitle>
          <CardDescription>
            Choisissez YouTube, TikTok et/ou Instagram. Après l&apos;onboarding, connectez vos
            comptes dans Paramètres pour activer la publication automatique.
          </CardDescription>
          {socialOauth ? (
            <Notice tone="ok" title="Publication automatique disponible" className="mt-4">
              Une fois vos réseaux connectés, STREAMCLIP peut publier vos clips dès qu&apos;ils sont
              prêts. Vous pourrez aussi toujours télécharger et publier manuellement.
            </Notice>
          ) : (
            <Notice tone="neutral" title="Publication manuelle" className="mt-4">
              Indiquez vos réseaux préférés. Vous pourrez télécharger vos clips et les publier
              vous-même depuis le tableau de bord.
            </Notice>
          )}
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            {SOCIALS.map((platform) => {
              const selected = socials.includes(platform.id);
              return (
                <button
                  key={platform.id}
                  type="button"
                  onClick={() =>
                    setSocials((current) =>
                      selected
                        ? current.filter((id) => id !== platform.id)
                        : [...current, platform.id],
                    )
                  }
                  className={cx(
                    "rounded-2xl border bg-gradient-to-b p-4 text-left transition-all",
                    platform.color,
                    selected
                      ? "border-brand-400/60 ring-1 ring-brand-400/40"
                      : "border-white/10 hover:border-white/20",
                  )}
                >
                  <p className="font-medium text-white">{platform.label}</p>
                  <p className="mt-1 text-xs text-ink-300">
                    {selected ? "Sélectionné" : "Cliquer pour sélectionner"}
                  </p>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="mt-4 text-sm text-ink-400 underline-offset-2 hover:text-ink-200 hover:underline"
            onClick={() => setSocials([])}
          >
            Je publierai uniquement en manuel
          </button>
        </Card>
      ) : null}

      {step === "premium" ? (
        <div className="space-y-5">
          <Card>
            <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Offre</p>
            <CardTitle className="mt-2 text-xl">Passez en premium — ou restez gratuit</CardTitle>
            <CardDescription>
              L’offre Free suffit pour tester. Premium débloque plus d’heures et de clips par live.
              Vous pouvez changer d’avis à tout moment.
            </CardDescription>
          </Card>
          <div className="grid gap-4 sm:grid-cols-2">
            {freePlan ? (
              <PlanCard
                plan={freePlan}
                current={overview.plan.code === freePlan.code}
                action={
                  <button
                    type="button"
                    className={buttonClasses({ variant: "secondary", className: "w-full" })}
                    disabled={pending}
                    onClick={() => {
                      persist({ premium_choice: "free", step: "live" }, "live");
                    }}
                  >
                    Rester sur Free
                  </button>
                }
              />
            ) : null}
            {highlighted ? (
              <PlanCard
                plan={highlighted}
                highlighted
                current={overview.plan.code === highlighted.code}
                action={
                  overview.is_paid || !highlighted.purchasable || !overview.billing_available ? (
                    <button
                      type="button"
                      className={buttonClasses({ variant: "secondary", className: "w-full" })}
                      disabled={pending}
                      onClick={() => persist({ premium_choice: "free", step: "live" }, "live")}
                    >
                      Continuer sans changer d’offre
                    </button>
                  ) : (
                    <Form
                      action={checkoutAction}
                      className="space-y-2"
                      onSubmit={() => {
                        void saveOnboardingAction({ premium_choice: "premium", step: "premium" });
                      }}
                    >
                      <input type="hidden" name="plan_code" value={highlighted.code} />
                      <SubmitButton className="w-full" pendingLabel="Ouverture du paiement…">
                        Passer à {highlighted.name}
                      </SubmitButton>
                    </Form>
                  )
                }
              />
            ) : null}
          </div>
          <button
            type="button"
            className="text-sm text-ink-400 underline-offset-2 hover:text-ink-200 hover:underline"
            onClick={() => persist({ premium_choice: "free", step: "live" }, "live")}
          >
            Continuer gratuitement
          </button>
        </div>
      ) : null}

      {step === "live" ? (
        <Card>
          <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">Go live</p>
          <CardTitle className="mt-2 text-xl">Lancez votre live</CardTitle>
          <CardDescription>
            Démarrez la diffusion dans {software === "streamlabs" ? "Streamlabs" : "OBS"}. STREAMCLIP
            détecte automatiquement que le live a commencé — branchez, diffusez, on s’occupe du
            reste.
          </CardDescription>
          <div className="mt-6">
            <LiveDetector
              sessions={sessions}
              onDetected={() => {
                /* refresh handled inside */
              }}
            />
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={pending}
              className={buttonClasses({ variant: "primary" })}
              onClick={() => finish(Boolean(sessions.some((s) => s.status === "live" || s.status === "pending")))}
            >
              {pending ? "Ouverture…" : "Ouvrir mon tableau de bord"}
            </button>
            <button
              type="button"
              disabled={pending}
              className={buttonClasses({ variant: "ghost" })}
              onClick={() => finish(false)}
            >
              Je lancerai mon live plus tard
            </button>
          </div>
        </Card>
      ) : null}

      {error ? (
        <p role="alert" className="mt-4 rounded-lg border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-400">
          {error}
        </p>
      ) : null}

      {step !== "live" && step !== "premium" ? (
        <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            className={buttonClasses({ variant: "ghost" })}
            onClick={goBack}
            disabled={step === "welcome" || pending}
          >
            Retour
          </button>
          <button
            type="button"
            className={buttonClasses({ variant: "primary" })}
            onClick={goNext}
            disabled={pending}
          >
            {pending ? "Enregistrement…" : step === "welcome" ? "Commencer" : "Continuer"}
          </button>
        </div>
      ) : null}

      {step === "premium" ? (
        <div className="mt-6">
          <button
            type="button"
            className={buttonClasses({ variant: "ghost" })}
            onClick={goBack}
            disabled={pending}
          >
            Retour
          </button>
        </div>
      ) : null}
    </div>
  );
}
