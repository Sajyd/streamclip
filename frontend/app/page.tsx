import { Suspense } from "react";

import { ClipIllustration } from "@/components/marketing/clip-illustration";
import { AvailabilityNotice, Pricing, PricingFallback } from "@/components/marketing/pricing";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/button";
import { Notice } from "@/components/ui/primitives";

const STEPS = [
  {
    title: "Ajoutez STREAMCLIP dans OBS",
    body: "Serveur rtmp://rtmp.streamclip.fr/live + votre clé secrète, en destination supplémentaire. Votre diffusion Twitch / YouTube / Kick ne change pas.",
  },
  {
    title: "Votre live est analysé en continu",
    body: "Dès le démarrage, votre instance dédiée analyse parole, réactions et image toutes les 5 minutes pour repérer les moments viraux.",
  },
  {
    title: "Les clips se préparent tout seuls",
    body: "Chaque moment fort est découpé (30–60 s), recadré en 9:16 et sous-titré, prêt pour Shorts, TikTok et Reels.",
  },
  {
    title: "Téléchargez ou publiez",
    body: "Retrouvez vos clips dans votre bibliothèque, téléchargez-les ou publiez-les sur vos réseaux.",
  },
];

const FEATURES = [
  {
    title: "Détection multimodale",
    body: "Transcription, intonation, rires, action à l'écran et type de contenu : un moment fort se reconnaît à plusieurs signaux, pas à un simple pic de volume.",
  },
  {
    title: "Cadrage vertical automatique",
    body: "Gaming avec webcam, podcast à plusieurs voix, live IRL : le recadrage 9:16 s'adapte à ce qui se passe à l'image.",
  },
  {
    title: "Sous-titres intégrés",
    body: "Des sous-titres lisibles sur mobile, synchronisés mot à mot avec la parole.",
  },
  {
    title: "Des clips qui se tiennent",
    body: "Un début, un moment fort, une fin naturelle : jamais de coupe au milieu d'une phrase, et pas deux clips du même instant.",
  },
  {
    title: "Vos accès restent à vous",
    body: "Aucune clé de diffusion ni mot de passe Twitch, YouTube ou Kick n'est demandé. La publication passe par les autorisations officielles de chaque plateforme.",
  },
  {
    title: "Consommation maîtrisée",
    body: "Seule la durée réellement traitée est décomptée. Vous êtes prévenu à 80 % de votre quota et le traitement s'arrête à 100 %, sans dépassement facturé.",
  },
];

const QUESTIONS = [
  {
    question: "Dois-je communiquer ma clé de stream ou mes mots de passe ?",
    answer:
      "Non. Vous envoyez une copie de votre flux vers STREAMCLIP avec une clé d'ingestion qui lui est propre. Nous ne demandons jamais vos clés de diffusion ni les mots de passe de vos comptes Twitch, YouTube, Kick ou de vos réseaux sociaux.",
  },
  {
    question: "Comment ma consommation est-elle comptée ?",
    answer:
      "Seule la durée de live effectivement traitée est décomptée de votre quota mensuel. Un live interrompu ou un flux non reçu n'est pas compté.",
  },
  {
    question: "Que se passe-t-il quand j'atteins mon quota ?",
    answer:
      "Vous recevez une alerte à 80 % de votre quota. À 100 %, le traitement s'arrête jusqu'au début de la période suivante : il n'y a jamais de dépassement facturé. Vous pouvez passer à une offre supérieure à tout moment.",
  },
  {
    question: "Puis-je changer d'offre ou résilier ?",
    answer:
      "Oui, depuis votre espace. Le passage à une offre supérieure est immédiat, le passage à une offre inférieure prend effet à la fin de la période déjà payée, et une résiliation vous laisse l'accès jusqu'à cette date.",
  },
  {
    question: "Comment connecter OBS ou Streamlabs ?",
    answer:
      "Service = Personnalisé, serveur = rtmp://rtmp.streamclip.fr/live, clé = celle affichée une seule fois dans votre espace. Au démarrage du live, STREAMCLIP vérifie votre abonnement et relaie le flux vers votre instance EC2 dédiée.",
  },
  {
    question: "La publication sur les réseaux est-elle automatique ?",
    answer:
      "Pour l'instant, téléchargez vos clips et publiez-les vous-même. La connexion OAuth officielle (YouTube, TikTok, Instagram) arrivera ensuite ; vos préférences sont déjà enregistrées à l'onboarding.",
  },
  {
    question: "Que deviennent mes vidéos et mes données ?",
    answer:
      "Les lives complets ne sont pas conservés : seuls les extraits nécessaires à la préparation des clips sont gardés temporairement, puis supprimés. Vous pouvez exporter vos données ou supprimer votre compte à tout moment depuis les paramètres.",
  },
];

function SectionHeading({
  eyebrow,
  title,
  intro,
}: {
  eyebrow: string;
  title: string;
  intro?: string;
}) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-xs font-medium tracking-[0.22em] text-brand-300 uppercase">{eyebrow}</p>
      <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h2>
      {intro ? <p className="mt-4 text-base leading-relaxed text-ink-300">{intro}</p> : null}
    </div>
  );
}

/** Confirmation shown after an account deletion (see deleteAccountAction). */
async function AccountDeletedNotice({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  if ((await searchParams).compte !== "supprime") {
    return null;
  }
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-6 sm:px-6">
      <Notice tone="ok" title="Votre compte est fermé">
        Votre abonnement éventuel est résilié et vos données sont en cours de suppression.
      </Notice>
    </div>
  );
}

export default function HomePage({ searchParams }: PageProps<"/">) {
  return (
    <div className="page-glow flex min-h-full flex-1 flex-col">
      <SiteHeader />
      <main id="contenu" className="flex-1">
        <Suspense fallback={null}>
          <AccountDeletedNotice searchParams={searchParams} />
        </Suspense>
        <Suspense fallback={null}>
          <AvailabilityNotice />
        </Suspense>

        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(ellipse_at_center,rgba(0,19,222,0.22),transparent_65%)]"
          />
          <div className="relative mx-auto grid w-full max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10 lg:py-24">
            <div className="animate-fade-up">
              <p className="text-sm font-medium tracking-[0.2em] text-brand-300 uppercase">
                STREAMCLIP
              </p>
              <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-[3.45rem] lg:leading-[1.06]">
                Vos lives deviennent des{" "}
                <span className="text-gradient">clips verticaux</span> prêts à publier
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-300">
                Connectez OBS en une URL RTMP, STREAMCLIP allume votre instance, analyse le live et
                livre des clips 9:16 sous-titrés pour YouTube Shorts, TikTok et Instagram.
              </p>
              <div className="mt-9 flex flex-wrap gap-3">
                <ButtonLink href="/register" size="lg">
                  Commencer gratuitement
                </ButtonLink>
                <ButtonLink href="/#tarifs" size="lg" variant="secondary">
                  Voir les offres
                </ButtonLink>
              </div>
              <p className="mt-5 text-sm text-ink-400">
                1&nbsp;h de traitement offerte / mois · abonnements sécurisés via Stripe · sans
                engagement
              </p>
            </div>
            <ClipIllustration />
          </div>
        </section>

        <section id="fonctionnement" className="scroll-mt-20 border-t border-white/5 py-20 sm:py-24">
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <SectionHeading
              eyebrow="Fonctionnement"
              title="Du direct au clip, sans montage"
              intro="Quatre étapes, dont une seule vous demande une action."
            />
            <ol className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, index) => (
                <li key={step.title} className="surface relative p-6">
                  <span className="flex size-9 items-center justify-center rounded-xl bg-brand-500/15 font-mono text-sm font-semibold text-brand-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-4 text-base font-semibold text-white">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-300">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="fonctionnalites" className="scroll-mt-20 border-t border-white/5 py-20 sm:py-24">
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <SectionHeading
              eyebrow="Fonctionnalités"
              title="Pensé pour les créateurs qui diffusent en direct"
              intro="Gaming, podcasts, interviews, discussions, lives IRL, événements ou musique."
            />
            <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature) => (
                <article key={feature.title} className="surface p-6 sm:p-7">
                  <div
                    aria-hidden
                    className="mb-4 h-1 w-10 rounded-full bg-gradient-to-r from-brand-400 to-flare-400"
                  />
                  <h3 className="font-semibold text-white">{feature.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-300">{feature.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="tarifs" className="scroll-mt-20 border-t border-white/5 py-20 sm:py-24">
          <div className="mx-auto w-full max-w-7xl px-4 sm:px-6">
            <SectionHeading
              eyebrow="Tarifs"
              title="Une offre pour chaque rythme de diffusion"
              intro="Commencez gratuitement, puis choisissez le volume d'heures qui vous convient."
            />
            <div className="mt-12">
              <Suspense fallback={<PricingFallback />}>
                <Pricing />
              </Suspense>
            </div>
          </div>
        </section>

        <section id="faq" className="scroll-mt-20 border-t border-white/5 py-20 sm:py-24">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
            <SectionHeading eyebrow="FAQ" title="Questions fréquentes" />
            <div className="surface mt-10 divide-y divide-white/10 overflow-hidden p-0">
              {QUESTIONS.map((item) => (
                <details key={item.question} className="group px-5 py-4 open:bg-white/[0.02]">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium text-white">
                    {item.question}
                    <span
                      aria-hidden
                      className="flex size-7 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-ink-900 text-brand-300 transition-transform group-open:rotate-45"
                    >
                      +
                    </span>
                  </summary>
                  <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-300">{item.answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="border-t border-white/5 py-20 sm:py-24">
          <div className="mx-auto w-full max-w-3xl px-4 text-center sm:px-6">
            <div className="surface relative overflow-hidden px-6 py-12 sm:px-10">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(0,19,222,0.28),transparent_60%)]"
              />
              <div className="relative">
                <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                  Prêt pour votre prochain live&nbsp;?
                </h2>
                <p className="mt-4 text-ink-300">
                  Compte gratuit en une minute, puis passez à une offre payante quand vous en avez
                  besoin — paiement sécurisé Stripe.
                </p>
                <ButtonLink href="/register" size="lg" className="mt-8">
                  Commencer gratuitement
                </ButtonLink>
              </div>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
  );
}
