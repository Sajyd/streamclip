import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { authorized } from "@/lib/mutations";

/**
 * Download of a data export: the API checks that the export belongs to the
 * caller's workspace, then issues a storage address valid for a few minutes.
 */
export async function GET(_request: Request, context: RouteContext<"/settings/exports/[id]">) {
  const { id } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) {
    redirect("/settings");
  }
  const result = await authorized((token) =>
    api<{ url: string }>(`/account/exports/${id}/download-url`, { token }),
  );
  if (!result.ok) {
    redirect("/settings");
  }
  redirect(result.data.url);
}
