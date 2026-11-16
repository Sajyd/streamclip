import { Suspense } from "react";

import { ClipIllustration } from "@/components/marketing/clip-illustration";
import { AvailabilityNotice, Pricing, PricingFallback } from "@/components/marketing/pricing";
import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/button";
import { Notice } from "@/components/ui/primitives";

const STEPS = [
  {
    title: "Ajoutez STREAMCLIP AI dans OBS",
    body: "Copiez l'adresse RTMPS ou SRT et votre clé d'ingestion personnelle comme destination supplémentaire. Votre diffusion habituelle ne change pas.",
  },
  {
    title: "Votre live est analysé en continu",
    body: "La parole, les réactions, l'image et le contexte sont croisés pour repérer les moments qui méritent un clip.",
  },
  {
    title: "Les clips se préparent tout seuls",
    body: "Chaque moment fort est découpé au bon endroit, recadré en 9:16 et sous-titré, pour une durée de 45 à 60 secondes.",
  },
  {
    title: "Téléchargez ou publiez",
    body: "Retrouvez vos clips dans votre bibliothèque, téléchargez-les ou envoyez-les vers vos réseaux.",
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
      "Non. Vous envoyez une copie de votre flux vers STREAMCLIP AI avec une clé d'ingestion qui lui est propre. Nous ne demandons jamais vos clés de diffusion ni les mots de passe de vos comptes Twitch, YouTube, Kick ou de vos réseaux sociaux.",
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
    question: "La publication sur les réseaux est-elle automatique ?",
    answer:
      "Elle dépend de ce que chaque plateforme autorise à votre compte. Quand une publication directe n'est pas possible, le clip reste disponible au téléchargement.",
  },
  {
    question: "Que deviennent mes vidéos et mes données ?",
    answer:
      "Les lives complets ne sont pas conservés : seuls les extraits nécessaires à la préparation des clips sont gardés temporairement, puis supprimés. Vous pouvez exporter vos données ou supprimer votre compte à tout moment depuis les paramètres.",
  },
];

function SectionHeading({ eyebrow, title, intro }: { eyebrow: string; title: string; intro?: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-sm font-semibold uppercase tracking-widest text-brand-300">{eyebrow}</p>
      <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h2>
      {intro ? <p className="mt-4 text-ink-300">{intro}</p> : null}
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
    <>
      <SiteHeader />
      <main id="contenu" className="flex-1">
        <Suspense fallback={null}>
          <AccountDeletedNotice searchParams={searchParams} />
        </Suspense>
        <Suspense fallback={null}>
          <AvailabilityNotice />
        </Suspense>

        <section className="mx-auto grid w-full max-w-6xl items-center gap-14 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:py-24">
          <div>
            <h1 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-6xl">
              Vos lives deviennent des <span className="text-gradient">clips verticaux</span> prêts à
              publier
            </h1>
            <p className="mt-6 max-w-xl text-lg text-ink-300">
              STREAMCLIP AI suit votre live, repère les moments forts et prépare des clips 9:16
              sous-titrés pour YouTube Shorts, TikTok et Instagram.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <ButtonLink href="/register" size="lg">
                Créer mon compte gratuit
              </ButtonLink>
              <ButtonLink href="/#tarifs" size="lg" variant="secondary">
                Voir les offres
              </ButtonLink>
            </div>
            <p className="mt-4 text-sm text-ink-400">1 heure de live offerte chaque mois, sans carte bancaire.</p>
          </div>
          <ClipIllustration />
        </section>

        <section id="fonctionnement" className="scroll-mt-20 border-t border-ink-800 py-20">
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <SectionHeading
              eyebrow="Fonctionnement"
              title="Du direct au clip, sans montage"
              intro="Quatre étapes, dont une seule vous demande une action."
            />
            <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, index) => (
                <li key={step.title} className="surface p-6">
                  <span className="flex size-9 items-center justify-center rounded-full bg-brand-500/15 text-sm font-semibold text-brand-200">
                    {index + 1}
                  </span>
                  <h3 className="mt-4 font-semibold text-white">{step.title}</h3>
                  <p className="mt-2 text-sm text-ink-300">{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section id="fonctionnalites" className="scroll-mt-20 border-t border-ink-800 py-20">
          <div className="mx-auto w-full max-w-6xl px-4 sm:px-6">
            <SectionHeading
              eyebrow="Fonctionnalités"
              title="Pensé pour les créateurs qui diffusent en direct"
              intro="Gaming, podcasts, interviews, discussions, lives IRL, événements ou musique."
            />
            <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {FEATURES.map((feature) => (
                <article key={feature.title} className="surface p-6">
                  <h3 className="font-semibold text-white">{feature.title}</h3>
                  <p className="mt-2 text-sm text-ink-300">{feature.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="tarifs" className="scroll-mt-20 border-t border-ink-800 py-20">
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

        <section id="faq" className="scroll-mt-20 border-t border-ink-800 py-20">
          <div className="mx-auto w-full max-w-3xl px-4 sm:px-6">
            <SectionHeading eyebrow="FAQ" title="Questions fréquentes" />
            <div className="mt-10 space-y-3">
              {QUESTIONS.map((item) => (
                <details key={item.question} className="surface group px-5 py-4">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium text-white">
                    {item.question}
                    <span aria-hidden className="text-brand-300 transition-transform group-open:rotate-45">
                      +
                    </span>
                  </summary>
                  <p className="mt-3 text-sm text-ink-300">{item.answer}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="border-t border-ink-800 py-20">
          <div className="mx-auto w-full max-w-3xl px-4 text-center sm:px-6">
            <h2 className="text-3xl font-semibold tracking-tight text-white">
              Prêt à essayer sur votre prochain live ?
            </h2>
            <p className="mt-4 text-ink-300">Créez votre compte en une minute. Sans carte bancaire.</p>
            <ButtonLink href="/register" size="lg" className="mt-8">
              Créer mon compte gratuit
            </ButtonLink>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
