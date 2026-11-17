import type { Metadata } from "next";
import { Suspense } from "react";

import { checkoutAction, portalAction } from "@/app/actions/billing";
import { AutoRefresh } from "@/components/app/auto-refresh";
import { PlanSummary, QuotaSummary } from "@/components/app/billing-widgets";
import { PlanCard, PlanGrid } from "@/components/plan-card";
import { Form, SubmitButton } from "@/components/ui/form";
import { Card, CardDescription, CardTitle, Notice, Skeleton } from "@/components/ui/primitives";
import { getBillingOverview, getPublicInfo, requireSession } from "@/lib/dal";
import type { BillingOverview, Plan } from "@/types/api";

export const metadata: Metadata = { title: "Abonnement" };

const PATH = "/billing";

type SearchParams = PageProps<"/billing">["searchParams"];

function CheckoutOutcome({ outcome, overview }: { outcome: string | undefined; overview: BillingOverview }) {
  if (outcome === "canceled") {
    return (
      <Notice tone="neutral" title="Paiement annulé">
        Aucun montant n&apos;a été débité. Vous pouvez choisir une offre quand vous le souhaitez.
      </Notice>
    );
  }
  if (outcome !== "success") {
    return null;
  }
  if (overview.is_paid) {
    return (
      <Notice tone="ok" title={`Votre offre ${overview.plan.name} est active`}>
        Merci ! Votre quota mensuel a été mis à jour.
      </Notice>
    );
  }
  // The subscription is activated by the payment provider's confirmation,
  // never by this return URL: the page waits for it.
  return (
    <>
      <AutoRefresh />
      <Notice tone="brand" title="Paiement reçu, activation en cours">
        Votre offre s&apos;active dès la confirmation du paiement, en général en quelques secondes.
        Cette page se met à jour toute seule.
      </Notice>
    </>
  );
}

function planAction(plan: Plan, overview: BillingOverview) {
  if (plan.code === overview.plan.code || overview.is_paid) {
    // Paid subscribers change plan in the customer portal (proration, schedule).
    return null;
  }
  if (!plan.purchasable || !overview.billing_available || !overview.can_manage) {
    return null;
  }
  return (
    <Form action={checkoutAction} className="space-y-2">
      <input type="hidden" name="plan_code" value={plan.code} />
      <SubmitButton className="w-full" pendingLabel="Ouverture du paiement…">
        Choisir {plan.name}
      </SubmitButton>
    </Form>
  );
}

async function Billing({ searchParams }: { searchParams: SearchParams }) {
  const { token, me } = await requireSession(PATH);
  const [overview, info, query] = await Promise.all([
    getBillingOverview(token, PATH),
    getPublicInfo(),
    searchParams,
  ]);
  const outcome = Array.isArray(query.checkout) ? query.checkout[0] : query.checkout;
  const timeZone = me.user.timezone;
  const canOpenPortal = overview.has_billing_account && overview.can_manage && overview.billing_available;
  // The API closes sales (not the portal) while the service is not open.
  const salesClosed =
    overview.billing_available && !overview.is_paid && info !== null && !info.catalog.items.some((plan) => plan.purchasable);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Abonnement</h1>
        <p className="mt-1 text-sm text-ink-300">Votre offre, votre quota et vos factures.</p>
      </div>

      <CheckoutOutcome outcome={outcome} overview={overview} />

      {overview.payment_failed ? (
        <Notice tone="danger" title="Le dernier paiement a échoué">
          Mettez à jour votre moyen de paiement pour conserver votre offre.
        </Notice>
      ) : null}

      {!overview.billing_available ? (
        <Notice tone="warn" title="Paiement indisponible">
          La souscription en ligne n&apos;est pas activée sur cette plateforme pour le moment.
        </Notice>
      ) : salesClosed ? (
        <Notice tone="brand" title="Offres payantes temporairement fermées">
          Les abonnements payants ne sont pas proposés pour le moment. Votre compte reste sur
          l&apos;offre gratuite.
        </Notice>
      ) : overview.billing_test_mode ? (
        <Notice tone="warn" title="Stripe en mode test">
          Les clés Stripe de production ne sont pas encore configurées : aucune carte réelle
          n&apos;est débitée. Carte de test : 4242 4242 4242 4242.
        </Notice>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <PlanSummary overview={overview} timeZone={timeZone} />
        <QuotaSummary overview={overview} timeZone={timeZone} />
      </div>

      {canOpenPortal ? (
        <Card>
          <CardTitle>Gérer mon abonnement</CardTitle>
          <CardDescription>
            Changer d&apos;offre, mettre à jour le moyen de paiement, télécharger vos factures ou
            résilier : tout se fait sur l&apos;espace client sécurisé de Stripe, notre prestataire de
            paiement.
          </CardDescription>
          <Form action={portalAction} className="mt-4 space-y-2">
            <SubmitButton variant="secondary" pendingLabel="Ouverture…">
              Ouvrir l&apos;espace client
            </SubmitButton>
          </Form>
        </Card>
      ) : null}

      {!overview.can_manage ? (
        <Notice tone="neutral">
          Seul un administrateur de l&apos;espace peut modifier l&apos;abonnement.
        </Notice>
      ) : null}

      <section aria-labelledby="offres">
        <h2 id="offres" className="text-lg font-semibold text-white">
          Les offres
        </h2>
        <p className="mt-1 mb-5 text-sm text-ink-300">
          {overview.is_paid
            ? "Pour passer à une autre offre, ouvrez l'espace client : la montée en gamme est immédiate, la descente prend effet à la fin de la période payée."
            : "Prix TTC, sans engagement : vous pouvez résilier à tout moment."}
        </p>
        {info ? (
          <PlanGrid>
            {info.catalog.items.map((plan) => (
              <PlanCard
                key={plan.code}
                plan={plan}
                current={plan.code === overview.plan.code}
                highlighted={plan.code === overview.plan.code}
                action={planAction(plan, overview)}
              />
            ))}
          </PlanGrid>
        ) : (
          <Notice tone="warn">Le catalogue n&apos;a pas pu être chargé. Rechargez la page.</Notice>
        )}
      </section>
    </div>
  );
}

function BillingSkeleton() {
  return (
    <div className="space-y-6" aria-busy aria-label="Chargement de l'abonnement">
      <Skeleton className="h-10 w-48" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-56" />
        <Skeleton className="h-56" />
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}

export default function BillingPage({ searchParams }: PageProps<"/billing">) {
  return (
    <Suspense fallback={<BillingSkeleton />}>
      <Billing searchParams={searchParams} />
    </Suspense>
  );
}
