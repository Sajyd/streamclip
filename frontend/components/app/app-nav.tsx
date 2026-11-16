"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cx } from "@/lib/format";

const LINKS = [
  { href: "/dashboard", label: "Tableau de bord" },
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
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors",
              active ? "bg-ink-800 text-white" : "text-ink-300 hover:bg-ink-850 hover:text-white",
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
