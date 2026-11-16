import type { Metadata } from "next";

import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";
import { ButtonLink } from "@/components/ui/button";

export const metadata: Metadata = { title: "Service indisponible", robots: { index: false } };

export default function UnavailablePage() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center px-4 py-24 text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-white">
          Service momentanément indisponible
        </h1>
        <p className="mt-4 text-ink-300">
          Nous n&apos;arrivons pas à joindre nos serveurs. Votre session est conservée : réessayez
          dans un instant.
        </p>
        <ButtonLink href="/dashboard" className="mt-8">
          Réessayer
        </ButtonLink>
      </main>
      <SiteFooter />
    </>
  );
}
