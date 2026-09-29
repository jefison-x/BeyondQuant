"""Market-data import conflict policy constants.

The SQLite-to-PostgreSQL application migration path was retired for the BYQ 0.10
fresh-schema baseline. Market-data stores retain these explicit conflict
policies for canonical dataset ingestion.
"""

KEEP_NEW = "KEEP_NEW"
VERIFY_EQUAL = "VERIFY_EQUAL"
REPORT_MISMATCH = "REPORT_MISMATCH"
CONFLICT_POLICIES = {KEEP_NEW, VERIFY_EQUAL, REPORT_MISMATCH}
