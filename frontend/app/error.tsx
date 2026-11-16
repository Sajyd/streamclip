"use client";

import { useEffect } from "react";

import { buttonClasses } from "@/components/ui/button";

export default function RootError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center px-4 py-24 text-center">
      <h1 className="text-3xl font-semibold tracking-tight text-white">Une erreur est survenue</h1>
      <p className="mt-4 text-ink-300">
        La page n&apos;a pas pu être affichée. Réessayez ; si le problème persiste, revenez dans
        quelques minutes.
      </p>
      <button type="button" onClick={() => retry()} className={buttonClasses({ className: "mt-8" })}>
        Réessayer
      </button>
    </main>
  );
}
