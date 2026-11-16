"use server";

import { refresh } from "next/cache";

import { api } from "@/lib/api";
import { failure, success, text, type FormState } from "@/lib/form-state";
import { authorized } from "@/lib/mutations";
import type { StreamKey } from "@/types/api";

export type IssueKeyState = FormState & { key?: StreamKey };

export async function issueIngestKeyAction(
  _previous: IssueKeyState,
  formData: FormData,
): Promise<IssueKeyState> {
  const label = text(formData, "label");
  const result = await authorized((token) =>
    api<StreamKey>("/ingest/key", {
      method: "POST",
      token,
      body: { label },
    }),
  );
  if (!result.ok) {
    return failure(result.error, { label });
  }
  // Do not refresh here: a remount would drop the one-time clear secret.
  return {
    ...success(
      result.data.stream_key
        ? "Clé créée. Copiez-la maintenant : elle ne sera plus réaffichée."
        : "Clé créée.",
    ),
    key: result.data,
  };
}

export async function rotateIngestKeyAction(
  _previous: IssueKeyState,
  formData: FormData,
): Promise<IssueKeyState> {
  const label = text(formData, "label");
  const result = await authorized((token) =>
    api<StreamKey>("/ingest/key/rotate", {
      method: "POST",
      token,
      body: { label },
    }),
  );
  if (!result.ok) {
    return failure(result.error, { label });
  }
  // Do not refresh here: a remount would drop the one-time clear secret.
  return {
    ...success("Nouvelle clé émise. L'ancienne ne fonctionne plus. Copiez la clé maintenant."),
    key: result.data,
  };
}

export async function revokeIngestKeyAction(): Promise<FormState> {
  const result = await authorized((token) =>
    api("/ingest/key", { method: "DELETE", token }),
  );
  if (!result.ok) {
    return failure(result.error);
  }
  refresh();
  return success("Clé d'ingestion révoquée.");
}
