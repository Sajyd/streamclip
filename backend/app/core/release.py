"""What this release actually ships."""

# Live ingest + clip generation are open. Paid Stripe checkout is allowed
# when LIVE_PROCESSING_AVAILABLE is True (including with live Stripe keys).
LIVE_PROCESSING_AVAILABLE = True

# Control plane for STREAMCLIP ingest keys and the shared edge RTMP URL.
INGEST_KEYS_AVAILABLE = True

# Official OAuth for YouTube / TikTok / Instagram + auto-publish queue.
SOCIAL_OAUTH_AVAILABLE = True
