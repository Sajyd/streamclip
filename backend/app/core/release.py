"""What this release actually ships."""

# Live media processing and clip generation (phases 3-5) are not open yet.
# Real Stripe payments stay blocked until this flips to True.
LIVE_PROCESSING_AVAILABLE = False

# Control plane for STREAMCLIP ingest keys (create / rotate / revoke, MediaMTX
# auth hooks). Can ship before MediaMTX accepts real RTMPS traffic.
INGEST_KEYS_AVAILABLE = True

# Official OAuth for YouTube / TikTok / Instagram (phase 8). Until this is
# True, users pick preferred platforms in onboarding and publish manually.
SOCIAL_OAUTH_AVAILABLE = False
