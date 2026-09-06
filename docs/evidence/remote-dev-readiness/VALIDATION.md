# Remote development readiness

Date: 2026-09-06

## Scope

The maintainer requested that development resume after resolving its prerequisites.
This maintenance aligns the GitHub-hosted application's Node toolchain with the
frontend's declared Node 22 engine and Node 22 Docker build. GitHub Actions'
internal Node 24 runtime remains unchanged. Product Phase 97 and the DSH default
release remain unchanged.

Branch: chore/remote-dev-readiness.
Base: 85b66d661f488d596045b4541e2047f0e1683554.
Worktree: /home/jefison/projects/.byq-worktrees/remote-dev-readiness.

## Environment checks

- SSH public-key authentication and pinned host verification passed.
- Remote Codex CLI 0.153.4 is authenticated using ChatGPT. Non-interactive SSH
  can invoke /home/jefison/.npm-global/bin/codex explicitly.
- GitHub authentication and read access passed; main matched the remote at inspection.
- Node 22.23.2 satisfies the frontend manifest and lockfile engine constraint.
- Host Python 3.14.4 satisfies the backend manifest; service tests use the existing
  Python 3.13 containers. System Python was not replaced.
- Docker/Compose access and Compose configuration validation passed.
- npm and PyPI endpoints were reachable.
- Chrome DevTools MCP 1.8.0 completed initialization and a real list_pages call
  against its isolated headless Chrome instance.
- The existing U2 worktree passed verify-worktree.py; no Codex/test process was
  found before dependency installation.
- npm ci completed in U2 frontend, MCP and runtime directories without changing
  their lockfiles. Playwright 1.62.1 launched Chromium 151.0.7922.34 and verified
  a local test page. U2 MCP TypeScript compilation and research translation test,
  both provenance generator unit tests and generated-policy check passed.

These U2 checks are development-environment evidence, not U2 qualification or
completion. Existing U2 source changes were preserved.

## Maintenance validation

Command: scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke

Result: all 25 selected local checks passed; process exit status 0.

- Architecture: 135 tests passed.
- Backend: 327 passed, 1 skipped, 7 subtests passed.
- Frontend: production build, 148 unit tests and dependency audit passed.
- Browser: 20 mocked journeys and 9 real Product API journeys passed.
- Gateway, Runtime Adapter, MCP and feedback-service checks passed.
- Isolated Compose smoke, restart persistence and two-user isolation passed.
- Test scope local-3149819 has no remaining containers, networks, volumes or
  named images after cleanup.
- Existing Product frontend and Gateway health endpoints still respond successfully.
  The main checkout is clean.

The sanitized log is stored at /tmp/byq-remote-dev-readiness/local-ci.log on the
development host. GitHub CI for this maintenance change has not run.
No push, merge or deployment is claimed by this report.
