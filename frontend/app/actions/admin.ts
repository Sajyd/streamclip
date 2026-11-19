"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api";
import { failure, invalid, success, text, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";

const USER_ID = /^[0-9a-f-]{36}$/i;

export async function suspendUserAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const userId = text(formData, "user_id");
  const reason = text(formData, "reason");
  if (!USER_ID.test(userId)) {
    return { status: "error", message: "Utilisateur inconnu." };
  }
  if (reason.length < 3) {
    return invalid({ reason: "Indiquez le motif de la suspension." });
  }
  const result = await authorized((token) =>
    api(`/admin/users/${userId}/suspend`, { method: "POST", token, body: { reason } }),
  );
  if (!result.ok) {
    return failure(result.error, { reason });
  }
  refresh();
  return success("Compte suspendu.");
}

export async function stopLiveAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const liveId = text(formData, "live_id");
  if (!USER_ID.test(liveId)) {
    return { status: "error", message: "Live inconnu." };
  }
  const result = await authorized((token) =>
    api<{ message: string }>(`/admin/lives/${liveId}/stop`, { method: "POST", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success(result.data.message || "Live arrêté.");
}

export async function reactivateUserAction(_previous: FormState, formData: FormData): Promise<FormState> {
  const userId = text(formData, "user_id");
  if (!USER_ID.test(userId)) {
    return { status: "error", message: "Utilisateur inconnu." };
  }
  const result = await authorized((token) =>
    api(`/admin/users/${userId}/reactivate`, { method: "POST", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Compte réactivé.");
}
