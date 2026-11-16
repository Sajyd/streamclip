import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { registerAction } from "@/app/actions/auth";
import { RedirectIfSignedIn } from "@/components/auth/auth-helpers";
import { Checkbox, Field, Form, SubmitButton } from "@/components/ui/form";
import { PASSWORD_MIN_LENGTH } from "@/lib/constants";

export const metadata: Metadata = { title: "Créer un compte" };

export default function RegisterPage() {
  return (
    <>
      <Suspense fallback={null}>
        <RedirectIfSignedIn />
      </Suspense>
      <h1 className="text-2xl font-semibold tracking-tight text-white">Créer un compte</h1>
      <p className="mt-2 mb-6 text-sm text-ink-300">
        Offre gratuite : 1 heure de live par mois, sans carte bancaire.
      </p>
      <Form action={registerAction}>
        <Field
          name="display_name"
          label="Nom ou pseudo"
          autoComplete="nickname"
          maxLength={120}
          hint="Facultatif."
        />
        <Field name="email" type="email" label="Adresse e-mail" autoComplete="email" required />
        <Field
          name="password"
          type="password"
          label="Mot de passe"
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          required
          hint={`Au moins ${PASSWORD_MIN_LENGTH} caractères. Une phrase longue vaut mieux qu'un mot compliqué.`}
        />
        <Checkbox name="accept_terms" required>
          J&apos;accepte les{" "}
          <Link href="/legal/conditions" className="text-brand-300 hover:text-brand-200">
            conditions d&apos;utilisation
          </Link>{" "}
          et j&apos;ai lu la{" "}
          <Link href="/legal/confidentialite" className="text-brand-300 hover:text-brand-200">
            politique de confidentialité
          </Link>
          .
        </Checkbox>
        <SubmitButton className="w-full" pendingLabel="Création du compte…">
          Créer mon compte
        </SubmitButton>
      </Form>
      <p className="mt-6 text-sm text-ink-300">
        Déjà inscrit ?{" "}
        <Link href="/login" className="text-brand-300 hover:text-brand-200">
          Se connecter
        </Link>
      </p>
    </>
  );
}
