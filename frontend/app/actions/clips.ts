"use server";

import { api } from "@/lib/api";
import { failure, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";

export type DownloadState = FormState & { url?: string };

export async function clipDownloadUrlAction(
  _previous: DownloadState,
  formData: FormData,
): Promise<DownloadState> {
  const clipId = String(formData.get("clip_id") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(clipId)) {
    return { status: "error", message: "Clip invalide." };
  }
  const result = await authorized((token) =>
    api<{ url: string }>(`/clips/${clipId}/download-url`, { token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  return { status: "success", message: "Téléchargement prêt.", url: result.data.url };
}
