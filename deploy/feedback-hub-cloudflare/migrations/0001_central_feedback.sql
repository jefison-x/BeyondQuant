CREATE TABLE central_feedback (
  receipt_id TEXT PRIMARY KEY,
  installation_hash TEXT NOT NULL,
  source_event_hash TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('received','triaged','accepted','rejected','duplicate','publishing','published')),
  duplicate_of TEXT REFERENCES central_feedback(receipt_id),
  github_repository TEXT,
  github_issue_number INTEGER,
  github_html_url TEXT,
  github_provider_identity TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(installation_hash, source_event_hash)
);

CREATE INDEX central_feedback_page ON central_feedback(status, created_at, receipt_id);
CREATE INDEX central_feedback_fingerprint ON central_feedback(fingerprint);

CREATE TABLE central_feedback_audit (
  audit_id TEXT PRIMARY KEY,
  receipt_id TEXT NOT NULL REFERENCES central_feedback(receipt_id),
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE central_feedback_outbox (
  event_id TEXT PRIMARY KEY,
  receipt_id TEXT NOT NULL UNIQUE REFERENCES central_feedback(receipt_id),
  snapshot_json TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','dispatching','enqueued','publishing','retry_wait','published','failed_terminal')),
  attempt INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL,
  lease_owner TEXT,
  lease_expires_at TEXT,
  lease_fence INTEGER NOT NULL DEFAULT 0,
  last_error_category TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX central_feedback_outbox_due ON central_feedback_outbox(state, next_attempt_at, event_id);
