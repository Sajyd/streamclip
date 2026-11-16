#!/usr/bin/env bash
# Local PostgreSQL for development and tests WITHOUT Docker.
#
# Downloads portable PostgreSQL binaries (theseus-rs/postgresql-binaries) into
# .tools/ (git-ignored), creates a cluster bound to 127.0.0.1 and manages it.
# Nothing is installed system-wide. The preferred path remains
# `docker compose up -d postgres`; this script exists for machines without a
# container runtime.
#
# Usage: scripts/dev-postgres.sh {start|stop|status|url|psql|destroy}
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_VERSION="${PG_VERSION:-17.12.0}"
PG_PORT="${PG_PORT:-55432}"
PG_SUPERUSER="${PG_SUPERUSER:-postgres}"
PG_SUPERUSER_PASSWORD="${PG_SUPERUSER_PASSWORD:-postgres}"
TOOLS_DIR="${TOOLS_DIR:-$ROOT/.tools}"
PG_HOME="$TOOLS_DIR/postgresql-$PG_VERSION"
PG_DATA="${PG_DATA:-$TOOLS_DIR/pgdata-${PG_VERSION%%.*}}"
PG_LOG="$TOOLS_DIR/postgres.log"
# Unix socket paths are limited to ~103 bytes: keep the socket dir short.
PG_SOCKET_DIR="${PG_SOCKET_DIR:-/tmp/streamclip-pg-$PG_PORT}"

platform_triple() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$os-$arch" in
    Darwin-arm64) echo "aarch64-apple-darwin" ;;
    Darwin-x86_64) echo "x86_64-apple-darwin" ;;
    Linux-x86_64) echo "x86_64-unknown-linux-gnu" ;;
    Linux-aarch64 | Linux-arm64) echo "aarch64-unknown-linux-gnu" ;;
    *)
      echo "Unsupported platform: $os-$arch" >&2
      exit 1
      ;;
  esac
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

ensure_binaries() {
  if [ -x "$PG_HOME/bin/postgres" ]; then
    return
  fi
  local triple archive url tmp expected actual
  triple="$(platform_triple)"
  archive="postgresql-$PG_VERSION-$triple.tar.gz"
  url="https://github.com/theseus-rs/postgresql-binaries/releases/download/$PG_VERSION/$archive"
  tmp="$TOOLS_DIR/$archive"
  mkdir -p "$TOOLS_DIR"
  echo "Downloading $url" >&2
  curl -fSL --retry 3 -o "$tmp" "$url"
  if expected="$(curl -fsSL --retry 3 "$url.sha256" 2>/dev/null | awk '{print $1}')" && [ -n "$expected" ]; then
    actual="$(sha256_of "$tmp")"
    if [ "$expected" != "$actual" ]; then
      echo "Checksum mismatch for $archive (expected $expected, got $actual)" >&2
      rm -f "$tmp"
      exit 1
    fi
    echo "Checksum OK ($actual)" >&2
  else
    echo "WARNING: no published checksum found for $archive; skipping verification" >&2
  fi
  mkdir -p "$PG_HOME"
  tar -xzf "$tmp" -C "$PG_HOME" --strip-components=1
  rm -f "$tmp"
}

ensure_cluster() {
  if [ -f "$PG_DATA/PG_VERSION" ]; then
    return
  fi
  local pwfile
  pwfile="$(mktemp)"
  printf '%s\n' "$PG_SUPERUSER_PASSWORD" >"$pwfile"
  "$PG_HOME/bin/initdb" -D "$PG_DATA" -U "$PG_SUPERUSER" --pwfile="$pwfile" \
    --auth=scram-sha-256 --encoding=UTF8 --locale=C >/dev/null
  rm -f "$pwfile"
}

is_running() {
  [ -f "$PG_DATA/postmaster.pid" ] && "$PG_HOME/bin/pg_ctl" -D "$PG_DATA" status >/dev/null 2>&1
}

admin_url() {
  echo "postgresql://$PG_SUPERUSER:$PG_SUPERUSER_PASSWORD@127.0.0.1:$PG_PORT/postgres"
}

cmd="${1:-}"
case "$cmd" in
  start)
    ensure_binaries
    ensure_cluster
    if is_running; then
      echo "PostgreSQL already running on 127.0.0.1:$PG_PORT"
    else
      mkdir -p "$PG_SOCKET_DIR"
      "$PG_HOME/bin/pg_ctl" -D "$PG_DATA" -l "$PG_LOG" -w -t 30 \
        -o "-p $PG_PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=$PG_SOCKET_DIR -c max_connections=200" \
        start >/dev/null
      echo "PostgreSQL $PG_VERSION started on 127.0.0.1:$PG_PORT"
    fi
    echo "Admin URL: $(admin_url)"
    ;;
  stop)
    if [ -x "$PG_HOME/bin/pg_ctl" ] && is_running; then
      "$PG_HOME/bin/pg_ctl" -D "$PG_DATA" -m fast -w stop >/dev/null
      echo "PostgreSQL stopped"
    else
      echo "PostgreSQL is not running"
    fi
    ;;
  status)
    if [ -x "$PG_HOME/bin/pg_ctl" ] && is_running; then
      echo "running on 127.0.0.1:$PG_PORT"
    else
      echo "stopped"
      exit 3
    fi
    ;;
  url)
    admin_url
    ;;
  psql)
    shift
    PGPASSWORD="$PG_SUPERUSER_PASSWORD" exec "$PG_HOME/bin/psql" -h 127.0.0.1 -p "$PG_PORT" -U "$PG_SUPERUSER" "$@"
    ;;
  destroy)
    if [ -x "$PG_HOME/bin/pg_ctl" ] && is_running; then
      "$PG_HOME/bin/pg_ctl" -D "$PG_DATA" -m immediate -w stop >/dev/null
    fi
    rm -rf "$PG_DATA"
    echo "Cluster data removed: $PG_DATA"
    ;;
  *)
    echo "Usage: $0 {start|stop|status|url|psql|destroy}" >&2
    exit 2
    ;;
esac
