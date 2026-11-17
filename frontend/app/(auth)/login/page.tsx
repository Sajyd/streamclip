import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { loginAction } from "@/app/actions/auth";
import {
  ForgotPasswordLink,
  QueryField,
  ReasonNotice,
  RedirectIfSignedIn,
} from "@/components/auth/auth-helpers";
import { Field, Form, SubmitButton } from "@/components/ui/form";

export const metadata: Metadata = { title: "Connexion" };

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <>
      <Suspense fallback={null}>
        <RedirectIfSignedIn />
      </Suspense>
      <h1 className="text-2xl font-semibold tracking-tight text-white">Connexion</h1>
      <p className="mt-2 mb-6 text-sm text-ink-300">Retrouvez votre espace STREAMCLIP.</p>
      <Suspense fallback={null}>
        <ReasonNotice searchParams={searchParams} />
      </Suspense>
      <Form action={loginAction}>
        <Suspense fallback={null}>
          <QueryField searchParams={searchParams} name="next" kind="path" />
        </Suspense>
        <Field name="email" type="email" label="Adresse e-mail" autoComplete="email" required />
        <Field
          name="password"
          type="password"
          label="Mot de passe"
          autoComplete="current-password"
          required
        />
        <SubmitButton className="w-full" pendingLabel="Connexion…">
          Se connecter
        </SubmitButton>
      </Form>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <Suspense fallback={null}>
          <ForgotPasswordLink />
        </Suspense>
        <p className="text-sm text-ink-300">
          Pas encore de compte ?{" "}
          <Link href="/register" className="text-brand-300 hover:text-brand-200">
            Créer un compte
          </Link>
        </p>
      </div>
    </>
  );
}
