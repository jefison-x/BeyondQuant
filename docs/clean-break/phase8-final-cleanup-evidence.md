# Phase 8 classified old-environment cleanup — 2026-09-28

The maintainer subsequently approved removing all resources that should be
removed from the old BYQ environment. This action remained scoped to the
[exact preflight manifest](phase8-final-targets.json), following the earlier
[five-target first pass](phase8-first-pass-evidence.md). The independent Sol
Reviewer passed the revised deletion scope before execution.

The final old Product database dump at
`/home/jefison/backups/byq-clean-break-final-20260927T234310Z/byq-domain.dump`
was verified again before removal: 2,102,827,616 bytes and SHA-256
`0d62af957f545da40fc13083914c1d4cc614f04414fe6806d36bc772a4d06183`.
The archive and manifest were left untouched. The old source volume was never
used as a migration input.

Immediately before deletion, Root checked every target's creation time,
labels or image tags, ID, and zero container references. Ten unattached named
old BYQ volumes and 68 unused old BYQ GHCR digest-only images matched the
manifest. Each was removed by exact name or ID without force or prune. The
[machine-readable result](phase8-final-cleanup-results.json) records 10/10
volume removals and 68/68 image removals, with no failures. Post-action checks
confirmed all 78 targets absent, 33 volumes remaining, only the three built-in
networks, and the same one unrelated exited container. No service was stopped;
no production deployment, push, merge, or existing backup change occurred.

Five BYQ-named but unlabeled volumes remain because their ownership/purpose
could not be proved from retained metadata: `byq-20f-pgdata`,
`byq-postgres-recovery-20260827`, `byq-phase61-clean-restore-20260827`,
`byq-phase68-test-data`, and `byq-v090-default-test-sessions`. The 28 anonymous
volumes, unrelated exited container, reusable base/DSH/database images,
retained U6/U7 and rollback tags, and unknown dangling images also remain.
These excluded resources are not prerequisites for the new environment.

This operation finishes the classified deletion list. Independent Tester
verified exact target absence and preservation of all excluded categories;
independent Sol Reviewer returned Functional PASS / Tests PASS / Clean Break
Architecture PASS. Root accepted **Phase 8 overall PASS**. Phase 9 has not
begun.
