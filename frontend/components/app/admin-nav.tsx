"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cx } from "@/lib/format";

const LINKS = [
  { href: "/admin", label: "Vue d'ensemble", exact: true },
  { href: "/admin/users", label: "Utilisateurs" },
  { href: "/admin/subscriptions", label: "Abonnements & MRR" },
  { href: "/admin/lives", label: "Lives" },
  { href: "/admin/clips", label: "Clips" },
  { href: "/admin/exports", label: "Exports" },
];

export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Administration" className="flex flex-wrap items-center gap-1">
      {LINKS.map((link) => {
        const active = link.exact
          ? pathname === link.href
          : pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "rounded-xl px-3 py-1.5 text-sm whitespace-nowrap transition-colors",
              active
                ? "bg-white/10 text-white"
                : "text-ink-300 hover:bg-white/5 hover:text-white",
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
