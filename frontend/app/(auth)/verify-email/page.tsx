import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { verifyEmailAction } from "@/app/actions/auth";
import { QueryField } from "@/components/auth/auth-helpers";
import { Form, SubmitButton } from "@/components/ui/form";

export const metadata: Metadata = { title: "Confirmer mon adresse e-mail", robots: { index: false } };

export default function VerifyEmailPage({ searchParams }: PageProps<"/verify-email">) {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight text-white">
        Confirmer mon adresse e-mail
      </h1>
      <p className="mt-2 mb-6 text-sm text-ink-300">
        Cliquez sur le bouton ci-dessous pour confirmer que cette adresse est bien la vôtre.
      </p>
      {/* Confirmed by an explicit action, not by merely opening the link:
          mail scanners that pre-load links cannot consume the token. */}
      <Form action={verifyEmailAction}>
        <Suspense fallback={null}>
          <QueryField searchParams={searchParams} name="token" />
        </Suspense>
        <SubmitButton className="w-full" pendingLabel="Confirmation…">
          Confirmer mon adresse
        </SubmitButton>
      </Form>
      <p className="mt-6 text-sm text-ink-300">
        <Link href="/dashboard" className="text-brand-300 hover:text-brand-200">
          Aller à mon espace
        </Link>
      </p>
    </>
  );
}
