import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { ApiResult } from "@/lib/api";
import { accessTokenForMutation, clearSession, rotateSession } from "@/lib/session";

const SIGN_IN = "/login?reason=expired";

/**
 * Run an authenticated API call from a Server Action or a Route Handler.
 *
 * The session is refreshed when the access token is missing or refused; if
 * that fails the visitor is sent to the sign-in page. Authorisation itself
 * always happens in the API.
 */
export async function authorized<T>(
  call: (token: string) => Promise<ApiResult<T>>,
): Promise<ApiResult<T>> {
  const token = await accessTokenForMutation();
  if (!token) {
    redirect(SIGN_IN);
  }
  let result = await call(token);
  if (!result.ok && result.error.status === 401) {
    const rotation = await rotateSession();
    if (!rotation.ok) {
      redirect(SIGN_IN);
    }
    result = await call(rotation.token);
    if (!result.ok && result.error.status === 401) {
      clearSession(await cookies());
      redirect(SIGN_IN);
    }
  }
  return result;
}
