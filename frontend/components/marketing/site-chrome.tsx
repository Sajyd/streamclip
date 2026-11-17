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
    <header className="sticky top-0 z-40 border-b border-white/5 bg-ink-950/75 shadow-[0_8px_30px_-20px_rgba(0,19,222,0.4)] backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="STREAMCLIP — accueil" className="shrink-0">
          <Logo />
        </Link>
        <nav aria-label="Navigation principale" className="hidden items-center gap-1 md:flex">
          {NAVIGATION.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-lg px-3 py-1.5 text-sm text-ink-300 transition-colors hover:bg-white/5 hover:text-white"
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
    <footer className="mt-auto border-t border-white/5">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-12 sm:px-6 md:flex-row md:items-start md:justify-between">
        <div>
          <Logo />
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-ink-400">
            STREAMCLIP sort les meilleurs moments de votre live en clips verticaux sous-titrés,
            prêts à poster.
          </p>
        </div>
        <nav aria-label="Informations légales" className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <Link href="/legal/conditions" className="text-ink-400 transition-colors hover:text-white">
            Conditions d&apos;utilisation
          </Link>
          <Link
            href="/legal/confidentialite"
            className="text-ink-400 transition-colors hover:text-white"
          >
            Confidentialité
          </Link>
          <Link href="/#tarifs" className="text-ink-400 transition-colors hover:text-white">
            Tarifs
          </Link>
        </nav>
      </div>
    </footer>
  );
}
