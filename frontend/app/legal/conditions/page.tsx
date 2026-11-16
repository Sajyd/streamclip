import type { Metadata } from "next";
import Link from "next/link";

import { LegalPage, LegalSection, PublisherIdentity } from "@/components/legal/legal-page";

export const metadata: Metadata = {
  title: "Conditions d'utilisation",
  description: "Conditions générales d'utilisation et de vente de STREAMCLIP AI.",
};

export default function TermsPage() {
  return (
    <LegalPage title="Conditions d'utilisation" updated="16 novembre 2026">
      <LegalSection title="1. Éditeur">
        <PublisherIdentity />
      </LegalSection>

      <LegalSection title="2. Objet du service">
        <p>
          STREAMCLIP AI est un service en ligne destiné aux créateurs de contenu : il reçoit une copie
          d&apos;un live que vous lui envoyez depuis votre logiciel de diffusion, en repère les moments
          forts et en tire des clips verticaux sous-titrés que vous pouvez télécharger ou publier.
        </p>
        <p>
          Le service s&apos;ouvre par étapes. Les fonctions effectivement disponibles sont indiquées sur
          le site et dans votre espace ; une fonction annoncée comme « pas encore ouverte » ne fait pas
          partie du service fourni.
        </p>
      </LegalSection>

      <LegalSection title="3. Compte">
        <ul>
          <li>Vous devez fournir une adresse e-mail valide et garder votre mot de passe confidentiel.</li>
          <li>Vous êtes responsable de l&apos;activité réalisée depuis votre compte.</li>
          <li>
            STREAMCLIP AI ne vous demande jamais le mot de passe ni la clé de diffusion de vos comptes
            Twitch, YouTube, Kick ou de vos réseaux sociaux.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="4. Offres, prix et paiement">
        <ul>
          <li>
            L&apos;offre gratuite et les offres payantes, leurs prix toutes taxes comprises et leurs
            quotas mensuels d&apos;heures de live sont présentés sur la <Link href="/#tarifs">page des offres</Link>.
          </li>
          <li>
            Les offres payantes sont des abonnements mensuels sans engagement, renouvelés
            automatiquement et payables d&apos;avance. Le paiement est opéré par Stripe ; STREAMCLIP AI
            ne voit ni ne conserve vos numéros de carte.
          </li>
          <li>
            Vous pouvez résilier à tout moment depuis votre espace : l&apos;offre reste active jusqu&apos;à
            la fin de la période déjà payée, puis le compte repasse sur l&apos;offre gratuite.
          </li>
          <li>
            Seule la durée de live effectivement traitée est décomptée du quota. À 100 % du quota, le
            traitement s&apos;arrête jusqu&apos;à la période suivante ou jusqu&apos;à un changement d&apos;offre.
          </li>
          <li>
            Si vous êtes un consommateur, vous disposez du droit de rétractation prévu par la loi, dans
            les conditions et limites qu&apos;elle fixe pour les services numériques.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Vos contenus">
        <ul>
          <li>Vous restez titulaire de tous les droits sur vos lives et sur les clips qui en sont tirés.</li>
          <li>
            Vous nous autorisez à traiter ces contenus dans le seul but de vous fournir le service
            (analyse, découpe, sous-titrage, stockage, mise à disposition).
          </li>
          <li>
            Vous garantissez disposer des droits nécessaires sur ce que vous diffusez (musique, images,
            personnes filmées) et respecter les règles des plateformes sur lesquelles vous publiez.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="6. Usages interdits">
        <ul>
          <li>Envoyer un flux dont vous n&apos;êtes pas l&apos;auteur ou que vous n&apos;avez pas le droit d&apos;exploiter.</li>
          <li>Diffuser des contenus illicites, ou portant atteinte aux droits de tiers.</li>
          <li>Tenter de contourner les quotas, la sécurité du service ou les règles d&apos;accès des plateformes tierces.</li>
          <li>Utiliser le service pour identifier des personnes à partir de leur visage ou de leur voix.</li>
        </ul>
        <p>Un compte qui enfreint ces règles peut être suspendu.</p>
      </LegalSection>

      <LegalSection title="7. Disponibilité et responsabilité">
        <p>
          Nous mettons en œuvre les moyens raisonnables pour assurer la disponibilité et la sécurité du
          service, sans garantir une disponibilité ininterrompue. La détection des moments forts repose
          sur une analyse automatisée : elle peut manquer un passage ou en retenir un sans intérêt, et
          il vous appartient de vérifier un clip avant de le publier.
        </p>
        <p>
          Rien dans ces conditions ne limite les droits que la loi reconnaît impérativement aux
          consommateurs.
        </p>
      </LegalSection>

      <LegalSection title="8. Suppression du compte">
        <p>
          Vous pouvez supprimer votre compte à tout moment depuis les paramètres : le compte est fermé
          immédiatement, l&apos;abonnement en cours est résilié et vos données sont effacées, comme le
          décrit la <Link href="/legal/confidentialite">politique de confidentialité</Link>.
        </p>
      </LegalSection>

      <LegalSection title="9. Évolution des conditions et droit applicable">
        <p>
          Ces conditions peuvent évoluer ; la version en vigueur est celle publiée sur cette page, et
          toute modification substantielle vous est notifiée. Elles sont soumises au droit français.
        </p>
      </LegalSection>
    </LegalPage>
  );
}
