# Publish pipeline (highlights → clips → réseaux)

Product flow target (not all shipped yet).

## Flow

1. **Live** → 5‑min analysis → `HighlightCandidate` (+ optional thumbnail asset).
2. User **selects** highlights (publish now / schedule / favorite / delete).
3. **Remotion render** (dedicated site/worker) produces a 9:16 MP4 → `Clip` + `ClipVersion`.
4. User **downloads**, **publishes now**, or **schedules** (`SocialPublication.scheduled_at`).
5. **Auto-publish** (settings): at schedule/publish time, render if needed then push to connected platforms.
6. **Calendar** lists due/scheduled items; edit title, description, date; delete.

## Thumbnail

- Prefer ffmpeg frame at payoff + TikTok-style title overlay; store as storage asset on the highlight.
- Optional upgrade: cheapest Bedrock image model with title baked in when quality matters.
- Persist key in analysis payload alongside segment video key.

## Remotion

- Preview today: `frontend/remotion/ViralHighlight.tsx` + `@remotion/player`.
- Captions: Komika Axis, 60px, 16px black stroke (`paintOrder: stroke fill`).
- Watermark (logo icon + « streamclip »): free plans only (`showWatermark={!is_paid}`). Hard jumps left / middle / right (~2.8s), no interpolation.
- Production render: deploy Remotion as a render service (Lambda or long-running worker), enqueue `clip.render` from highlight selection / schedule tick; pass `showWatermark` from plan.

## Status

| Piece | Status |
| --- | --- |
| Guide OBS/Streamlabs post-onboarding | Shipped (`/guide`) |
| Calendar nav stub | Shipped (`/calendar` placeholder) |
| Highlight favorite / delete / select | Todo |
| Remotion server render → Clip | Todo |
| Schedule + auto render-at-publish | Todo |
| Calendar CRUD | Todo |
| Thumbnail ffmpeg / Bedrock | Todo |
