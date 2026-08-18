# Self-Hosted CI (GitHub Actions Runner on the local machine)

Status: **Proposed** — companion to `scripts/ci/local-ci.sh` and
`.github/workflows/ci-selfhosted.yml`.

## Why

GitHub-hosted Actions runners now require paid billing in this account, so PR
checks (`ci.yml`) fail with "account payments / spending limit" errors. A
**self-hosted runner** lets the existing GitHub PR workflow keep working —
GitHub still orchestrates the checks and shows status on PRs — while every
check **executes on the local machine** for free.

The self-hosted workflow runs the project's own local CI script
(`scripts/ci/local-ci.sh --all`), which is the same code as `make local-ci`,
so the PR status reflects the exact checks we already validated locally.

## Architecture

```
GitHub (orchestration only, free)
  └─ PR / push ─► .github/workflows/ci-selfhosted.yml
                     └─ job: local-ci  runs-on: [self-hosted, linux, x64, byq]
                          └─ local machine: actions-runner (systemd service)
                               ├─ docker (service tests use clean CI postgres)
                               ├─ python3 (architecture tests)
                               ├─ node 22 (frontend build + vitest)
                               └─ scripts/ci/local-ci.sh --all
```

The local CI script deliberately does **not** use `docker compose up` for the
service checks (it mounts sources into existing images and spins up a clean
CI-only postgres), so it never collides with the developer's own running
`beyondquant` compose stack.

## Prerequisites on the runner machine

| Requirement | Minimum | Notes |
|---|---|---|
| OS | Linux x64 (this repo's setup) | macOS/Windows work but use matching runner package |
| Docker Engine + Compose v2 | recent | runner user must be in the `docker` group (or have socket access) |
| Python 3 | 3.10+ | used by `python3 -m unittest` (architecture) and services already containerized |
| Node.js | 22 | used by frontend build + vitest (matches GitHub setup-node 22) |
| Disk | ≥ 50 GB free | service images + node_modules + postgres volumes |
| RAM | ≥ 8 GB | compose build and parallel service tests |
| `git`, `bash` | — | runner and local-ci script requirements |

Check quickly:

```bash
docker --version && docker compose version
python3 --version
node --version && npm --version
git --version
id -nG | tr ' ' '\n' | grep -q docker && echo "docker group OK"
```

## Register the runner (one-time)

1. Open **GitHub → repo (jefison-x/BeyondQuant) → Settings → Actions →
   Runners → New self-hosted runner → Linux → x64**.
2. Copy the shown `download` + `configure` snippet (it includes a
   one-time registration token). On the local machine:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
# <download command from GitHub, e.g.>
curl -sL -o actions-runner-linux-x64.tar.gz <URL-from-GitHub>
tar xzf actions-runner-linux-x64.tar.gz
# <configure command from GitHub, plus labels; example:>
./config.sh --url https://github.com/jefison-x/BeyondQuant \
            --token <TOKEN> \
            --name byq-local-runner \
            --labels byq,linux,x64 \
            --work _work
```

3. Start it in the foreground to confirm it connects (watch for
   "Listening for Jobs"):

```bash
./run.sh
```

4. Back on GitHub: **Runners → the new runner should show "Idle"**. Cancel the
   foreground run and install it as a service (next section).

> Labels must include `byq` (plus `linux,x64`) because the workflow pins
> `runs-on: [self-hosted, linux, x64, byq]`. If you change the label, update
> the workflow to match.

## Run the runner as a service (systemd)

The bundled `svc.sh` registers a systemd service:

```bash
cd ~/actions-runner
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
# logs:
sudo ./svc.sh check
# uninstall (if ever needed):
# sudo ./svc.sh uninstall
```

Make sure the service user can talk to Docker (add it to the docker group and
restart the service):

```bash
sudo usermod -aG docker <runner-user>
sudo systemctl restart actions.runner.jefison-x-BeyondQuant.byq-local-runner.service
```

## The workflow file

- `.github/workflows/ci-selfhosted.yml` — new workflow (this repo). It:
  - triggers on PR and on push to `main` / `bootstrap/**`;
  - checks out with full history (`fetch-depth: 0`) and fetches `origin/main`
    so the script's path-filtering baseline is correct;
  - runs `./scripts/ci/local-ci.sh --all` (all six core checks: architecture,
    backend, gateway, runtime-adapter, mcp, frontend);
  - sets `COMPOSE_PROJECT_NAME=byq-ci-runner` as a guard against any future
    compose usage colliding with the local stack.
- The original `ci.yml` (GitHub-hosted) remains in the repo for reference /
  rollback. Once the runner is stable, you can disable it (GitHub → repo →
  Settings → Actions → General → Actions permissions → Disable workflow, or
  delete the file in a follow-up PR) so no paid jobs are ever scheduled.

## Verify end-to-end

1. Runner online: GitHub → Settings → Actions → Runners → **Idle**.
2. Open or update any PR — the `BeyondQuant Self-Hosted CI / local-ci` check
   appears. Watch `~/actions-runner/_diag` or `sudo ./svc.sh check` logs.
3. Expected: the check runs `local-ci.sh --all` and reports the same results
   we already validated locally (all six core checks PASS).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Job stuck "Queued" / never starts | runner offline or wrong label | runner online in Settings; labels include `byq`; `sudo ./svc.sh status` |
| "permission denied ... docker.sock" | runner user lacks docker access | add to `docker` group, restart service |
| `tsc: not found` (mcp) | host node_modules partial | script mounts only `src/tests`; ensure image is current (`docker compose build mcp`) |
| Backend "no schema has been selected" | shared `byq_postgres_data` volume is bad | script auto-creates clean `byq-ci-postgres`; verify no stale container on the label |
| OOM during build | RAM too low | build serially (`--build` once), stop local compose during heavy jobs |
| Local `docker compose` stack broken after CI | collision | CI uses `byq-ci-runner` project name + clean postgres; `docker ps` to confirm |

## Security notes

- A self-hosted runner token has write access to the repository it is
  registered to. Keep `~/actions-runner` on a trusted machine and prefer
  running on pull_request (contents read only) as configured.
- Never run untrusted third-party workflows on the self-hosted runner; only
  this repo's workflow is scheduled here.
- The runner does not require Tushare/DeepSeek secrets for the core checks;
  keyless tests are used. Keep real secrets out of the runner environment.
