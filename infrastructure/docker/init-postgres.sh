#!/bin/bash
# Creates the application owner role and database on first boot of the
# compose Postgres service (same names as scripts/dev.sh setup).
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'streamclip_owner') THEN
      CREATE ROLE streamclip_owner LOGIN PASSWORD 'streamclip' CREATEROLE BYPASSRLS;
    END IF;
  END
  \$\$;
  SELECT 'CREATE DATABASE streamclip_dev OWNER streamclip_owner'
  WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'streamclip_dev')\gexec
EOSQL
