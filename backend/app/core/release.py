"""What this release actually ships."""

# The ingest and clip-generation pipeline (development phases 2 to 5) is not
# part of this release. Two things follow from this single switch: no client
# presents live processing as available, and no real payment is taken for it.
LIVE_PROCESSING_AVAILABLE = False
