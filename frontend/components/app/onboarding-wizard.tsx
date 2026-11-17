"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { checkoutAction } from "@/app/actions/billing";
import {
  completeOnboardingAction,
  saveOnboardingAction,
  type OnboardingPatch,
} from "@/app/actions/onboarding";
import { CopyField, StreamKeyManager } from "@/components/app/ingest-credentials";
import { LiveDetector } from "@/components/app/live-detector";
import {
  PluginConnectStep,
  PluginDownloadStep,
  PluginInstallStep,
  PluginVerifyStep,
  StreamlabsConnectStep,
  type Creds,
} from "@/components/app/obs-rtmp-guide";
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
  | "plugin-ask"
  | "plugin-download"
  | "plugin-install"
  | "plugin-verify"
  | "plugin-connect"
  | "streamlabs-setup"
  | "social"
  | "premium"
  | "live";

function buildSteps(
  software: "obs" | "streamlabs" | null,
  hasPlugin: boolean | null,
): StepId[] {
  const head: StepId[] = ["welcome", "referral", "usage", "software", "ingest-key"];
  const tail: StepId[] = ["social", "premium", "live"];

  if (software === "streamlabs") {
    return [...head, "streamlabs-setup", ...tail];
  }

  // OBS (default while software unknown: show ask only)
  const mid: StepId[] = ["plugin-ask"];
  if (hasPlugin === false) {
    mid.push("plugin-download", "plugin-install", "plugin-verify");
  }
  if (hasPlugin !== null) {
    mid.push("plugin-connect");
  }
  return [...head, ...mid, ...tail];
}

function resolveStep(raw: string, steps: StepId[]): StepId {
  if (raw === "obs-guide" || raw === "obs-setup") return "ingest-key";
  if (steps.includes(raw as StepId)) return raw as StepId;
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

function Progress({ step, steps }: { step: StepId; steps: StepId[] }) {
  const index = Math.max(0, steps.indexOf(step));
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between text-xs text-ink-400">
        <span>
          Étape {index + 1} / {steps.length}
        </span>
        <span>{Math.round(((index + 1) / steps.length) * 100)} %</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div
          className="h-full rounded-full bg-gradient-to-r from-brand-500 to-flare-400 transition-all duration-500"
          style={{ width: `${((index + 1) / steps.length) * 100}%` }}
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

function StepHeader({
  eyebrow,
  title,
  hint,
}: {
  eyebrow: string;
  title: string;
  hint?: string;
}) {
  return (
    <div>
      <p className="text-xs font-medium tracking-[0.16em] text-ink-400 uppercase">{eyebrow}</p>
      <CardTitle className="mt-2 text-xl sm:text-2xl">{title}</CardTitle>
      {hint ? <CardDescription className="mt-2 max-w-xl">{hint}</CardDescription> : null}
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
  const [referral, setReferral] = useState<string | null>(initial.referral_source);
  const [usage, setUsage] = useState<string | null>(initial.usage);
  const [software, setSoftware] = useState<"obs" | "streamlabs" | null>(initial.software);
  const [hasPlugin, setHasPlugin] = useState<boolean | null>(null);
  const [socials, setSocials] = useState<Array<"youtube" | "tiktok" | "instagram">>(
    initial.social_platforms,
  );
  /** Clear secret kept only in memory until onboarding ends. */
  const [creds, setCreds] = useState<Creds | null>(null);

  const steps = useMemo(() => buildSteps(software, hasPlugin), [software, hasPlugin]);
  const [step, setStep] = useState<StepId>(() =>
    initial.completed ? "live" : resolveStep(initial.step, buildSteps(initial.software, null)),
  );

  function captureKey(key: StreamKey) {
    const server = key.rtmps_url ?? ingestRtmpUrl;
    if (!key.stream_key || !server) return;
    setCreds({ server, streamKey: key.stream_key });
  }

  function wipeSecret() {
    setCreds(null);
  }

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
    const index = steps.indexOf(step);
    const next = steps[Math.min(index + 1, steps.length - 1)] ?? "live";

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
      if (!ingestKey && !creds) {
        setError("Créez votre clé pour continuer.");
        return;
      }
      if (!creds) {
        setError("Affichez le secret (créer ou régénérer) pour le garder sous la main.");
        return;
      }
      const afterKey: StepId = software === "streamlabs" ? "streamlabs-setup" : "plugin-ask";
      persist({ step: afterKey, ingest_ready: true, software: software ?? "obs" }, afterKey);
      return;
    }
    if (step === "plugin-ask") {
      setError("Répondez oui ou non pour continuer.");
      return;
    }
    if (
      step === "plugin-download" ||
      step === "plugin-install" ||
      step === "plugin-verify" ||
      step === "plugin-connect" ||
      step === "streamlabs-setup"
    ) {
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

  function answerPlugin(installed: boolean) {
    setHasPlugin(installed);
    setError(null);
    const next: StepId = installed ? "plugin-connect" : "plugin-download";
    persist({ step: next, ingest_ready: true }, next);
  }

  function goBack() {
    const index = steps.indexOf(step);
    if (index <= 0) return;
    // Leaving plugin path resets the ask so progress recalculates cleanly
    if (step === "plugin-connect" || step === "plugin-download") {
      setHasPlugin(null);
      setStep("plugin-ask");
      return;
    }
    const previous = steps[index - 1];
    if (!previous) return;
    setError(null);
    setStep(previous);
  }

  function finish(liveDetected = false) {
    setError(null);
    wipeSecret();
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

  return (
    <div className="animate-fade-up">
      <Progress step={step} steps={steps} />

      {step === "welcome" ? (
        <Card className="relative overflow-hidden">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-brand-500/20 to-transparent" />
          <StepHeader
            eyebrow="Bienvenue"
            title={displayName ? `Salut ${displayName}` : "Salut"}
            hint="On branche votre live étape par étape. Twitch / YouTube ne changent pas."
          />
          <ul className="relative mt-6 grid gap-2 text-sm text-ink-200 sm:grid-cols-3">
            {["1. Clé", "2. Plugin OBS", "3. Live"].map((item) => (
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
                { id: "obs" as const, title: "OBS Studio", body: "Plugin Multiple RTMP" },
                { id: "streamlabs" as const, title: "Streamlabs", body: "Destination Custom RTMP" },
              ] as const
            ).map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  setSoftware(option.id);
                  setHasPlugin(null);
                }}
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
            eyebrow="Clé STREAMCLIP"
            title="Créez votre clé"
            hint="Un clic. Le serveur et la clé restent visibles jusqu’à la fin de l’onboarding."
          />
          {creds ? (
            <div className="mt-6 space-y-3 rounded-2xl border border-ok-500/30 bg-ok-500/10 p-4">
              <p className="text-sm font-semibold text-ok-400">Clé prête — copiez-la</p>
              <CopyField label="Serveur RTMP" value={creds.server} />
              <CopyField label="Clé secrète" value={creds.streamKey} />
            </div>
          ) : (
            <div className="mt-6">
              <StreamKeyManager
                canManage={canManage}
                ingestOnline={ingestOnline}
                rtmpUrl={ingestRtmpUrl}
                existingKey={ingestKey}
                defaultLabel={software === "streamlabs" ? "Streamlabs" : "OBS"}
                onIssued={captureKey}
                compact
              />
            </div>
          )}
        </Card>
      ) : null}

      {step === "plugin-ask" ? (
        <Card>
          <StepHeader
            eyebrow="Multiple RTMP"
            title="Avez-vous déjà le plugin Multiple RTMP ?"
            hint="Il s’appelle aussi « Multiple RTMP Outputs » dans OBS."
          />
          <div className="mt-6 grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => answerPlugin(true)}
              className="rounded-3xl border border-white/10 bg-ink-950/50 p-5 text-left transition-all hover:border-brand-400/50 hover:bg-brand-500/10"
            >
              <p className="text-lg font-semibold text-white">Oui, déjà installé</p>
              <p className="mt-1 text-sm text-ink-400">On passe direct à STREAMCLIP</p>
            </button>
            <button
              type="button"
              onClick={() => answerPlugin(false)}
              className="rounded-3xl border border-white/10 bg-ink-950/50 p-5 text-left transition-all hover:border-brand-400/50 hover:bg-brand-500/10"
            >
              <p className="text-lg font-semibold text-white">Non, on l’installe</p>
              <p className="mt-1 text-sm text-ink-400">3 étapes courtes + collage de la clé</p>
            </button>
          </div>
        </Card>
      ) : null}

      {step === "plugin-download" ? (
        <Card>
          <StepHeader eyebrow="Installation · 1/3" title="Téléchargement" />
          <div className="mt-6">
            <PluginDownloadStep />
          </div>
        </Card>
      ) : null}

      {step === "plugin-install" ? (
        <Card>
          <StepHeader eyebrow="Installation · 2/3" title="Installation" />
          <div className="mt-6">
            <PluginInstallStep />
          </div>
        </Card>
      ) : null}

      {step === "plugin-verify" ? (
        <Card>
          <StepHeader eyebrow="Installation · 3/3" title="Vérification" />
          <div className="mt-6">
            <PluginVerifyStep />
          </div>
        </Card>
      ) : null}

      {step === "plugin-connect" ? (
        <Card>
          <StepHeader
            eyebrow="Connexion"
            title="Collez serveur + clé dans OBS"
            hint="Le bandeau jaune ci-dessus reste disponible."
          />
          <div className="mt-6">
            <PluginConnectStep creds={creds} />
          </div>
        </Card>
      ) : null}

      {step === "streamlabs-setup" ? (
        <Card>
          <StepHeader eyebrow="Streamlabs" title="Ajoutez STREAMCLIP" />
          <div className="mt-6">
            <StreamlabsConnectStep creds={creds} />
          </div>
        </Card>
      ) : null}

      {step === "social" ? (
        <Card>
          <StepHeader
            eyebrow="Réseaux"
            title="Où publiez-vous ?"
            hint="Optionnel — vous pourrez télécharger vos clips."
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
                    onClick={() => {
                      wipeSecret();
                      persist({ premium_choice: "free", step: "live" }, "live");
                    }}
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
                      onClick={() => {
                        wipeSecret();
                        persist({ premium_choice: "free", step: "live" }, "live");
                      }}
                    >
                      Continuer
                    </button>
                  ) : (
                    <Form
                      action={checkoutAction}
                      className="space-y-2"
                      onSubmit={() => {
                        wipeSecret();
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
            onClick={() => {
              wipeSecret();
              persist({ premium_choice: "free", step: "live" }, "live");
            }}
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
            hint="Démarrez dans votre logiciel. On détecte le signal automatiquement."
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
                  Boolean(sessions.some((s) => s.status === "live" || s.status === "pending")),
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

      {step !== "live" && step !== "premium" && step !== "plugin-ask" ? (
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
                  ? "Continuer avec cette clé"
                  : step === "plugin-connect" || step === "streamlabs-setup"
                    ? "C’est branché"
                    : step === "plugin-download"
                      ? "Fichier téléchargé"
                      : step === "plugin-install"
                        ? "Plugin installé"
                        : step === "plugin-verify"
                          ? "Panneau OK"
                          : "Continuer"}
          </button>
        </div>
      ) : null}

      {step === "premium" || step === "plugin-ask" ? (
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
