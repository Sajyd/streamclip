import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page introuvable" };

export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center px-4 py-24 text-center">
        <p className="text-sm font-medium text-brand-300">Erreur 404</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Page introuvable</h1>
        <p className="mt-4 text-ink-300">Cette page n&apos;existe pas ou a été déplacée.</p>
        <ButtonLink href="/" className="mt-8">
          Retour à l&apos;accueil
        </ButtonLink>
      </main>
      <SiteFooter />
    </>
  );
}
