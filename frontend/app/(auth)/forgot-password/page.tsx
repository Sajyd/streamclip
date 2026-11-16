import type { Metadata } from "next";
import Link from "next/link";

import { forgotPasswordAction } from "@/app/actions/auth";
import { Field, Form, SubmitButton } from "@/components/ui/form";

export const metadata: Metadata = { title: "Mot de passe oublié" };

export default function ForgotPasswordPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-white">Mot de passe oublié</h1>
      <p className="mt-2 mb-6 text-sm text-ink-300">
        Indiquez l&apos;adresse e-mail de votre compte : nous vous enverrons un lien pour choisir un
        nouveau mot de passe.
      </p>
      <Form action={forgotPasswordAction}>
        <Field name="email" type="email" label="Adresse e-mail" autoComplete="email" required />
        <SubmitButton className="w-full" pendingLabel="Envoi…">
          Recevoir le lien
        </SubmitButton>
      </Form>
      <p className="mt-6 text-sm text-ink-300">
        <Link href="/login" className="text-brand-300 hover:text-brand-200">
          Retour à la connexion
        </Link>
      </p>
    </>
  );
}
