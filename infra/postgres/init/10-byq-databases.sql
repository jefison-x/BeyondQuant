-- ADR-0016: isolated PostgreSQL databases/roles for BYQ domain stores.
-- Runs once on an empty postgres data volume (docker-entrypoint-initdb.d).
-- Compose POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD already create
-- byq_domain / byq_app. CREATE DATABASE cannot run inside a transaction
-- block, hence \gexec.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'byq_test') THEN
    CREATE ROLE byq_test LOGIN PASSWORD 'byq-test-dev';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'byq_bootstrap') THEN
    CREATE ROLE byq_bootstrap LOGIN PASSWORD 'byq-bootstrap-dev';
  END IF;
END $$;

SELECT 'CREATE DATABASE byq_domain_test OWNER byq_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'byq_domain_test')\gexec

SELECT 'CREATE DATABASE byq_bootstrap OWNER byq_bootstrap'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'byq_bootstrap')\gexec
