"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api";
import { failure, success, text, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";

export type SocialFormState = FormState & { authorizeUrl?: string };

export async function connectSocialAction(
  _previous: SocialFormState,
  formData: FormData,
): Promise<SocialFormState> {
  const platform = text(formData, "platform");
  const result = await authorized((token) =>
    api<{ authorize_url: string; platform: string }>(`/social/accounts/${platform}/connect`, {
      method: "POST",
      token,
      body: {},
    }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  return { ...success("Redirection…"), authorizeUrl: result.data.authorize_url };
}

export async function disconnectSocialAction(
  _previous: SocialFormState,
  formData: FormData,
): Promise<SocialFormState> {
  const accountId = text(formData, "account_id");
  const result = await authorized((token) =>
    api(`/social/accounts/${accountId}`, { method: "DELETE", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Compte déconnecté.");
}

export async function updateAutoPublishAction(
  _previous: SocialFormState,
  formData: FormData,
): Promise<SocialFormState> {
  const platforms = formData.getAll("platforms").map(String);
  const result = await authorized((token) =>
    api("/social/auto-publish", {
      method: "PUT",
      token,
      body: { platforms },
    }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Préférences de publication enregistrées.");
}
