"""Domain enumerations.

Stored as VARCHAR columns guarded by CHECK constraints (see `enum_column`)
rather than native PostgreSQL ENUM types: adding or retiring a value is then
a plain constraint swap in a migration instead of an `ALTER TYPE`.
"""

from enum import StrEnum


class PlatformRole(StrEnum):
    USER = "user"
    SUPPORT = "support"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_DELETION = "pending_deletion"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class AuthTokenPurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class SessionRevokeReason(StrEnum):
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    PASSWORD_CHANGED = "password_changed"
    PASSWORD_RESET = "password_reset"
    TOKEN_REUSE = "token_reuse"
    ADMIN_REVOKED = "admin_revoked"
    ACCOUNT_SUSPENDED = "account_suspended"
    USER_REVOKED = "user_revoked"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    UNPAID = "unpaid"
    PAUSED = "paused"
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    CANCELED = "canceled"


class UsageKind(StrEnum):
    LIVE_PROCESSING = "live_processing"
    ADJUSTMENT = "adjustment"
    ADMIN_CREDIT = "admin_credit"


class BillingEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class CostCategory(StrEnum):
    INGEST_COMPUTE = "ingest_compute"
    WORKER_COMPUTE = "worker_compute"
    TRANSCRIPTION = "transcription"
    DIARIZATION = "diarization"
    LLM = "llm"
    STORAGE = "storage"
    STORAGE_REQUESTS = "storage_requests"
    DATA_TRANSFER = "data_transfer"
    EMAIL = "email"
    OTHER = "other"


class StreamKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class IngestNodeStatus(StrEnum):
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    TERMINATED = "terminated"
    LOST = "lost"


class IngestNodeKind(StrEnum):
    POOLED = "pooled"
    DEDICATED = "dedicated"


class StreamSessionStatus(StrEnum):
    PENDING = "pending"
    LIVE = "live"
    INTERRUPTED = "interrupted"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class StreamEndReason(StrEnum):
    PUBLISHER_ENDED = "publisher_ended"
    SIGNAL_LOST = "signal_lost"
    USER_STOPPED = "user_stopped"
    QUOTA_EXHAUSTED = "quota_exhausted"
    ADMIN_STOPPED = "admin_stopped"
    ACCOUNT_SUSPENDED = "account_suspended"
    ERROR = "error"


class IngestProtocol(StrEnum):
    RTMP = "rtmp"
    RTMPS = "rtmps"
    SRT = "srt"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    LOST = "lost"


class SegmentKind(StrEnum):
    AV = "av"
    AUDIO = "audio"
    FRAMES = "frames"


class SegmentStatus(StrEnum):
    AVAILABLE = "available"
    DELETED = "deleted"
    LOST = "lost"


class ContentCategory(StrEnum):
    GAMING = "gaming"
    PODCAST = "podcast"
    INTERVIEW = "interview"
    JUST_CHATTING = "just_chatting"
    IRL = "irl"
    MUSIC = "music"
    EVENT = "event"
    CONFERENCE = "conference"
    OTHER = "other"


class WindowStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisJobKind(StrEnum):
    SIGNAL_EXTRACTION = "signal_extraction"
    TRANSCRIPTION = "transcription"
    DIARIZATION = "diarization"
    FRAME_SAMPLING = "frame_sampling"
    MULTIMODAL_ANALYSIS = "multimodal_analysis"
    BOUNDARY_REFINEMENT = "boundary_refinement"
    CLIP_VERIFICATION = "clip_verification"
    SPEAKER_ASSOCIATION = "speaker_association"
    CLIP_RENDER = "clip_render"
    PUBLICATION = "publication"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    SKIPPED = "skipped"


class VisualAssociationStatus(StrEnum):
    """Whether a diarized voice could be tied to a visible person.

    Audio diarization and visual identification are distinct problems: a voice
    stays `not_visually_identified` until active-speaker detection is confident.
    """

    NOT_VISUALLY_IDENTIFIED = "not_visually_identified"
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"


class EventCategory(StrEnum):
    FUNNY_STORY = "funny_story"
    PUNCHLINE = "punchline"
    DEBATE = "debate"
    REVELATION = "revelation"
    UNEXPECTED_REACTION = "unexpected_reaction"
    VICTORY = "victory"
    EPIC_FAIL = "epic_fail"
    IMPRESSIVE_ACTION = "impressive_action"
    ABSURD_SITUATION = "absurd_situation"
    EMOTIONAL_MOMENT = "emotional_moment"
    PERFORMANCE = "performance"
    INTERESTING_EXCHANGE = "interesting_exchange"
    OTHER = "other"


class EventStatus(StrEnum):
    DETECTED = "detected"
    MERGED = "merged"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class CandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    REFINING = "refining"
    APPROVED = "approved"
    REJECTED = "rejected"
    RENDERED = "rendered"
    SUPERSEDED = "superseded"


class ClipStatus(StrEnum):
    QUEUED = "queued"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class ClipVersionKind(StrEnum):
    AUTO = "auto"
    USER_EDIT = "user_edit"


class ClipVersionStatus(StrEnum):
    QUEUED = "queued"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


class CaptionFormat(StrEnum):
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"
    WORDS_JSON = "words_json"


class ClipFeedbackAction(StrEnum):
    VIEWED = "viewed"
    DOWNLOADED = "downloaded"
    KEPT = "kept"
    DELETED = "deleted"
    PUBLISHED = "published"
    EDITED = "edited"
    RATED = "rated"


class SocialPlatform(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class SocialAccountStatus(StrEnum):
    CONNECTED = "connected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELED = "canceled"
    MANUAL_REQUIRED = "manual_required"


class AssetKind(StrEnum):
    CLIP_VIDEO = "clip_video"
    CLIP_PREVIEW = "clip_preview"
    CLIP_THUMBNAIL = "clip_thumbnail"
    CAPTION_FILE = "caption_file"
    TRANSCRIPT = "transcript"
    ANALYSIS_ARTIFACT = "analysis_artifact"
    DATA_EXPORT = "data_export"


class AssetStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    DELETED = "deleted"
    MISSING = "missing"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD = "dead"
    CANCELED = "canceled"


class NotificationSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    INGEST_NODE = "ingest_node"
    WEBHOOK = "webhook"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
