import "server-only";

import { api } from "@/lib/api";
import { readSession } from "@/lib/session";

/**
 * Proxy HLS playlist/segments from the API (which talks to the dedicated
 * ingest agent). Keeps MediaMTX/HLS off the public internet and avoids
 * mixed-content blocks on the HTTPS dashboard.
 */

function baseUrl(): string {
  const url = process.env.API_INTERNAL_URL;
  if (!url) {
    throw new Error("API_INTERNAL_URL is not configured");
  }
  return url;
}

async function bffHeaders(token: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    accept: "*/*",
    authorization: `Bearer ${token}`,
  };
  const secret = process.env.BFF_SHARED_SECRET;
  if (secret) {
    headers["x-streamclip-bff-token"] = secret;
  }
  return headers;
}

export async function proxyUserHls(filePath: string): Promise<Response> {
  const { access } = await readSession();
  if (!access) {
    return new Response("Unauthorized", { status: 401 });
  }
  const safe = filePath.replace(/^\/+/, "");
  if (!safe || safe.includes("..")) {
    return new Response("Not found", { status: 404 });
  }
  const upstream = await fetch(
    new URL(`/api/v1/ingest/playback/hls/${safe}`, baseUrl()),
    { headers: await bffHeaders(access), cache: "no-store" },
  );
  return forward(upstream);
}

export async function proxyAdminHls(liveId: string, filePath: string): Promise<Response> {
  const { access } = await readSession();
  if (!access) {
    return new Response("Unauthorized", { status: 401 });
  }
  // Confirm staff via a cheap typed call (403 → not found upstream of UI).
  const me = await api<{ user: { platform_role: string } }>("/me", { token: access });
  if (!me.ok || me.data.user.platform_role === "user") {
    return new Response("Forbidden", { status: 403 });
  }
  const safe = filePath.replace(/^\/+/, "");
  if (!safe || safe.includes("..") || !/^[0-9a-f-]{36}$/i.test(liveId)) {
    return new Response("Not found", { status: 404 });
  }
  const upstream = await fetch(
    new URL(`/api/v1/admin/lives/${liveId}/playback/hls/${safe}`, baseUrl()),
    { headers: await bffHeaders(access), cache: "no-store" },
  );
  return forward(upstream);
}

function forward(upstream: Response): Response {
  const contentType = upstream.headers.get("content-type") || "application/octet-stream";
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    },
  });
}
