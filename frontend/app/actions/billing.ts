"use server";

import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { failure, text, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";

// Payment pages are hosted by Stripe: only these origins are followed.
const STRIPE_HOSTS = new Set(["checkout.stripe.com", "billing.stripe.com"]);

function stripeUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && STRIPE_HOSTS.has(url.hostname) ? url.toString() : null;
  } catch {
    return null;
  }
}

const UNEXPECTED: FormState = {
  status: "error",
  message: "La page de paiement n'a pas pu être ouverte. Réessayez dans un instant.",
};

/** Start a subscription: the price is chosen by the API from the plan code. */
export async function checkoutAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const planCode = text(formData, "plan_code");
  if (!/^[a-z0-9_]{1,32}$/.test(planCode)) {
    return UNEXPECTED;
  }
  const result = await authorized((token) =>
    api<{ url: string }>("/billing/checkout-session", {
      method: "POST",
      token,
      body: { plan_code: planCode },
    }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  const url = stripeUrl(result.data.url);
  if (!url) {
    return UNEXPECTED;
  }
  redirect(url);
}

/** Open the Stripe customer portal (plan change, payment method, invoices, cancellation). */
export async function portalAction(): Promise<FormState> {
  const result = await authorized((token) =>
    api<{ url: string }>("/billing/portal-session", { method: "POST", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  const url = stripeUrl(result.data.url);
  if (!url) {
    return UNEXPECTED;
  }
  redirect(url);
}
