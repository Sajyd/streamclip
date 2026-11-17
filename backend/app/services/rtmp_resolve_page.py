"""HTML landing for GET /rtmp?key=… — status helper, not the OBS server URL.

OBS must use the stable edge RTMP URL + stream key. This page only confirms
quota / dedicated spot readiness for support and debugging.
"""

from __future__ import annotations

import html


def render_resolve_page(
    *,
    status: str,
    message: str,
    rtmp_url: str | None,
    stream_key: str | None,
    resolve_url: str,
    edge_rtmp_url: str | None = None,
    refresh_seconds: int = 3,
) -> str:
    title = {
        "ready": "Instance dédiée prête",
        "starting": "Démarrage de votre instance…",
        "unavailable": "Instance indisponible",
        "forbidden": "Accès refusé",
    }.get(status, "STREAMCLIP")
    refresh = (
        f'<meta http-equiv="refresh" content="{refresh_seconds}">'
        if status == "starting"
        else ""
    )
    edge_block = ""
    if edge_rtmp_url:
        edge_block = f"""
        <div class="card">
          <p class="label">Serveur OBS (toujours le même)</p>
          <code>{html.escape(edge_rtmp_url)}</code>
          <p class="hint">Dans OBS : Service = Personnalisé. Collez cette URL + votre clé de stream. Le backend relaie vers votre EC2 dédiée.</p>
        </div>
        """
    dedicated_block = ""
    if rtmp_url and status == "ready":
        dedicated_block = f"""
        <div class="card">
          <p class="label">Cible relay interne (ne pas coller dans OBS)</p>
          <code>{html.escape(rtmp_url)}</code>
        </div>
        """
    key_block = (
        f'<p class="label">Clé de stream</p><code>{html.escape(stream_key)}</code>'
        if stream_key
        else ""
    )
    return f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  {refresh}
  <title>{html.escape(title)} · STREAMCLIP</title>
  <style>
    :root {{ color-scheme: dark; font-family: ui-sans-serif, system-ui, sans-serif; }}
    body {{ margin: 0; min-height: 100vh; background: #0a0a0b; color: #f4f4f5;
           display: grid; place-items: center; padding: 24px; }}
    main {{ max-width: 560px; width: 100%; }}
    h1 {{ font-size: 1.4rem; margin: 0 0 8px; }}
    p {{ color: #a1a1aa; line-height: 1.5; }}
    .card {{ margin-top: 20px; padding: 16px; border: 1px solid #27272a; border-radius: 16px;
             background: #18181b; }}
    .label {{ font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase;
              color: #71717a; margin: 0 0 8px; }}
    code {{ display: block; word-break: break-all; background: #09090b; border: 1px solid #3f3f46;
            border-radius: 10px; padding: 12px; color: #e4e4e7; font-size: 0.9rem; margin-bottom: 12px; }}
    .hint {{ font-size: 0.85rem; margin: 8px 0 0; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 0.75rem;
              border: 1px solid #3f3f46; color: #d4d4d8; margin-bottom: 12px; }}
    .ok {{ border-color: #166534; color: #86efac; }}
    .warn {{ border-color: #854d0e; color: #fde047; }}
    a {{ color: #93c5fd; }}
  </style>
</head>
<body>
  <main>
    <span class="badge {"ok" if status == "ready" else "warn"}">{html.escape(status)}</span>
    <h1>{html.escape(title)}</h1>
    <p>{html.escape(message)}</p>
    {edge_block}
    {key_block}
    {dedicated_block}
    <p class="hint">Page statut : <a href="{html.escape(resolve_url)}">{html.escape(resolve_url)}</a></p>
  </main>
</body>
</html>
"""
