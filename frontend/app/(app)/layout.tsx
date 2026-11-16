import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { logoutAction } from "@/app/actions/auth";
import { AppNav } from "@/components/app/app-nav";
import { buttonClasses } from "@/components/ui/button";
import { Logo, Skeleton } from "@/components/ui/primitives";
import { loadSession } from "@/lib/dal";

async function UserMenu() {
  const session = await loadSession();
  if (session.status !== "authenticated") {
    // The page itself redirects to sign-in or to the session refresh.
    return null;
  }
  const { user, organization } = session.me;
  return (
    <div className="flex items-center gap-3">
      {user.platform_role === "user" ? null : (
        <Link href="/admin/users" className="text-sm text-ink-300 hover:text-white">
          Administration
        </Link>
      )}
      <div className="hidden text-right leading-tight sm:block">
        <p className="max-w-48 truncate text-sm font-medium text-white">
          {user.display_name || user.email}
        </p>
        <p className="max-w-48 truncate text-xs text-ink-400">{organization.name}</p>
      </div>
      <form action={logoutAction}>
        <button type="submit" className={buttonClasses({ variant: "secondary", size: "sm" })}>
          Déconnexion
        </button>
      </form>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <header className="sticky top-0 z-40 border-b border-ink-800 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-6">
            <Link href="/dashboard" aria-label="STREAMCLIP AI — tableau de bord" className="shrink-0">
              <Logo />
            </Link>
            <div className="hidden md:block">
              <AppNav />
            </div>
          </div>
          <Suspense fallback={<Skeleton className="h-8 w-28" />}>
            <UserMenu />
          </Suspense>
        </div>
        <div className="border-t border-ink-800 px-4 py-2 md:hidden">
          <AppNav />
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}
