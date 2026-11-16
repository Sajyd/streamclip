import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/ui/primitives";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col items-center justify-center px-4 py-12">
      <Link href="/" aria-label="STREAMCLIP AI — accueil" className="mb-8">
        <Logo className="text-lg" />
      </Link>
      <main className="surface w-full max-w-md p-6 sm:p-8">{children}</main>
      <p className="mt-6 text-center text-xs text-ink-500">
        <Link href="/legal/conditions" className="hover:text-ink-300">
          Conditions d&apos;utilisation
        </Link>
        {" · "}
        <Link href="/legal/confidentialite" className="hover:text-ink-300">
          Confidentialité
        </Link>
      </p>
    </div>
  );
}
