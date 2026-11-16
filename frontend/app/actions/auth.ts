"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import {
  failure,
  invalid,
  secret,
  success,
  text,
  type FormState,
} from "@/lib/form-state";
import { authorized } from "@/lib/mutations";
import { clearSession, readSession, safeNextPath, writeSession } from "@/lib/session";
import type { AuthResponse } from "@/types/api";

export async function loginAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const email = text(formData, "email");
  const password = secret(formData, "password");
  const values = { email };
  const fields: Record<string, string> = {};
  if (!email) fields.email = "Indiquez votre adresse e-mail.";
  if (!password) fields.password = "Indiquez votre mot de passe.";
  if (Object.keys(fields).length > 0) {
    return invalid(fields, values);
  }

  const result = await api<AuthResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
  if (!result.ok) {
    return failure(result.error, values);
  }
  writeSession(await cookies(), result.data.tokens);
  redirect(safeNextPath(formData.get("next")));
}

export async function registerAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const email = text(formData, "email");
  const displayName = text(formData, "display_name");
  const password = secret(formData, "password");
  const acceptTerms = formData.get("accept_terms") === "on";
  const values: Record<string, string> = { email, display_name: displayName };
  if (acceptTerms) values.accept_terms = "on";
  const fields: Record<string, string> = {};
  if (!email) fields.email = "Indiquez votre adresse e-mail.";
  if (!password) fields.password = "Choisissez un mot de passe.";
  if (!acceptTerms) fields.accept_terms = "Vous devez accepter les conditions pour créer un compte.";
  if (Object.keys(fields).length > 0) {
    return invalid(fields, values);
  }

  const result = await api<AuthResponse>("/auth/register", {
    method: "POST",
    body: {
      email,
      password,
      display_name: displayName || null,
      accept_terms: true,
    },
  });
  if (!result.ok) {
    return failure(result.error, values);
  }
  writeSession(await cookies(), result.data.tokens);
  redirect("/dashboard");
}

export async function logoutAction(): Promise<void> {
  const { access } = await readSession();
  if (access) {
    // Best effort: the cookies are cleared whatever the API answers.
    await api("/auth/logout", { method: "POST", token: access });
  }
  clearSession(await cookies());
  redirect("/");
}

export async function forgotPasswordAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const email = text(formData, "email");
  if (!email) {
    return invalid({ email: "Indiquez votre adresse e-mail." });
  }
  const result = await api("/auth/forgot-password", { method: "POST", body: { email } });
  if (!result.ok) {
    return failure(result.error, { email });
  }
  // Same answer whether or not an account exists for this address.
  return success(
    "Si un compte existe pour cette adresse, un e-mail contenant un lien de réinitialisation vient de lui être envoyé.",
  );
}

export async function resetPasswordAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const token = text(formData, "token");
  const password = secret(formData, "password");
  if (!token) {
    return { status: "error", message: "Ce lien est incomplet. Demandez-en un nouveau." };
  }
  if (!password) {
    return invalid({ password: "Choisissez un nouveau mot de passe." });
  }
  const result = await api("/auth/reset-password", {
    method: "POST",
    body: { token, new_password: password },
  });
  if (!result.ok) {
    return failure(result.error);
  }
  // Every session was revoked by the API: sign in again with the new password.
  clearSession(await cookies());
  redirect("/login?reason=password-reset");
}

export async function verifyEmailAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const token = text(formData, "token");
  if (!token) {
    return { status: "error", message: "Ce lien est incomplet. Demandez-en un nouveau." };
  }
  const result = await api("/auth/verify-email", { method: "POST", body: { token } });
  if (!result.ok) {
    return failure(result.error);
  }
  return success("Votre adresse e-mail est confirmée.");
}

export async function resendVerificationAction(): Promise<FormState> {
  const result = await authorized((token) =>
    api("/auth/resend-verification", { method: "POST", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  return success("Un nouvel e-mail de confirmation vient d'être envoyé.");
}
