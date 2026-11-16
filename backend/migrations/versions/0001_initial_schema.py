"""Initial schema: every table of the data model.

Generated from the ORM models, then reviewed. Access control (roles, grants,
row-level security) is added by revision 0002 and reference data by 0003.

Revision ID: 0001
Revises:
Create Date: 2026-11-16 18:22:32.239394+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audit_logs',
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_type', sa.Enum('user', 'admin', 'system', 'ingest_node', 'webhook', name='actor_type', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=96), nullable=False),
    sa.Column('outcome', sa.Enum('success', 'failure', name='outcome', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('target_type', sa.String(length=64), nullable=True),
    sa.Column('target_id', sa.String(length=128), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs')),
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor_time', 'audit_logs', ['actor_user_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_occurred_at'), 'audit_logs', ['occurred_at'], unique=False)
    op.create_index('ix_audit_logs_org_time', 'audit_logs', ['organization_id', 'occurred_at'], unique=False)
    op.create_table('billing_events',
    sa.Column('provider', sa.String(length=16), server_default='stripe', nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('event_type', sa.String(length=128), nullable=False),
    sa.Column('object_id', sa.String(length=128), nullable=True),
    sa.Column('livemode', sa.Boolean(), nullable=False),
    sa.Column('status', sa.Enum('received', 'processed', 'ignored', 'failed', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='1', nullable=False),
    sa.Column('error', sa.String(length=1000), nullable=True),
    sa.Column('event_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_events')),
    sa.UniqueConstraint('provider', 'event_id', name=op.f('uq_billing_events_provider')),
    )
    op.create_index(op.f('ix_billing_events_event_type'), 'billing_events', ['event_type'], unique=False)
    op.create_table('cost_records',
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('stream_session_id', sa.Uuid(), nullable=True),
    sa.Column('category', sa.Enum('ingest_compute', 'worker_compute', 'transcription', 'diarization', 'llm', 'storage', 'storage_requests', 'data_transfer', 'email', 'other', name='category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('resource', sa.String(length=96), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('unit', sa.String(length=24), nullable=False),
    sa.Column('unit_cost_usd', sa.Numeric(precision=18, scale=10), nullable=False),
    sa.Column('amount_usd', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('is_estimate', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('pricing_version', sa.String(length=32), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cost_records')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_cost_records_idempotency_key')),
    )
    op.create_index(op.f('ix_cost_records_occurred_at'), 'cost_records', ['occurred_at'], unique=False)
    op.create_index('ix_cost_records_org_time', 'cost_records', ['organization_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_cost_records_stream_session_id'), 'cost_records', ['stream_session_id'], unique=False)
    op.create_table('ingest_nodes',
    sa.Column('name', sa.String(length=96), nullable=False),
    sa.Column('kind', sa.Enum('pooled', 'dedicated', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('starting', 'ready', 'draining', 'terminated', 'lost', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('region', sa.String(length=32), nullable=False),
    sa.Column('instance_id', sa.String(length=64), nullable=True),
    sa.Column('instance_type', sa.String(length=32), nullable=True),
    sa.Column('public_hostname', sa.String(length=255), nullable=True),
    sa.Column('capacity_streams', sa.Integer(), server_default='1', nullable=False),
    sa.Column('active_streams', sa.Integer(), server_default='0', nullable=False),
    sa.Column('agent_version', sa.String(length=64), nullable=True),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('launched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('terminated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingest_nodes')),
    sa.UniqueConstraint('instance_id', name=op.f('uq_ingest_nodes_instance_id')),
    sa.UniqueConstraint('name', name=op.f('uq_ingest_nodes_name')),
    )
    op.create_index(op.f('ix_ingest_nodes_status'), 'ingest_nodes', ['status'], unique=False)
    op.create_table('plans',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=300), server_default='', nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='eur', nullable=False),
    sa.Column('included_seconds', sa.Integer(), nullable=False),
    sa.Column('max_clips_per_session', sa.Integer(), nullable=True),
    sa.Column('max_concurrent_streams', sa.Integer(), server_default='1', nullable=False),
    sa.Column('clip_retention_days', sa.Integer(), nullable=True),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('stripe_product_id', sa.String(length=64), nullable=True),
    sa.Column('stripe_price_id', sa.String(length=64), nullable=True),
    sa.Column('is_public', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('included_seconds >= 0', name=op.f('ck_plans_included_non_negative')),
    sa.CheckConstraint('price_cents >= 0', name=op.f('ck_plans_price_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_plans')),
    sa.UniqueConstraint('code', name=op.f('uq_plans_code')),
    sa.UniqueConstraint('stripe_price_id', name=op.f('uq_plans_stripe_price_id')),
    )
    op.create_table('platform_settings',
    sa.Column('key', sa.String(length=96), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('updated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_platform_settings')),
    )
    op.create_table('rate_limit_counters',
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key', 'window_start', name=op.f('pk_rate_limit_counters')),
    prefixes=['UNLOGGED']
    )
    op.create_index(op.f('ix_rate_limit_counters_expires_at'), 'rate_limit_counters', ['expires_at'], unique=False)
    op.create_table('tasks',
    sa.Column('queue', sa.String(length=32), server_default='default', nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'dead', 'canceled', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('priority', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
    sa.Column('locked_by', sa.String(length=128), nullable=True),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=True),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_tasks_idempotency_key')),
    )
    op.create_index('ix_tasks_claim', 'tasks', ['queue', 'priority', 'run_at'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('ix_tasks_lease', 'tasks', ['locked_until'], unique=False, postgresql_where=sa.text("status = 'running'"))
    op.create_index(op.f('ix_tasks_organization_id'), 'tasks', ['organization_id'], unique=False)
    op.create_table('users',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=True),
    sa.Column('locale', sa.String(length=10), server_default='fr', nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='Europe/Paris', nullable=False),
    sa.Column('platform_role', sa.Enum('user', 'support', 'admin', name='platform_role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'suspended', 'pending_deletion', 'deleted', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('terms_version', sa.String(length=32), nullable=False),
    sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('marketing_opt_in', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('suspended_reason', sa.String(length=500), nullable=True),
    sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('email = lower(email)', name=op.f('ck_users_email_lowercase')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email')),
    )
    op.create_table('worker_nodes',
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('queues', sa.String(length=300), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=True),
    sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_worker_nodes')),
    sa.UniqueConstraint('name', name=op.f('uq_worker_nodes_name')),
    )
    op.create_index(op.f('ix_worker_nodes_last_heartbeat_at'), 'worker_nodes', ['last_heartbeat_at'], unique=False)
    op.create_table('auth_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('purpose', sa.Enum('email_verification', 'password_reset', name='purpose', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('sent_to', sa.String(length=320), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_tokens_token_hash')),
    )
    op.create_index(op.f('ix_auth_tokens_expires_at'), 'auth_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_auth_tokens_user_id'), 'auth_tokens', ['user_id'], unique=False)
    op.create_table('organizations',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('active', 'suspended', 'pending_deletion', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('stripe_customer_id', sa.String(length=64), nullable=True),
    sa.Column('billing_email', sa.String(length=320), nullable=True),
    sa.Column('country', sa.String(length=2), nullable=True),
    sa.Column('deletion_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_organizations_owner_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_organizations')),
    sa.UniqueConstraint('stripe_customer_id', name=op.f('uq_organizations_stripe_customer_id')),
    )
    op.create_index(op.f('ix_organizations_owner_user_id'), 'organizations', ['owner_user_id'], unique=False)
    op.create_table('user_settings',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('email_notifications', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('ui_preferences', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_user_settings')),
    )
    op.create_table('auth_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoke_reason', sa.Enum('logout', 'logout_all', 'password_changed', 'password_reset', 'token_reuse', 'admin_revoked', 'account_suspended', 'user_revoked', name='revoke_reason', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_auth_sessions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions')),
    )
    op.create_index('ix_auth_sessions_user_active', 'auth_sessions', ['user_id'], unique=False, postgresql_where=sa.text('revoked_at IS NULL'))
    op.create_table('clip_feedback_events',
    sa.Column('clip_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.Enum('viewed', 'downloaded', 'kept', 'deleted', 'published', 'edited', 'rated', name='action', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_clip_feedback_events_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clip_feedback_events')),
    )
    op.create_index(op.f('ix_clip_feedback_events_clip_id'), 'clip_feedback_events', ['clip_id'], unique=False)
    op.create_index(op.f('ix_clip_feedback_events_organization_id'), 'clip_feedback_events', ['organization_id'], unique=False)
    op.create_index('ix_clip_feedback_org_created', 'clip_feedback_events', ['organization_id', 'created_at'], unique=False)
    op.create_table('memberships',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.Enum('owner', 'admin', 'member', name='role', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_memberships_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_memberships_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_memberships')),
    sa.UniqueConstraint('organization_id', 'user_id', name=op.f('uq_memberships_organization_id')),
    )
    op.create_index(op.f('ix_memberships_organization_id'), 'memberships', ['organization_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)
    op.create_table('notifications',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('severity', sa.Enum('info', 'success', 'warning', 'error', name='severity', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('body', sa.String(length=1000), server_default='', nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_notifications_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications')),
    sa.UniqueConstraint('organization_id', 'dedupe_key', name=op.f('uq_notifications_organization_id')),
    )
    op.create_index('ix_notifications_org_created', 'notifications', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_notifications_organization_id'), 'notifications', ['organization_id'], unique=False)
    op.create_table('organization_settings',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('min_clip_seconds', sa.Integer(), server_default='30', nullable=False),
    sa.Column('target_clip_min_seconds', sa.Integer(), server_default='45', nullable=False),
    sa.Column('target_clip_max_seconds', sa.Integer(), server_default='60', nullable=False),
    sa.Column('max_clip_seconds', sa.Integer(), server_default='120', nullable=False),
    sa.Column('context_buffer_seconds', sa.Integer(), server_default='90', nullable=False),
    sa.Column('content_category_override', sa.Enum('gaming', 'podcast', 'interview', 'just_chatting', 'irl', 'music', 'event', 'conference', 'other', name='content_category_override', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('caption_style', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('scoring_weights', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('preference_profile', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('allow_global_training', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('min_clip_seconds <= target_clip_min_seconds AND target_clip_min_seconds <= target_clip_max_seconds AND target_clip_max_seconds <= max_clip_seconds', name=op.f('ck_organization_settings_clip_durations_ordered')),
    sa.CheckConstraint('min_clip_seconds >= 5', name=op.f('ck_organization_settings_min_clip_positive')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_organization_settings_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('organization_id', name=op.f('pk_organization_settings')),
    )
    op.create_table('social_accounts',
    sa.Column('platform', sa.Enum('youtube', 'tiktok', 'instagram', name='platform', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('connected', 'expired', 'revoked', 'error', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('external_account_id', sa.String(length=128), nullable=False),
    sa.Column('display_name', sa.String(length=200), server_default='', nullable=False),
    sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('access_token_encrypted', sa.Text(), nullable=True),
    sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
    sa.Column('encryption_key_version', sa.String(length=64), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('connected_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('last_error', sa.String(length=1000), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_social_accounts_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_social_accounts')),
    sa.UniqueConstraint('organization_id', 'platform', 'external_account_id', name=op.f('uq_social_accounts_organization_id')),
    )
    op.create_index(op.f('ix_social_accounts_organization_id'), 'social_accounts', ['organization_id'], unique=False)
    op.create_table('storage_assets',
    sa.Column('kind', sa.Enum('clip_video', 'clip_preview', 'clip_thumbnail', 'caption_file', 'transcript', 'analysis_artifact', 'data_export', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('pending', 'available', 'deleted', 'missing', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('bucket', sa.String(length=63), nullable=False),
    sa.Column('key', sa.String(length=512), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_storage_assets_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_storage_assets')),
    sa.UniqueConstraint('bucket', 'key', name=op.f('uq_storage_assets_bucket')),
    )
    op.create_index('ix_storage_assets_expiry', 'storage_assets', ['expires_at'], unique=False, postgresql_where=sa.text("status = 'available'"))
    op.create_index(op.f('ix_storage_assets_organization_id'), 'storage_assets', ['organization_id'], unique=False)
    op.create_table('stream_keys',
    sa.Column('public_id', sa.String(length=32), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('key_hint', sa.String(length=8), nullable=False),
    sa.Column('label', sa.String(length=80), server_default='', nullable=False),
    sa.Column('status', sa.Enum('active', 'revoked', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_stream_keys_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stream_keys')),
    sa.UniqueConstraint('key_hash', name=op.f('uq_stream_keys_key_hash')),
    sa.UniqueConstraint('public_id', name=op.f('uq_stream_keys_public_id')),
    )
    op.create_index(op.f('ix_stream_keys_organization_id'), 'stream_keys', ['organization_id'], unique=False)
    op.create_index('uq_stream_keys_one_active', 'stream_keys', ['organization_id'], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.create_table('subscriptions',
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('active', 'trialing', 'past_due', 'unpaid', 'paused', 'incomplete', 'incomplete_expired', 'canceled', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('stripe_subscription_id', sa.String(length=64), nullable=True),
    sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payment_failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stripe_event_created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_subscriptions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_subscriptions_plan_id_plans'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('stripe_subscription_id', name=op.f('uq_subscriptions_stripe_subscription_id')),
    )
    op.create_index(op.f('ix_subscriptions_organization_id'), 'subscriptions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_plan_id'), 'subscriptions', ['plan_id'], unique=False)
    op.create_index('uq_subscriptions_current', 'subscriptions', ['organization_id'], unique=True, postgresql_where=sa.text('ended_at IS NULL'))
    op.create_table('refresh_tokens',
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('parent_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rotated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['auth_sessions.id'], name=op.f('fk_refresh_tokens_session_id_auth_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash')),
    )
    op.create_index(op.f('ix_refresh_tokens_expires_at'), 'refresh_tokens', ['expires_at'], unique=False)
    op.create_index(op.f('ix_refresh_tokens_session_id'), 'refresh_tokens', ['session_id'], unique=False)
    op.create_table('stream_sessions',
    sa.Column('stream_key_id', sa.Uuid(), nullable=True),
    sa.Column('ingest_node_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('pending', 'live', 'interrupted', 'finalizing', 'completed', 'failed', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('end_reason', sa.Enum('publisher_ended', 'signal_lost', 'user_stopped', 'quota_exhausted', 'admin_stopped', 'account_suspended', 'error', name='end_reason', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('protocol', sa.Enum('rtmp', 'rtmps', 'srt', name='protocol', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('content_category', sa.Enum('gaming', 'podcast', 'interview', 'just_chatting', 'irl', 'music', 'event', 'conference', 'other', name='content_category', native_enum=False, create_constraint=True, length=32), nullable=True),
    sa.Column('content_category_confidence', sa.Float(), nullable=True),
    sa.Column('processing_profile', sa.String(length=32), server_default='standard', nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_media_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('media_duration_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('processed_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('video_codec', sa.String(length=32), nullable=True),
    sa.Column('audio_codec', sa.String(length=32), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('fps', sa.Numeric(precision=7, scale=3), nullable=True),
    sa.Column('bitrate_kbps', sa.Integer(), nullable=True),
    sa.Column('rolling_summary', sa.Text(), nullable=True),
    sa.Column('clips_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=1000), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('processed_ms >= 0 AND media_duration_ms >= 0', name=op.f('ck_stream_sessions_durations_positive')),
    sa.ForeignKeyConstraint(['ingest_node_id'], ['ingest_nodes.id'], name=op.f('fk_stream_sessions_ingest_node_id_ingest_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_stream_sessions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_key_id'], ['stream_keys.id'], name=op.f('fk_stream_sessions_stream_key_id_stream_keys'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stream_sessions')),
    )
    op.create_index(op.f('ix_stream_sessions_ingest_node_id'), 'stream_sessions', ['ingest_node_id'], unique=False)
    op.create_index('ix_stream_sessions_open', 'stream_sessions', ['status'], unique=False, postgresql_where=sa.text("status IN ('pending', 'live', 'interrupted', 'finalizing')"))
    op.create_index('ix_stream_sessions_org_started', 'stream_sessions', ['organization_id', 'started_at'], unique=False)
    op.create_index(op.f('ix_stream_sessions_organization_id'), 'stream_sessions', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stream_sessions_stream_key_id'), 'stream_sessions', ['stream_key_id'], unique=False)
    op.create_table('usage_periods',
    sa.Column('subscription_id', sa.Uuid(), nullable=False),
    sa.Column('plan_id', sa.Uuid(), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('included_ms', sa.BigInteger(), nullable=False),
    sa.Column('consumed_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('warning_sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('exhausted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('consumed_ms >= 0 AND included_ms >= 0', name=op.f('ck_usage_periods_non_negative')),
    sa.CheckConstraint('period_end > period_start', name=op.f('ck_usage_periods_period_ordered')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_usage_periods_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], name=op.f('fk_usage_periods_plan_id_plans'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], name=op.f('fk_usage_periods_subscription_id_subscriptions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_periods')),
    sa.UniqueConstraint('organization_id', 'period_start', name=op.f('uq_usage_periods_organization_id')),
    )
    op.create_index(op.f('ix_usage_periods_organization_id'), 'usage_periods', ['organization_id'], unique=False)
    op.create_index(op.f('ix_usage_periods_subscription_id'), 'usage_periods', ['subscription_id'], unique=False)
    op.create_table('analysis_windows',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'queued', 'analyzing', 'analyzed', 'failed', 'skipped', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('context_summary', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('open_events', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('cost_usd', sa.Numeric(precision=18, scale=8), server_default='0', nullable=False),
    sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_analysis_windows_range_ordered')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_analysis_windows_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_analysis_windows_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_windows')),
    sa.UniqueConstraint('stream_session_id', 'sequence', name=op.f('uq_analysis_windows_stream_session_id')),
    )
    op.create_index(op.f('ix_analysis_windows_organization_id'), 'analysis_windows', ['organization_id'], unique=False)
    op.create_index(op.f('ix_analysis_windows_status'), 'analysis_windows', ['status'], unique=False)
    op.create_table('highlight_candidates',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('candidate', 'refining', 'approved', 'rejected', 'rendered', 'superseded', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('category', sa.Enum('funny_story', 'punchline', 'debate', 'revelation', 'unexpected_reaction', 'victory', 'epic_fail', 'impressive_action', 'absurd_situation', 'emotional_moment', 'performance', 'interesting_exchange', 'other', name='category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.Text(), server_default='', nullable=False),
    sa.Column('context_start_ms', sa.BigInteger(), nullable=True),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('payoff_ms', sa.BigInteger(), nullable=True),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=3), nullable=False),
    sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('verification', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('rejection_reason', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_highlight_candidates_range_ordered')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_highlight_candidates_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_highlight_candidates_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_highlight_candidates')),
    )
    op.create_index(op.f('ix_highlight_candidates_organization_id'), 'highlight_candidates', ['organization_id'], unique=False)
    op.create_index('ix_highlight_candidates_session_score', 'highlight_candidates', ['stream_session_id', 'score'], unique=False)
    op.create_table('media_segments',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sa.Enum('av', 'audio', 'frames', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('sequence', sa.BigInteger(), nullable=False),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Enum('available', 'deleted', 'lost', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('pinned_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_media_segments_range_ordered')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_media_segments_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_media_segments_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_media_segments')),
    sa.UniqueConstraint('stream_session_id', 'kind', 'sequence', name=op.f('uq_media_segments_stream_session_id')),
    )
    op.create_index('ix_media_segments_expiry', 'media_segments', ['expires_at'], unique=False, postgresql_where=sa.text("status = 'available'"))
    op.create_index(op.f('ix_media_segments_organization_id'), 'media_segments', ['organization_id'], unique=False)
    op.create_index('ix_media_segments_session_time', 'media_segments', ['stream_session_id', 'start_ms'], unique=False)
    op.create_table('speakers',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('label', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=True),
    sa.Column('total_speech_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('first_heard_ms', sa.BigInteger(), nullable=True),
    sa.Column('visual_status', sa.Enum('not_visually_identified', 'tentative', 'confirmed', name='visual_status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('visual_confidence', sa.Float(), nullable=True),
    sa.Column('visual_track', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_speakers_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_speakers_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_speakers')),
    sa.UniqueConstraint('stream_session_id', 'label', name=op.f('uq_speakers_stream_session_id')),
    )
    op.create_index(op.f('ix_speakers_organization_id'), 'speakers', ['organization_id'], unique=False)
    op.create_table('stream_connections',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('ingest_node_id', sa.Uuid(), nullable=True),
    sa.Column('protocol', sa.Enum('rtmp', 'rtmps', 'srt', name='protocol', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('active', 'closed', 'lost', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('remote_ip', postgresql.INET(), nullable=True),
    sa.Column('connected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('disconnected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('media_offset_ms', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('bytes_received', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('disconnect_reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['ingest_node_id'], ['ingest_nodes.id'], name=op.f('fk_stream_connections_ingest_node_id_ingest_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_stream_connections_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_stream_connections_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stream_connections')),
    )
    op.create_index(op.f('ix_stream_connections_organization_id'), 'stream_connections', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stream_connections_stream_session_id'), 'stream_connections', ['stream_session_id'], unique=False)
    op.create_table('usage_records',
    sa.Column('usage_period_id', sa.Uuid(), nullable=False),
    sa.Column('stream_session_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Enum('live_processing', 'adjustment', 'admin_credit', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('quantity_ms', sa.BigInteger(), nullable=False),
    sa.Column('media_start_ms', sa.BigInteger(), nullable=True),
    sa.Column('media_end_ms', sa.BigInteger(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_usage_records_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['usage_period_id'], ['usage_periods.id'], name=op.f('fk_usage_records_usage_period_id_usage_periods'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_usage_records')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_usage_records_idempotency_key')),
    )
    op.create_index(op.f('ix_usage_records_organization_id'), 'usage_records', ['organization_id'], unique=False)
    op.create_index(op.f('ix_usage_records_stream_session_id'), 'usage_records', ['stream_session_id'], unique=False)
    op.create_index(op.f('ix_usage_records_usage_period_id'), 'usage_records', ['usage_period_id'], unique=False)
    op.create_table('analysis_jobs',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('analysis_window_id', sa.Uuid(), nullable=True),
    sa.Column('clip_id', sa.Uuid(), nullable=True),
    sa.Column('kind', sa.Enum('signal_extraction', 'transcription', 'diarization', 'frame_sampling', 'multimodal_analysis', 'boundary_refinement', 'clip_verification', 'speaker_association', 'clip_render', 'publication', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', 'canceled', 'skipped', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('provider', sa.String(length=48), nullable=True),
    sa.Column('model', sa.String(length=96), nullable=True),
    sa.Column('attempt', sa.Integer(), server_default='1', nullable=False),
    sa.Column('input_tokens', sa.BigInteger(), nullable=True),
    sa.Column('output_tokens', sa.BigInteger(), nullable=True),
    sa.Column('audio_ms', sa.BigInteger(), nullable=True),
    sa.Column('frames', sa.Integer(), nullable=True),
    sa.Column('cost_usd', sa.Numeric(precision=18, scale=8), server_default='0', nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=1000), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['analysis_window_id'], ['analysis_windows.id'], name=op.f('fk_analysis_jobs_analysis_window_id_analysis_windows'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_analysis_jobs_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_analysis_jobs_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_jobs')),
    )
    op.create_index(op.f('ix_analysis_jobs_analysis_window_id'), 'analysis_jobs', ['analysis_window_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_clip_id'), 'analysis_jobs', ['clip_id'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_organization_id'), 'analysis_jobs', ['organization_id'], unique=False)
    op.create_index('ix_analysis_jobs_session_kind', 'analysis_jobs', ['stream_session_id', 'kind'], unique=False)
    op.create_index(op.f('ix_analysis_jobs_status'), 'analysis_jobs', ['status'], unique=False)
    op.create_table('clips',
    sa.Column('stream_session_id', sa.Uuid(), nullable=True),
    sa.Column('highlight_candidate_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'rendering', 'ready', 'failed', 'deleted', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('category', sa.Enum('funny_story', 'punchline', 'debate', 'revelation', 'unexpected_reaction', 'victory', 'epic_fail', 'impressive_action', 'absurd_situation', 'emotional_moment', 'performance', 'interesting_exchange', 'other', name='category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('language', sa.String(length=12), nullable=True),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=3), nullable=False),
    sa.Column('score_breakdown', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('speakers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('current_version_id', sa.Uuid(), nullable=True),
    sa.Column('is_favorite', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_clips_range_ordered')),
    sa.ForeignKeyConstraint(['highlight_candidate_id'], ['highlight_candidates.id'], name=op.f('fk_clips_highlight_candidate_id_highlight_candidates'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_clips_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_clips_stream_session_id_stream_sessions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clips')),
    )
    op.create_index('ix_clips_org_created', 'clips', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_clips_organization_id'), 'clips', ['organization_id'], unique=False)
    op.create_index(op.f('ix_clips_stream_session_id'), 'clips', ['stream_session_id'], unique=False)
    op.create_table('detected_events',
    sa.Column('stream_session_id', sa.Uuid(), nullable=False),
    sa.Column('analysis_window_id', sa.Uuid(), nullable=False),
    sa.Column('category', sa.Enum('funny_story', 'punchline', 'debate', 'revelation', 'unexpected_reaction', 'victory', 'epic_fail', 'impressive_action', 'absurd_situation', 'emotional_moment', 'performance', 'interesting_exchange', 'other', name='category', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('detected', 'merged', 'rejected', 'promoted', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('peak_ms', sa.BigInteger(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('is_open', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('merged_into_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_detected_events_range_ordered')),
    sa.ForeignKeyConstraint(['analysis_window_id'], ['analysis_windows.id'], name=op.f('fk_detected_events_analysis_window_id_analysis_windows'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['merged_into_id'], ['detected_events.id'], name=op.f('fk_detected_events_merged_into_id_detected_events'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_detected_events_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stream_session_id'], ['stream_sessions.id'], name=op.f('fk_detected_events_stream_session_id_stream_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_detected_events')),
    )
    op.create_index(op.f('ix_detected_events_analysis_window_id'), 'detected_events', ['analysis_window_id'], unique=False)
    op.create_index(op.f('ix_detected_events_organization_id'), 'detected_events', ['organization_id'], unique=False)
    op.create_index('ix_detected_events_session_time', 'detected_events', ['stream_session_id', 'start_ms'], unique=False)
    op.create_table('clip_versions',
    sa.Column('clip_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('auto', 'user_edit', name='kind', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('queued', 'rendering', 'ready', 'failed', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('start_ms', sa.BigInteger(), nullable=False),
    sa.Column('end_ms', sa.BigInteger(), nullable=False),
    sa.Column('render_settings', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('video_asset_id', sa.Uuid(), nullable=True),
    sa.Column('thumbnail_asset_id', sa.Uuid(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('rendered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=1000), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('end_ms > start_ms', name=op.f('ck_clip_versions_range_ordered')),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_clip_versions_clip_id_clips'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_clip_versions_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['thumbnail_asset_id'], ['storage_assets.id'], name=op.f('fk_clip_versions_thumbnail_asset_id_storage_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['video_asset_id'], ['storage_assets.id'], name=op.f('fk_clip_versions_video_asset_id_storage_assets'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clip_versions')),
    sa.UniqueConstraint('clip_id', 'version', name=op.f('uq_clip_versions_clip_id')),
    )
    op.create_index(op.f('ix_clip_versions_organization_id'), 'clip_versions', ['organization_id'], unique=False)
    op.create_table('highlight_candidate_events',
    sa.Column('highlight_candidate_id', sa.Uuid(), nullable=False),
    sa.Column('detected_event_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['detected_event_id'], ['detected_events.id'], name=op.f('fk_highlight_candidate_events_detected_event_id_detected_events'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['highlight_candidate_id'], ['highlight_candidates.id'], name=op.f('fk_highlight_candidate_events_highlight_candidate_id_highlight_candidates'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_highlight_candidate_events_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('highlight_candidate_id', 'detected_event_id', name=op.f('pk_highlight_candidate_events')),
    )
    op.create_index(op.f('ix_highlight_candidate_events_detected_event_id'), 'highlight_candidate_events', ['detected_event_id'], unique=False)
    op.create_index(op.f('ix_highlight_candidate_events_organization_id'), 'highlight_candidate_events', ['organization_id'], unique=False)
    op.create_table('captions',
    sa.Column('clip_version_id', sa.Uuid(), nullable=False),
    sa.Column('language', sa.String(length=12), nullable=False),
    sa.Column('format', sa.Enum('srt', 'vtt', 'ass', 'words_json', name='format', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('words', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('asset_id', sa.Uuid(), nullable=True),
    sa.Column('is_burned_in', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['storage_assets.id'], name=op.f('fk_captions_asset_id_storage_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['clip_version_id'], ['clip_versions.id'], name=op.f('fk_captions_clip_version_id_clip_versions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_captions_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_captions')),
    sa.UniqueConstraint('clip_version_id', 'language', 'format', name=op.f('uq_captions_clip_version_id')),
    )
    op.create_index(op.f('ix_captions_organization_id'), 'captions', ['organization_id'], unique=False)
    op.create_table('social_publications',
    sa.Column('clip_id', sa.Uuid(), nullable=True),
    sa.Column('clip_version_id', sa.Uuid(), nullable=True),
    sa.Column('social_account_id', sa.Uuid(), nullable=False),
    sa.Column('platform', sa.Enum('youtube', 'tiktok', 'instagram', name='platform', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('status', sa.Enum('draft', 'scheduled', 'queued', 'uploading', 'processing', 'published', 'failed', 'canceled', 'manual_required', name='status', native_enum=False, create_constraint=True, length=32), nullable=False),
    sa.Column('title', sa.String(length=200), server_default='', nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('hashtags', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('privacy', sa.String(length=32), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('external_post_id', sa.String(length=128), nullable=True),
    sa.Column('external_url', sa.String(length=500), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.String(length=1000), nullable=True),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['clip_id'], ['clips.id'], name=op.f('fk_social_publications_clip_id_clips'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['clip_version_id'], ['clip_versions.id'], name=op.f('fk_social_publications_clip_version_id_clip_versions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_social_publications_organization_id_organizations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['social_account_id'], ['social_accounts.id'], name=op.f('fk_social_publications_social_account_id_social_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_social_publications')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_social_publications_idempotency_key')),
    )
    op.create_index(op.f('ix_social_publications_clip_id'), 'social_publications', ['clip_id'], unique=False)
    op.create_index('ix_social_publications_due', 'social_publications', ['scheduled_at'], unique=False, postgresql_where=sa.text("status = 'scheduled'"))
    op.create_index('ix_social_publications_org_created', 'social_publications', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_social_publications_organization_id'), 'social_publications', ['organization_id'], unique=False)
    op.create_index(op.f('ix_social_publications_social_account_id'), 'social_publications', ['social_account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_social_publications_social_account_id'), table_name='social_publications')
    op.drop_index(op.f('ix_social_publications_organization_id'), table_name='social_publications')
    op.drop_index('ix_social_publications_org_created', table_name='social_publications')
    op.drop_index('ix_social_publications_due', table_name='social_publications', postgresql_where=sa.text("status = 'scheduled'"))
    op.drop_index(op.f('ix_social_publications_clip_id'), table_name='social_publications')
    op.drop_table('social_publications')
    op.drop_index(op.f('ix_captions_organization_id'), table_name='captions')
    op.drop_table('captions')
    op.drop_index(op.f('ix_highlight_candidate_events_organization_id'), table_name='highlight_candidate_events')
    op.drop_index(op.f('ix_highlight_candidate_events_detected_event_id'), table_name='highlight_candidate_events')
    op.drop_table('highlight_candidate_events')
    op.drop_index(op.f('ix_clip_versions_organization_id'), table_name='clip_versions')
    op.drop_table('clip_versions')
    op.drop_index('ix_detected_events_session_time', table_name='detected_events')
    op.drop_index(op.f('ix_detected_events_organization_id'), table_name='detected_events')
    op.drop_index(op.f('ix_detected_events_analysis_window_id'), table_name='detected_events')
    op.drop_table('detected_events')
    op.drop_index(op.f('ix_clips_stream_session_id'), table_name='clips')
    op.drop_index(op.f('ix_clips_organization_id'), table_name='clips')
    op.drop_index('ix_clips_org_created', table_name='clips')
    op.drop_table('clips')
    op.drop_index(op.f('ix_analysis_jobs_status'), table_name='analysis_jobs')
    op.drop_index('ix_analysis_jobs_session_kind', table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_organization_id'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_clip_id'), table_name='analysis_jobs')
    op.drop_index(op.f('ix_analysis_jobs_analysis_window_id'), table_name='analysis_jobs')
    op.drop_table('analysis_jobs')
    op.drop_index(op.f('ix_usage_records_usage_period_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_stream_session_id'), table_name='usage_records')
    op.drop_index(op.f('ix_usage_records_organization_id'), table_name='usage_records')
    op.drop_table('usage_records')
    op.drop_index(op.f('ix_stream_connections_stream_session_id'), table_name='stream_connections')
    op.drop_index(op.f('ix_stream_connections_organization_id'), table_name='stream_connections')
    op.drop_table('stream_connections')
    op.drop_index(op.f('ix_speakers_organization_id'), table_name='speakers')
    op.drop_table('speakers')
    op.drop_index('ix_media_segments_session_time', table_name='media_segments')
    op.drop_index(op.f('ix_media_segments_organization_id'), table_name='media_segments')
    op.drop_index('ix_media_segments_expiry', table_name='media_segments', postgresql_where=sa.text("status = 'available'"))
    op.drop_table('media_segments')
    op.drop_index('ix_highlight_candidates_session_score', table_name='highlight_candidates')
    op.drop_index(op.f('ix_highlight_candidates_organization_id'), table_name='highlight_candidates')
    op.drop_table('highlight_candidates')
    op.drop_index(op.f('ix_analysis_windows_status'), table_name='analysis_windows')
    op.drop_index(op.f('ix_analysis_windows_organization_id'), table_name='analysis_windows')
    op.drop_table('analysis_windows')
    op.drop_index(op.f('ix_usage_periods_subscription_id'), table_name='usage_periods')
    op.drop_index(op.f('ix_usage_periods_organization_id'), table_name='usage_periods')
    op.drop_table('usage_periods')
    op.drop_index(op.f('ix_stream_sessions_stream_key_id'), table_name='stream_sessions')
    op.drop_index(op.f('ix_stream_sessions_organization_id'), table_name='stream_sessions')
    op.drop_index('ix_stream_sessions_org_started', table_name='stream_sessions')
    op.drop_index('ix_stream_sessions_open', table_name='stream_sessions', postgresql_where=sa.text("status IN ('pending', 'live', 'interrupted', 'finalizing')"))
    op.drop_index(op.f('ix_stream_sessions_ingest_node_id'), table_name='stream_sessions')
    op.drop_table('stream_sessions')
    op.drop_index(op.f('ix_refresh_tokens_session_id'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_expires_at'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('uq_subscriptions_current', table_name='subscriptions', postgresql_where=sa.text('ended_at IS NULL'))
    op.drop_index(op.f('ix_subscriptions_plan_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_organization_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index('uq_stream_keys_one_active', table_name='stream_keys', postgresql_where=sa.text("status = 'active'"))
    op.drop_index(op.f('ix_stream_keys_organization_id'), table_name='stream_keys')
    op.drop_table('stream_keys')
    op.drop_index(op.f('ix_storage_assets_organization_id'), table_name='storage_assets')
    op.drop_index('ix_storage_assets_expiry', table_name='storage_assets', postgresql_where=sa.text("status = 'available'"))
    op.drop_table('storage_assets')
    op.drop_index(op.f('ix_social_accounts_organization_id'), table_name='social_accounts')
    op.drop_table('social_accounts')
    op.drop_table('organization_settings')
    op.drop_index(op.f('ix_notifications_organization_id'), table_name='notifications')
    op.drop_index('ix_notifications_org_created', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index(op.f('ix_memberships_organization_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index('ix_clip_feedback_org_created', table_name='clip_feedback_events')
    op.drop_index(op.f('ix_clip_feedback_events_organization_id'), table_name='clip_feedback_events')
    op.drop_index(op.f('ix_clip_feedback_events_clip_id'), table_name='clip_feedback_events')
    op.drop_table('clip_feedback_events')
    op.drop_index('ix_auth_sessions_user_active', table_name='auth_sessions', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_table('auth_sessions')
    op.drop_table('user_settings')
    op.drop_index(op.f('ix_organizations_owner_user_id'), table_name='organizations')
    op.drop_table('organizations')
    op.drop_index(op.f('ix_auth_tokens_user_id'), table_name='auth_tokens')
    op.drop_index(op.f('ix_auth_tokens_expires_at'), table_name='auth_tokens')
    op.drop_table('auth_tokens')
    op.drop_index(op.f('ix_worker_nodes_last_heartbeat_at'), table_name='worker_nodes')
    op.drop_table('worker_nodes')
    op.drop_table('users')
    op.drop_index(op.f('ix_tasks_organization_id'), table_name='tasks')
    op.drop_index('ix_tasks_lease', table_name='tasks', postgresql_where=sa.text("status = 'running'"))
    op.drop_index('ix_tasks_claim', table_name='tasks', postgresql_where=sa.text("status = 'queued'"))
    op.drop_table('tasks')
    op.drop_index(op.f('ix_rate_limit_counters_expires_at'), table_name='rate_limit_counters')
    op.drop_table('rate_limit_counters')
    op.drop_table('platform_settings')
    op.drop_table('plans')
    op.drop_index(op.f('ix_ingest_nodes_status'), table_name='ingest_nodes')
    op.drop_table('ingest_nodes')
    op.drop_index(op.f('ix_cost_records_stream_session_id'), table_name='cost_records')
    op.drop_index('ix_cost_records_org_time', table_name='cost_records')
    op.drop_index(op.f('ix_cost_records_occurred_at'), table_name='cost_records')
    op.drop_table('cost_records')
    op.drop_index(op.f('ix_billing_events_event_type'), table_name='billing_events')
    op.drop_table('billing_events')
    op.drop_index('ix_audit_logs_org_time', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_occurred_at'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_time', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
