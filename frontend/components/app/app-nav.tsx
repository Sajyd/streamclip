"use client";

import { usePathname } from "next/navigation";

import { cx } from "@/lib/format";

const LINKS = [
  { href: "/dashboard", label: "Tableau de bord" },
  { href: "/live", label: "Live" },
  { href: "/highlights", label: "Highlights" },
  { href: "/clips", label: "Clips" },
  { href: "/calendar", label: "Calendrier" },
  { href: "/guide", label: "Guide" },
  { href: "/billing", label: "Abonnement" },
  { href: "/settings", label: "Paramètres" },
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Navigation de l'espace" className="flex items-center gap-1 overflow-x-auto">
      {LINKS.map((link) => {
        const active = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <a
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "rounded-xl px-3.5 py-1.5 text-sm whitespace-nowrap transition-colors",
              active
                ? "bg-white/10 text-white"
                : "text-ink-300 hover:bg-white/5 hover:text-white",
            )}
          >
            {link.label}
          </a>
        );
      })}
    </nav>
  );
}
