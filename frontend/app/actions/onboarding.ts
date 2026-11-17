"use server";

import { api } from "@/lib/api";
import { failure, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";
import type { Onboarding } from "@/types/api";

export type OnboardingPatch = {
  step?: string;
  referral_source?: string | null;
  usage?: string | null;
  software?: "obs" | "streamlabs" | null;
  social_platforms?: Array<"youtube" | "tiktok" | "instagram">;
  ingest_ready?: boolean;
  premium_choice?: "free" | "premium" | null;
  live_detected?: boolean;
  complete?: boolean;
};

export async function saveOnboardingAction(patch: OnboardingPatch): Promise<FormState & { onboarding?: Onboarding }> {
  const result = await authorized((token) =>
    api<Onboarding>("/onboarding", { method: "PATCH", token, body: patch }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  return { status: "success", message: "Progression enregistrée.", onboarding: result.data };
}

export async function completeOnboardingAction(
  patch: OnboardingPatch = {},
): Promise<FormState & { onboarding?: Onboarding }> {
  const result = await authorized((token) =>
    api<Onboarding>("/onboarding", {
      method: "PATCH",
      token,
      body: { ...patch, complete: true, step: "done" },
    }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  return { status: "success", message: "Onboarding terminé.", onboarding: result.data };
}
