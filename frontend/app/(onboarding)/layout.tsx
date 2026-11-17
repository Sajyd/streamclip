import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/ui/primitives";

export default function OnboardingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="page-glow flex min-h-full flex-1 flex-col">
      <header className="border-b border-white/5 bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex h-14 w-full max-w-3xl items-center px-4 sm:px-6">
          <Link href="/onboarding" aria-label="STREAMCLIP">
            <Logo />
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-8 sm:px-6 sm:py-12">{children}</main>
    </div>
  );
}
