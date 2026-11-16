import "server-only";

import { headers } from "next/headers";

/**
 * Server-side client of the STREAMCLIP AI API.
 *
 * The browser never talks to the API: every call goes through this module,
 * running on the web server (backend-for-frontend). It authenticates itself
 * with a shared secret, which lets the API trust the visitor's IP address we
 * forward for rate limiting and audit.
 */

export type ApiError = {
  status: number;
  code: string;
  message: string;
  /** Field name -> message, for validation errors. */
  fields: Record<string, string>;
};

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string;
  /** Forward the visitor's address and user agent (reads the incoming request). */
  forwardClient?: boolean;
};

const API_PREFIX = "/api/v1";
const TIMEOUT_MS = 15_000;

const UNAVAILABLE: ApiError = {
  status: 503,
  code: "api_unreachable",
  message: "Le service est momentanément indisponible. Réessayez dans un instant.",
  fields: {},
};

const FIELD_MESSAGES: Record<string, string> = {
  missing: "Ce champ est obligatoire.",
  string_too_short: "Cette valeur est trop courte.",
  string_too_long: "Cette valeur est trop longue.",
  extra_forbidden: "Ce champ n'est pas accepté.",
};

function baseUrl(): string {
  // On Vercel this is the private binding to the API service; locally, the
  // address of the API started with uvicorn.
  const url = process.env.API_INTERNAL_URL;
  if (!url) {
    throw new Error("API_INTERNAL_URL is not configured");
  }
  return url;
}

async function clientHeaders(): Promise<Record<string, string>> {
  const incoming = await headers();
  const forwarded: Record<string, string> = {};
  // Set by the hosting platform's edge, not by the visitor.
  const ip =
    incoming.get("x-real-ip") ?? incoming.get("x-forwarded-for")?.split(",")[0]?.trim() ?? null;
  if (ip) {
    forwarded["x-streamclip-client-ip"] = ip;
  } else if (process.env.NODE_ENV !== "production") {
    forwarded["x-streamclip-client-ip"] = "127.0.0.1";
  }
  const userAgent = incoming.get("user-agent");
  if (userAgent) {
    forwarded["x-streamclip-client-ua"] = userAgent.slice(0, 400);
  }
  return forwarded;
}

function parseError(status: number, payload: unknown): ApiError {
  const error = (payload as { error?: Record<string, unknown> } | null)?.error;
  if (!error || typeof error.code !== "string") {
    return { ...UNAVAILABLE, status };
  }
  const fields: Record<string, string> = {};
  const details = error.details as { fields?: unknown } | null | undefined;
  if (Array.isArray(details?.fields)) {
    for (const item of details.fields as { field?: string; type?: string }[]) {
      if (item.field) {
        fields[item.field] = FIELD_MESSAGES[item.type ?? ""] ?? "Cette valeur n'est pas valide.";
      }
    }
  }
  return {
    status,
    code: error.code,
    message: typeof error.message === "string" ? error.message : UNAVAILABLE.message,
    fields,
  };
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  const { method = "GET", body, token, forwardClient = true } = options;
  const requestHeaders: Record<string, string> = { accept: "application/json" };
  const secret = process.env.BFF_SHARED_SECRET;
  if (secret) {
    requestHeaders["x-streamclip-bff-token"] = secret;
    if (forwardClient) {
      Object.assign(requestHeaders, await clientHeaders());
    }
  }
  if (token) {
    requestHeaders.authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    requestHeaders["content-type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(new URL(`${API_PREFIX}${path}`, baseUrl()), {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    console.error("api_unreachable", { path, error: error instanceof Error ? error.message : error });
    return { ok: false, error: UNAVAILABLE };
  }

  if (response.status === 204) {
    return { ok: true, data: undefined as T };
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok && payload !== null) {
    return { ok: true, data: payload as T };
  }
  if (response.ok) {
    return { ok: true, data: undefined as T };
  }
  return { ok: false, error: parseError(response.status, payload) };
}
