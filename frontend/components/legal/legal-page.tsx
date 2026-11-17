import type { ReactNode } from "react";

import { SiteFooter, SiteHeader } from "@/components/marketing/site-chrome";

/** Publisher identity, supplied by the operator (never hard-coded). */
export const publisher = {
  identity: process.env.LEGAL_PUBLISHER?.trim() || null,
  contact: process.env.LEGAL_CONTACT_EMAIL?.trim() || null,
};

export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: ReactNode;
}) {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-14 sm:px-6">
        <h1 className="text-3xl font-semibold tracking-tight text-white">{title}</h1>
        <p className="mt-2 text-sm text-ink-400">Version du {updated}</p>
        <div className="mt-10 space-y-10">{children}</div>
      </main>
      <SiteFooter />
    </>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-ink-200 [&_a]:text-brand-300 [&_a:hover]:text-brand-200 [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5">
        {children}
      </div>
    </section>
  );
}

export function PublisherIdentity() {
  return (
    <>
      {publisher.identity ? (
        <p>Le service STREAMCLIP est édité par {publisher.identity}.</p>
      ) : (
        <p>
          Le service STREAMCLIP est actuellement proposé en accès anticipé. L&apos;identité complète
          de l&apos;éditeur (dénomination, adresse, immatriculation) sera publiée sur cette page avant
          toute ouverture commerciale.
        </p>
      )}
      {publisher.contact ? (
        <p>
          Contact : <a href={`mailto:${publisher.contact}`}>{publisher.contact}</a>.
        </p>
      ) : null}
    </>
  );
}
