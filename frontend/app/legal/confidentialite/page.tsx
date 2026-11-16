import type { Metadata } from "next";

import { LegalPage, LegalSection, PublisherIdentity, publisher } from "@/components/legal/legal-page";

export const metadata: Metadata = {
  title: "Politique de confidentialité",
  description: "Les données traitées par STREAMCLIP AI, leur usage, leur durée de conservation et vos droits.",
};

export default function PrivacyPage() {
  return (
    <LegalPage title="Politique de confidentialité" updated="16 novembre 2026">
      <LegalSection title="1. Responsable du traitement">
        <PublisherIdentity />
      </LegalSection>

      <LegalSection title="2. Données traitées et finalités">
        <ul>
          <li>
            <strong>Compte</strong> : adresse e-mail, nom ou pseudo, mot de passe (conservé uniquement
            sous forme d&apos;empreinte Argon2id, jamais en clair), fuseau horaire, date d&apos;acceptation des
            conditions. Finalité : créer et sécuriser votre compte (exécution du contrat).
          </li>
          <li>
            <strong>Sessions et sécurité</strong> : adresse IP, navigateur, dates de connexion, journal
            des opérations sensibles. Finalité : protéger les comptes et détecter les abus (intérêt
            légitime).
          </li>
          <li>
            <strong>Abonnement</strong> : offre, état de l&apos;abonnement, identifiants techniques Stripe,
            durée de live consommée. Les données de carte sont saisies chez Stripe et ne nous sont
            jamais transmises. Finalité : facturation et gestion des quotas (exécution du contrat,
            obligations comptables).
          </li>
          <li>
            <strong>Contenus</strong> : lorsque le traitement des lives sera ouvert, le flux que vous
            envoyez, sa transcription et les clips produits, dans le seul but de vous fournir le
            service.
          </li>
        </ul>
        <p>
          Nous n&apos;utilisons aucun traceur publicitaire ni outil de mesure d&apos;audience tiers. Les seuls
          cookies déposés sont les deux cookies de session strictement nécessaires à la connexion.
        </p>
      </LegalSection>

      <LegalSection title="3. Sous-traitants et lieux d'hébergement">
        <ul>
          <li>Vercel — hébergement de l&apos;application (exécution à Londres, Royaume-Uni).</li>
          <li>Neon — base de données PostgreSQL (Londres, Royaume-Uni).</li>
          <li>Amazon Web Services — stockage chiffré des fichiers (Stockholm, Suède).</li>
          <li>Stripe — paiement, facturation et prévention de la fraude.</li>
        </ul>
        <p>
          Lorsqu&apos;une donnée est traitée en dehors de l&apos;Union européenne, le transfert repose sur une
          décision d&apos;adéquation de la Commission européenne ou sur des clauses contractuelles types.
          Vos données ne sont ni vendues, ni utilisées pour entraîner des modèles d&apos;intelligence
          artificielle.
        </p>
      </LegalSection>

      <LegalSection title="4. Durées de conservation">
        <ul>
          <li>Données du compte : jusqu&apos;à la suppression du compte.</li>
          <li>Sessions : 30 jours après leur expiration ou leur révocation.</li>
          <li>Adresses IP et navigateurs du journal de sécurité : effacés après 12 mois.</li>
          <li>Exports de données : fichiers supprimés 7 jours après leur création.</li>
          <li>
            Factures et pièces comptables : conservées par notre prestataire de paiement pendant la
            durée imposée par la loi.
          </li>
        </ul>
      </LegalSection>

      <LegalSection title="5. Vos droits">
        <p>
          Vous disposez des droits d&apos;accès, de rectification, d&apos;effacement, de limitation,
          d&apos;opposition et de portabilité. Deux d&apos;entre eux s&apos;exercent directement depuis les
          paramètres de votre compte :
        </p>
        <ul>
          <li><strong>Portabilité</strong> : « Demander un export » fournit une copie de vos données au format JSON.</li>
          <li>
            <strong>Effacement</strong> : « Supprimer mon compte » ferme le compte immédiatement, résilie
            l&apos;abonnement, puis efface votre espace, vos fichiers et vos données.
          </li>
        </ul>
        <p>
          {publisher.contact
            ? `Pour toute autre demande, écrivez à ${publisher.contact}. `
            : ""}
          Vous pouvez également introduire une réclamation auprès de la CNIL (www.cnil.fr).
        </p>
      </LegalSection>

      <LegalSection title="6. Sécurité">
        <ul>
          <li>Échanges chiffrés (HTTPS) et fichiers chiffrés au repos.</li>
          <li>Cloisonnement des données de chaque espace client au niveau de la base de données.</li>
          <li>Journalisation des opérations sensibles et limitation des tentatives de connexion.</li>
        </ul>
      </LegalSection>
    </LegalPage>
  );
}
