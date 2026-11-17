import { connection } from "next/server";

import { PlanCard, PlanGrid } from "@/components/plan-card";
import { ButtonLink } from "@/components/ui/button";
import { Notice, Skeleton } from "@/components/ui/primitives";
import { getPublicInfo } from "@/lib/dal";

const HIGHLIGHTED_PLAN = "creator";

/** Catalogue read from the API at request time: prices are never hard-coded. */
export async function Pricing() {
  // The API is not reachable while the site is being built.
  await connection();
  const info = await getPublicInfo();
  if (!info) {
    return (
      <Notice tone="warn" title="Offres momentanément indisponibles">
        Le catalogue n&apos;a pas pu être chargé. Rechargez la page dans un instant.
      </Notice>
    );
  }
  const { catalog, meta } = info;
  const registrationOpen = meta.capabilities.registration_open;
  return (
    <div className="space-y-6">
      {meta.capabilities.billing_test_mode ? (
        <Notice tone="warn" title="Paiements en mode test">
          Les abonnements sont actuellement traités dans l&apos;environnement de test de notre
          prestataire de paiement : aucune carte réelle n&apos;est débitée.
        </Notice>
      ) : null}
      <PlanGrid>
        {catalog.items.map((plan) => (
          <PlanCard
            key={plan.code}
            plan={plan}
            highlighted={plan.code === HIGHLIGHTED_PLAN}
            action={
              registrationOpen ? (
                <ButtonLink
                  href="/register"
                  variant={plan.code === HIGHLIGHTED_PLAN ? "primary" : "secondary"}
                  className="w-full"
                >
                  {plan.price_cents === 0 ? "Commencer gratuitement" : `Choisir ${plan.name}`}
                </ButtonLink>
              ) : null
            }
          />
        ))}
      </PlanGrid>
      <p className="text-center text-xs text-ink-400">
        Prix TTC, TVA de {new Intl.NumberFormat("fr-FR").format(catalog.vat_rate_percent)} % incluse.
        Sans engagement : changez d&apos;offre ou résiliez à tout moment depuis votre espace.
      </p>
    </div>
  );
}

export function PricingFallback() {
  return (
    <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-5" aria-busy aria-label="Chargement des offres">
      {Array.from({ length: 5 }, (_, index) => (
        <Skeleton key={index} className="h-96 rounded-2xl" />
      ))}
    </div>
  );
}

/** Banner only while lives/clips are still gated off. */
export async function AvailabilityNotice() {
  await connection();
  const info = await getPublicInfo();
  if (!info || info.meta.capabilities.live_processing) {
    return null;
  }
  return (
    <div className="mx-auto w-full max-w-6xl px-4 pt-6 sm:px-6">
      <Notice tone="brand" title="Ouverture en cours">
        Le traitement des lives sera disponible sous peu. Vous pouvez déjà créer votre compte et
        préparer votre clé d&apos;ingestion.
      </Notice>
    </div>
  );
}
