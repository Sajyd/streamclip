import type { Metadata } from "next";

import { ButtonLink } from "@/components/ui/button";

export const metadata: Metadata = { title: "Page introuvable" };

/**
 * The app shell already renders its navigation. The root not-found page also
 * includes the marketing header, so a missing app resource would show both.
 */
export default function AppNotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center py-16 text-center">
      <p className="text-sm font-medium text-brand-300">Erreur 404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white">Page introuvable</h1>
      <p className="mt-3 text-ink-300">Cette page n&apos;existe pas ou a été déplacée.</p>
      <ButtonLink href="/dashboard" className="mt-8">
        Retour au tableau de bord
      </ButtonLink>
    </div>
  );
}
