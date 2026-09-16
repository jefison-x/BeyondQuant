-- Existing events may already have reached GitHub; only reconcile them.
ALTER TABLE central_feedback_outbox ADD COLUMN create_started INTEGER NOT NULL DEFAULT 0 CHECK (create_started IN (0,1));
UPDATE central_feedback_outbox SET create_started=1;
