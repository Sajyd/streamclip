// Shapes returned by the STREAMCLIP API (/api/v1). The API is the source
// of truth: these types only describe what the web application reads.

export type Capabilities = {
  registration_open: boolean;
  email_delivery: boolean;
  billing: boolean;
  billing_test_mode: boolean;
  storage: boolean;
  live_processing: boolean;
  ingest_keys: boolean;
  ingest_online: boolean;
  /** Stable OBS server URL (same for every org). */
  ingest_rtmp_url: string | null;
  /** Status / docs URL (not the OBS server field). */
  ingest_api_url: string | null;
  social_oauth: boolean;
};

export type Onboarding = {
  completed: boolean;
  step: string;
  referral_source: string | null;
  usage: string | null;
  software: "obs" | "streamlabs" | null;
  social_platforms: Array<"youtube" | "tiktok" | "instagram">;
  ingest_ready: boolean;
  premium_choice: "free" | "premium" | null;
  live_detected: boolean;
  completed_at: string | null;
};

export type Clip = {
  id: string;
  title: string;
  description: string;
  status: string;
  category: string;
  score: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number | null;
  is_favorite: boolean;
  thumbnail_available: boolean;
  download_available: boolean;
  created_at: string;
  stream_session_id: string | null;
};

export type HighlightWord = {
  text: string;
  start_ms: number;
  end_ms: number;
};

export type Highlight = {
  id: string;
  stream_session_id: string;
  title: string;
  description: string;
  category: string;
  score: number;
  start_ms: number;
  end_ms: number;
  relative_start_ms: number;
  relative_end_ms: number;
  segment_sequence: number;
  hashtags: string[];
  words: HighlightWord[];
  camera: { detected: boolean; x: number; y: number };
  media_available: boolean;
  created_at: string;
};

export type SocialAccount = {
  id: string;
  platform: string;
  status: string;
  display_name: string;
  connected_at: string;
  auto_publish?: boolean;
};

export type SocialAccountList = {
  items: SocialAccount[];
  oauth_available: boolean;
  platforms: string[];
};

export type Meta = {
  name: string;
  environment: string;
  capabilities: Capabilities;
  password_min_length: number;
  terms_version: string;
};

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  locale: string;
  timezone: string;
  email_verified: boolean;
  platform_role: "user" | "support" | "admin";
  created_at: string;
};

export type Tokens = {
  token_type: string;
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  session_id: string;
};

export type AuthResponse = { user: User; tokens: Tokens };

export type Organization = { id: string; name: string; role: "owner" | "admin" | "member" };

export type Me = {
  user: User;
  organization: Organization;
  capabilities: Capabilities;
  onboarding: Onboarding;
};

export type Plan = {
  code: string;
  name: string;
  description: string;
  price_cents: number;
  currency: string;
  included_seconds: number;
  max_clips_per_session: number | null;
  max_concurrent_streams: number;
  clip_retention_days: number | null;
  features: string[];
  purchasable: boolean;
};

export type PlanCatalog = { items: Plan[]; vat_rate_percent: number };

export type Quota = {
  included_seconds: number;
  consumed_seconds: number;
  remaining_seconds: number;
  used_ratio: number;
  warning: boolean;
  exhausted: boolean;
};

export type BillingOverview = {
  plan: Plan;
  status: string;
  is_paid: boolean;
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  payment_failed: boolean;
  quota: Quota;
  has_billing_account: boolean;
  can_manage: boolean;
  billing_available: boolean;
  billing_test_mode: boolean;
};

export type Notification = {
  id: string;
  kind: string;
  severity: "info" | "success" | "warning" | "error";
  title: string;
  body: string;
  data: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
};

export type NotificationList = { items: Notification[]; unread_count: number };

export type AuthSession = {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  ip: string | null;
  user_agent: string | null;
  current: boolean;
};

export type DataExport = {
  id: string;
  status: "pending" | "available";
  size_bytes: number | null;
  created_at: string;
  expires_at: string | null;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string | null;
  status: "active" | "suspended" | "pending_deletion" | "deleted";
  platform_role: "user" | "support" | "admin";
  email_verified: boolean;
  created_at: string;
  last_login_at: string | null;
  organization_id: string | null;
  plan_code: string | null;
};

export type AdminUserList = { items: AdminUser[]; next_cursor: string | null };

export type AdminAnalyticsPeriod = "day" | "week" | "month" | "year";

export type AdminAnalyticsTotals = {
  users_total: number;
  users_new: number;
  users_new_previous: number;
  paying_subscribers: number;
  subscriptions_new: number;
  subscriptions_new_previous: number;
  mrr_cents: number;
  lives_active: number;
  lives_started: number;
  lives_started_previous: number;
  clips_total: number;
  clips_created: number;
  clips_created_previous: number;
  exports_created: number;
  exports_created_previous: number;
  clip_downloads: number;
  clip_downloads_previous: number;
};

export type AdminPlanBreakdown = {
  plan_code: string;
  plan_name: string;
  price_cents: number;
  currency: string;
  subscribers: number;
  mrr_cents: number;
};

export type AdminAnalyticsBucket = {
  bucket_start: string;
  users_new: number;
  clips_created: number;
  lives_started: number;
  exports_created: number;
  clip_downloads: number;
};

export type AdminAnalytics = {
  period: AdminAnalyticsPeriod;
  range_start: string;
  range_end: string;
  previous_range_start: string;
  currency: string;
  totals: AdminAnalyticsTotals;
  plans: AdminPlanBreakdown[];
  series: AdminAnalyticsBucket[];
};

export type AdminSubscription = {
  id: string;
  organization_id: string;
  organization_name: string;
  owner_email: string | null;
  plan_code: string;
  plan_name: string;
  price_cents: number;
  currency: string;
  status: string;
  is_paid: boolean;
  current_period_start: string;
  current_period_end: string;
  cancel_at_period_end: boolean;
  payment_failed: boolean;
  created_at: string;
};

export type AdminSubscriptionSummary = {
  mrr_cents: number;
  currency: string;
  paying_subscribers: number;
  free_subscribers: number;
  plans: AdminPlanBreakdown[];
};

export type AdminSubscriptionList = {
  items: AdminSubscription[];
  next_cursor: string | null;
  summary: AdminSubscriptionSummary;
};

export type AdminLive = {
  id: string;
  organization_id: string;
  organization_name: string;
  owner_email: string | null;
  status: string;
  end_reason: string | null;
  protocol: string | null;
  title: string | null;
  started_at: string | null;
  ended_at: string | null;
  last_media_at: string | null;
  media_duration_ms: number;
  processed_ms: number;
  clips_count: number;
  created_at: string;
};

export type AdminLiveList = { items: AdminLive[]; next_cursor: string | null };

export type AdminLiveDetail = AdminLive & {
  error_code: string | null;
  error_message: string | null;
  ingest_node: {
    id: string;
    name: string;
    status: string;
    public_hostname: string | null;
    instance_id: string | null;
    launch_error: string | null;
    launched_at: string | null;
  } | null;
  pipeline_log: Array<{
    id: string;
    occurred_at: string;
    action: string;
    outcome: string;
    ip: string | null;
    details: Record<string, unknown>;
  }>;
  tasks: Array<{
    id: string;
    kind: string;
    status: string;
    attempts: number;
    last_error: string | null;
    created_at: string;
    payload: Record<string, unknown>;
  }>;
  highlights: Array<{
    id: string;
    title: string;
    score: number;
    status: string;
    start_ms: number;
    end_ms: number;
    created_at: string;
  }>;
};

export type AdminClip = {
  id: string;
  organization_id: string;
  organization_name: string;
  owner_email: string | null;
  title: string;
  status: string;
  category: string;
  score: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  is_favorite: boolean;
  stream_session_id: string | null;
  created_at: string;
};

export type AdminClipList = { items: AdminClip[]; next_cursor: string | null };

export type AdminExport = {
  id: string;
  kind: "data_export" | "clip_download";
  organization_id: string;
  organization_name: string;
  owner_email: string | null;
  status: string;
  size_bytes: number | null;
  clip_id: string | null;
  clip_title: string | null;
  created_at: string;
  expires_at: string | null;
};

export type AdminExportList = { items: AdminExport[]; next_cursor: string | null };

export type StreamKey = {
  public_id: string;
  key_hint: string;
  label: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
  /** Stable API resolve URL (same for every org). */
  ingest_api_url: string;
  /** Dedicated instance RTMP URL once the spot is ready. */
  rtmps_url: string | null;
  srt_url: string | null;
  stream_key: string | null;
  ingest_online: boolean;
};

export type IngestResolve = {
  status: "starting" | "ready" | "unavailable" | string;
  ingest_api_url: string;
  rtmp_url: string | null;
  analysis_url: string | null;
  public_hostname: string | null;
  message: string;
};

export type StreamSession = {
  id: string;
  status: string;
  end_reason: string | null;
  protocol: string | null;
  title: string | null;
  started_at: string | null;
  ended_at: string | null;
  media_duration_ms: number;
  processed_ms: number;
  clips_count: number;
  created_at: string;
};
