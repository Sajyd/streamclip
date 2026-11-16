"use client";

import { useEffect } from "react";

import { buttonClasses } from "@/components/ui/button";

export default function AppError({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto max-w-xl py-16 text-center">
      <h1 className="text-2xl font-semibold tracking-tight text-white">
        Cette page n&apos;a pas pu être chargée
      </h1>
      <p className="mt-3 text-ink-300">
        Le service est peut-être momentanément indisponible. Vos données ne sont pas affectées.
      </p>
      <button type="button" onClick={() => retry()} className={buttonClasses({ className: "mt-8" })}>
        Réessayer
      </button>
    </div>
  );
}
