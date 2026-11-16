"use server";

import { refresh } from "next/cache";
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
import { clearSession } from "@/lib/session";

export async function updateProfileAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const displayName = text(formData, "display_name");
  const timezone = text(formData, "timezone");
  const values = { display_name: displayName, timezone };
  const result = await authorized((token) =>
    api("/me", {
      method: "PATCH",
      token,
      body: { display_name: displayName || null, ...(timezone ? { timezone } : {}) },
    }),
  );
  if (!result.ok) {
    return failure(result.error, values);
  }
  refresh();
  return success("Profil mis à jour.");
}

export async function renameOrganizationAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const name = text(formData, "name");
  if (!name) {
    return invalid({ name: "Indiquez un nom." });
  }
  const result = await authorized((token) =>
    api("/organization", { method: "PATCH", token, body: { name } }),
  );
  if (!result.ok) {
    return failure(result.error, { name });
  }
  refresh();
  return success("Nom de l'espace mis à jour.");
}

export async function changePasswordAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const currentPassword = secret(formData, "current_password");
  const password = secret(formData, "password");
  const fields: Record<string, string> = {};
  if (!currentPassword) fields.current_password = "Indiquez votre mot de passe actuel.";
  if (!password) fields.password = "Choisissez un nouveau mot de passe.";
  if (Object.keys(fields).length > 0) {
    return invalid(fields);
  }
  const result = await authorized((token) =>
    api("/auth/change-password", {
      method: "POST",
      token,
      body: { current_password: currentPassword, new_password: password },
    }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Mot de passe modifié. Vos autres appareils ont été déconnectés.");
}

export async function revokeSessionAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const sessionId = text(formData, "session_id");
  if (!/^[0-9a-f-]{36}$/i.test(sessionId)) {
    return { status: "error", message: "Session inconnue." };
  }
  const result = await authorized((token) =>
    api(`/auth/sessions/${sessionId}`, { method: "DELETE", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Appareil déconnecté.");
}

export async function logoutEverywhereAction(): Promise<FormState> {
  const result = await authorized((token) => api("/auth/logout-all", { method: "POST", token }));
  if (!result.ok) {
    return failure(result.error);
  }
  clearSession(await cookies());
  redirect("/login?reason=signed-out");
}

export async function requestExportAction(): Promise<FormState> {
  const result = await authorized((token) => api("/account/exports", { method: "POST", token }));
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Export demandé. Il s'affiche dans la liste dès qu'il est prêt.");
}

export async function deleteAccountAction(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const password = secret(formData, "current_password");
  const confirmation = text(formData, "confirmation");
  const fields: Record<string, string> = {};
  if (!password) fields.current_password = "Indiquez votre mot de passe.";
  if (confirmation !== "SUPPRIMER") fields.confirmation = "Saisissez SUPPRIMER pour confirmer.";
  if (Object.keys(fields).length > 0) {
    return invalid(fields);
  }
  const result = await authorized((token) =>
    api("/account/delete", { method: "POST", token, body: { password } }),
  );
  if (!result.ok) {
    return failure(result.error, undefined, { password: "current_password" });
  }
  clearSession(await cookies());
  redirect("/?compte=supprime");
}

export async function markNotificationsReadAction(): Promise<FormState> {
  const result = await authorized((token) =>
    api("/notifications/read", { method: "POST", token, body: {} }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return { status: "idle" };
}
