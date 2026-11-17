import "server-only";

import { api } from "@/lib/api";
import { readSession } from "@/lib/session";

/**
 * Proxy HLS playlist/segments from the API (which talks to the dedicated
 * ingest agent). Rewrites playlists so segment URIs stay on this origin.
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

/** Force every playlist URI to a same-origin relative basename. */
function rewritePlaylist(body: string): string {
  return body
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        // EXT-X-MAP / EXT-X-MEDIA / EXT-X-STREAM-INF may embed URI="..."
        return line.replace(/URI="([^"]+)"/gi, (_match, uri: string) => {
          const base = uri.split("?")[0] ?? uri;
          const name = base.split("/").pop() || base;
          return `URI="${name}"`;
        });
      }
      // Absolute or rooted paths → basename only (resolved against playlist URL).
      try {
        if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith("/")) {
          const path = trimmed.split("?")[0] ?? trimmed;
          return path.split("/").pop() || trimmed;
        }
      } catch {
        // keep line
      }
      return line;
    })
    .join("\n");
}

async function forwardHls(upstream: Response): Promise<Response> {
  const contentType = upstream.headers.get("content-type") || "application/octet-stream";
  if (!upstream.ok) {
    // Don't leak API JSON to hls.js — empty body + status is enough.
    return new Response(null, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  }

  const isPlaylist =
    contentType.includes("mpegurl") ||
    contentType.includes("m3u8") ||
    contentType.includes("text/plain");

  if (isPlaylist) {
    const text = await upstream.text();
    // Heuristic: playlists start with #EXTM3U
    const body = text.trimStart().startsWith("#EXTM3U") ? rewritePlaylist(text) : text;
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.apple.mpegurl",
        "Cache-Control": "no-store",
      },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "no-store",
    },
  });
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
  try {
    const upstream = await fetch(
      new URL(`/api/v1/ingest/playback/hls/${safe}`, baseUrl()),
      { headers: await bffHeaders(access), cache: "no-store" },
    );
    return forwardHls(upstream);
  } catch {
    return new Response(null, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}

export async function proxyAdminHls(liveId: string, filePath: string): Promise<Response> {
  const { access } = await readSession();
  if (!access) {
    return new Response("Unauthorized", { status: 401 });
  }
  const me = await api<{ user: { platform_role: string } }>("/me", { token: access });
  if (!me.ok || me.data.user.platform_role === "user") {
    return new Response("Forbidden", { status: 403 });
  }
  const safe = filePath.replace(/^\/+/, "");
  if (!safe || safe.includes("..") || !/^[0-9a-f-]{36}$/i.test(liveId)) {
    return new Response("Not found", { status: 404 });
  }
  try {
    const upstream = await fetch(
      new URL(`/api/v1/admin/lives/${liveId}/playback/hls/${safe}`, baseUrl()),
      { headers: await bffHeaders(access), cache: "no-store" },
    );
    return forwardHls(upstream);
  } catch {
    return new Response(null, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
