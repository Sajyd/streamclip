import Link from "next/link";

import { ButtonLink } from "@/components/ui/button";
import { Logo } from "@/components/ui/primitives";

const NAVIGATION = [
  { href: "/#fonctionnement", label: "Fonctionnement" },
  { href: "/#fonctionnalites", label: "Fonctionnalités" },
  { href: "/#tarifs", label: "Tarifs" },
  { href: "/#faq", label: "FAQ" },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="STREAMCLIP AI — accueil">
          <Logo />
        </Link>
        <nav aria-label="Navigation principale" className="hidden items-center gap-7 md:flex">
          {NAVIGATION.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-sm text-ink-300 transition-colors hover:text-white"
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ButtonLink href="/login" variant="ghost" size="sm">
            Connexion
          </ButtonLink>
          <ButtonLink href="/register" size="sm">
            Créer un compte
          </ButtonLink>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-ink-800">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-10 sm:px-6 md:flex-row md:items-center md:justify-between">
        <div>
          <Logo />
          <p className="mt-2 max-w-sm text-sm text-ink-400">
            Vos lives analysés, vos meilleurs moments en clips verticaux sous-titrés.
          </p>
        </div>
        <nav aria-label="Informations légales" className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Link href="/legal/conditions" className="text-ink-300 hover:text-white">
            Conditions d&apos;utilisation
          </Link>
          <Link href="/legal/confidentialite" className="text-ink-300 hover:text-white">
            Confidentialité
          </Link>
          <Link href="/#tarifs" className="text-ink-300 hover:text-white">
            Tarifs
          </Link>
        </nav>
      </div>
    </footer>
  );
}
