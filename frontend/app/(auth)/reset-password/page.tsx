import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { resetPasswordAction } from "@/app/actions/auth";
import { QueryField } from "@/components/auth/auth-helpers";
import { Field, Form, SubmitButton } from "@/components/ui/form";
import { PASSWORD_MIN_LENGTH } from "@/lib/constants";

export const metadata: Metadata = { title: "Nouveau mot de passe", robots: { index: false } };

export default function ResetPasswordPage({ searchParams }: PageProps<"/reset-password">) {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-white">Nouveau mot de passe</h1>
      <p className="mt-2 mb-6 text-sm text-ink-300">
        Choisissez un nouveau mot de passe. Tous vos appareils seront déconnectés.
      </p>
      <Form action={resetPasswordAction}>
        <Suspense fallback={null}>
          <QueryField searchParams={searchParams} name="token" />
        </Suspense>
        <Field
          name="password"
          type="password"
          label="Nouveau mot de passe"
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          required
          hint={`Au moins ${PASSWORD_MIN_LENGTH} caractères.`}
        />
        <SubmitButton className="w-full" pendingLabel="Enregistrement…">
          Enregistrer le mot de passe
        </SubmitButton>
      </Form>
      <p className="mt-6 text-sm text-ink-300">
        <Link href="/forgot-password" className="text-brand-300 hover:text-brand-200">
          Demander un nouveau lien
        </Link>
      </p>
    </>
  );
}
