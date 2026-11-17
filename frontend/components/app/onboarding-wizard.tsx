"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { checkoutAction } from "@/app/actions/billing";
import {
  completeOnboardingAction,
  saveOnboardingAction,
  type OnboardingPatch,
} from "@/app/actions/onboarding";
import { StreamKeyManager } from "@/components/app/ingest-credentials";
import { LiveDetector } from "@/components/app/live-detector";
import { ObsSetupGuide } from "@/components/app/obs-rtmp-guide";
import { PlanCard } from "@/components/plan-card";
import { buttonClasses } from "@/components/ui/button";
import { Form, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle } from "@/components/ui/primitives";
import { cx } from "@/lib/format";
import type { BillingOverview, Onboarding, Plan, StreamKey, StreamSession } from "@/types/api";

type StepId =
  | "welcome"
  | "referral"
  | "usage"
  | "software"
  | "ingest-key"
  | "obs-setup"
  | "social"
  | "premium"
  | "live";

const STEPS: StepId[] = [
  "welcome",
  "referral",
  "usage",
  "software",
  "ingest-key",
  "obs-setup",
  "social",
  "premium",
  "live",
];

/** Map legacy step ids saved before the split. */
function resolveStep(raw: string): StepId {
  if (raw === "obs-guide") return "ingest-key";
  if (STEPS.includes(raw as StepId)) return raw as StepId;
  return "welcome";
}

const REFERRALS = [
  { id: "youtube", label: "YouTube" },
  { id: "twitch", label: "Twitch" },
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram" },
  { id: "x", label: "X / Twitter" },
  { id: "discord", label: "Discord" },
  { id: "friend", label: "Un ami" },
  { id: "search", label: "Google" },
  { id: "other", label: "Autre" },
] as const;

const USAGES = [
  { id: "gaming", label: "Gaming" },
  { id: "vlog", label: "Vlog" },
  { id: "podcast", label: "Podcast" },
  { id: "concert", label: "Concert" },
  { id: "interview", label: "Interview" },
  { id: "just_chatting", label: "Just chatting" },
  { id: "irl", label: "IRL" },
  { id: "conference", label: "Conférence" },
  { id: "other", label: "Autre" },
] as const;

const SOCIALS = [
  { id: "youtube" as const, label: "YouTube" },
  { id: "tiktok" as const, label: "TikTok" },
  { id: "instagram" as const, label: "Instagram" },
];

function Progress({ step }: { step: StepId }) {
  const index = Math.max(0, STEPS.indexOf(step));
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between text-xs text-ink-400">
        <span>
          Étape {index + 1} / {STEPS.length}
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
  options: ReadonlyArray<{ id: string; label: string }>;
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
              "rounded-2xl border px-4 py-3.5 text-left text-sm font-medium transition-all",
              selected
                ? "border-brand-400/60 bg-brand-500/15 text-white shadow-lg shadow-brand-500/10"
                : "border-white/10 bg-ink-950/60 text-ink-200 hover:border-white/20 hover:text-white",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function StepHeader({ eyebrow, title, hint }: { eyebrow: string; title: string; hint?: string }) {
  return (
    <div>
      <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">{eyebrow}</p>
      <CardTitle className="mt-2 text-xl sm:text-2xl">{title}</CardTitle>
      {hint ? <CardDescription className="mt-2">{hint}</CardDescription> : null}
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
  socialOauth?: boolean;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<StepId>(
    initial.completed ? "live" : resolveStep(initial.step),
  );
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
        setError("Choisissez une option.");
        return;
      }
      persist({ step: next, referral_source: referral }, next);
      return;
    }
    if (step === "usage") {
      if (!usage) {
        setError("Choisissez un type de contenu.");
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
    if (step === "ingest-key") {
      if (!ingestKey) {
        setError("Créez votre clé pour continuer.");
        return;
      }
      persist({ step: next, ingest_ready: true, software: software ?? "obs" }, next);
      return;
    }
    if (step === "obs-setup") {
      persist({ step: next, ingest_ready: true }, next);
      return;
    }
    if (step === "social") {
      persist({ step: next, social_platforms: socials }, next);
      return;
    }
    if (step === "premium") {
      persist({ step: next, premium_choice: "free" }, next);
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
        setError(result.message ?? "Impossible de terminer.");
        return;
      }
      router.replace("/dashboard");
      router.refresh();
    });
  }

  const highlighted =
    plans.find((plan) => plan.code === "creator") ?? plans.find((p) => p.price_cents > 0);
  const freePlan = plans.find((plan) => plan.price_cents === 0);
  const softLabel = software === "streamlabs" ? "Streamlabs" : "OBS";

  return (
    <div className="animate-fade-up">
      <Progress step={step} />

      {step === "welcome" ? (
        <Card className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-brand-500/20 to-transparent" />
          <StepHeader
            eyebrow="Bienvenue"
            title={displayName ? `Salut ${displayName}` : "Salut"}
            hint="On branche votre live en quelques minutes. Vous gardez Twitch / YouTube — STREAMCLIP reçoit une copie."
          />
          <ul className="relative mt-6 grid gap-2 text-sm text-ink-200 sm:grid-cols-3">
            {["Clé STREAMCLIP", "Réglage OBS", "Clips prêts"].map((item) => (
              <li
                key={item}
                className="rounded-2xl border border-white/10 bg-ink-950/50 px-3 py-2.5 text-center font-medium"
              >
                {item}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {step === "referral" ? (
        <Card>
          <StepHeader eyebrow="Découverte" title="Comment nous avez-vous trouvé ?" />
          <div className="mt-6">
            <ChoiceGrid options={REFERRALS} value={referral} onChange={setReferral} columns={2} />
          </div>
        </Card>
      ) : null}

      {step === "usage" ? (
        <Card>
          <StepHeader eyebrow="Contenu" title="Vous streamez quoi ?" />
          <div className="mt-6">
            <ChoiceGrid options={USAGES} value={usage} onChange={setUsage} />
          </div>
        </Card>
      ) : null}

      {step === "software" ? (
        <Card>
          <StepHeader eyebrow="Logiciel" title="Quel outil utilisez-vous ?" />
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            {(
              [
                { id: "obs" as const, title: "OBS Studio", body: "Le plus courant" },
                { id: "streamlabs" as const, title: "Streamlabs", body: "All-in-one" },
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
                <p className="mt-1 text-sm text-ink-400">{option.body}</p>
              </button>
            ))}
          </div>
        </Card>
      ) : null}

      {step === "ingest-key" ? (
        <Card>
          <StepHeader
            eyebrow="Étape 5 · Clé"
            title="Créez votre clé STREAMCLIP"
            hint="Un clic. Copiez la clé tout de suite — elle ne s’affiche qu’une fois."
          />
          <div className="mt-6">
            <StreamKeyManager
              canManage={canManage}
              ingestOnline={ingestOnline}
              rtmpUrl={ingestRtmpUrl}
              existingKey={ingestKey}
              defaultLabel={software === "streamlabs" ? "Streamlabs" : "OBS"}
            />
          </div>
          {!canManage ? (
            <p className="mt-4 text-sm text-ink-400">
              Seul un admin de l’espace peut créer la clé.
            </p>
          ) : null}
        </Card>
      ) : null}

      {step === "obs-setup" ? (
        <Card>
          <StepHeader
            eyebrow={`Étape 6 · ${softLabel}`}
            title={`Branchez ${softLabel}`}
            hint="4 actions. Collez le serveur et la clé de l’étape 5."
          />
          <div className="mt-6">
            <ObsSetupGuide software={software ?? "obs"} />
          </div>
        </Card>
      ) : null}

      {step === "social" ? (
        <Card>
          <StepHeader
            eyebrow="Réseaux"
            title="Où publiez-vous ?"
            hint="Optionnel — vous pourrez toujours télécharger vos clips."
          />
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
                    "rounded-2xl border px-4 py-4 text-center text-sm font-medium transition-all",
                    selected
                      ? "border-brand-400/60 bg-brand-500/15 text-white"
                      : "border-white/10 text-ink-200 hover:border-white/20",
                  )}
                >
                  {platform.label}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="mt-4 text-sm text-ink-400 underline-offset-2 hover:text-ink-200 hover:underline"
            onClick={() => setSocials([])}
          >
            Je publierai à la main
          </button>
        </Card>
      ) : null}

      {step === "premium" ? (
        <div className="space-y-5">
          <Card>
            <StepHeader
              eyebrow="Offre"
              title="Free ou Premium ?"
              hint="Vous pouvez rester gratuit et changer plus tard."
            />
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
                    onClick={() => persist({ premium_choice: "free", step: "live" }, "live")}
                  >
                    Rester gratuit
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
                      Continuer
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
                      <SubmitButton className="w-full" pendingLabel="Ouverture…">
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
          <StepHeader
            eyebrow="Go live"
            title="Lancez votre live"
            hint={`Démarrez dans ${softLabel}. On détecte le signal tout seuls.`}
          />
          <div className="mt-6">
            <LiveDetector sessions={sessions} />
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={pending}
              className={buttonClasses({ variant: "primary" })}
              onClick={() =>
                finish(
                  Boolean(
                    sessions.some((s) => s.status === "live" || s.status === "pending"),
                  ),
                )
              }
            >
              {pending ? "Ouverture…" : "Ouvrir le tableau de bord"}
            </button>
            <button
              type="button"
              disabled={pending}
              className={buttonClasses({ variant: "ghost" })}
              onClick={() => finish(false)}
            >
              Plus tard
            </button>
          </div>
        </Card>
      ) : null}

      {error ? (
        <p
          role="alert"
          className="mt-4 rounded-lg border border-danger-500/40 bg-danger-500/10 px-3 py-2 text-sm text-danger-400"
        >
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
            {pending
              ? "…"
              : step === "welcome"
                ? "C’est parti"
                : step === "ingest-key"
                  ? "Clé créée, continuer"
                  : step === "obs-setup"
                    ? "C’est branché"
                    : "Continuer"}
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
