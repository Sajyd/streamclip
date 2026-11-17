// Shapes returned by the STREAMCLIP AI API (/api/v1). The API is the source
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

export type SocialAccount = {
  id: string;
  platform: string;
  status: string;
  display_name: string;
  connected_at: string;
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

export type StreamKey = {
  public_id: string;
  key_hint: string;
  label: string;
  status: string;
  created_at: string;
  last_used_at: string | null;
  rtmps_url: string | null;
  srt_url: string | null;
  stream_key: string | null;
  ingest_online: boolean;
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
