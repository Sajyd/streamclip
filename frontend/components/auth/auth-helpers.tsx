import Link from "next/link";
import { redirect } from "next/navigation";
import { connection } from "next/server";

import { Notice } from "@/components/ui/primitives";
import { getPublicInfo } from "@/lib/dal";
import { readSession, safeNextPath } from "@/lib/session";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** Visitors who already have a session skip the sign-in pages. */
export async function RedirectIfSignedIn() {
  const { access, refresh } = await readSession();
  if (access || refresh) {
    redirect("/dashboard");
  }
  return null;
}

/** Hidden form field carrying a value from the URL (a token, a destination). */
export async function QueryField({
  searchParams,
  name,
  kind = "text",
}: {
  searchParams: SearchParams;
  name: string;
  kind?: "text" | "path";
}) {
  const raw = first((await searchParams)[name]);
  const value = kind === "path" ? safeNextPath(raw) : (raw ?? "");
  return <input type="hidden" name={name} value={value} />;
}

const REASONS: Record<string, { tone: "neutral" | "ok" | "warn"; text: string }> = {
  expired: { tone: "neutral", text: "Votre session a expiré. Connectez-vous à nouveau." },
  suspended: { tone: "warn", text: "Ce compte est suspendu. Contactez le support." },
  "password-reset": {
    tone: "ok",
    text: "Mot de passe modifié. Connectez-vous avec votre nouveau mot de passe.",
  },
  "signed-out": { tone: "ok", text: "Vous êtes déconnecté de tous vos appareils." },
};

export async function ReasonNotice({ searchParams }: { searchParams: SearchParams }) {
  const reason = REASONS[first((await searchParams).reason) ?? ""];
  if (!reason) {
    return null;
  }
  return (
    <Notice tone={reason.tone} className="mb-5">
      {reason.text}
    </Notice>
  );
}

/** Password recovery needs e-mail delivery: the link only shows when it works. */
export async function ForgotPasswordLink() {
  await connection();
  const info = await getPublicInfo();
  if (!info?.meta.capabilities.email_delivery) {
    return null;
  }
  return (
    <Link href="/forgot-password" className="text-sm text-brand-300 hover:text-brand-200">
      Mot de passe oublié ?
    </Link>
  );
}
