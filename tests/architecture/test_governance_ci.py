import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]


def cleanup_script_sandbox(root):
    (root / "scripts/ci").mkdir(parents=True)
    (root / "scripts/release").mkdir(parents=True)
    (root / "scripts/dsh").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/ci/cleanup-resources.sh", root / "scripts/ci/cleanup-resources.sh")
    shutil.copy2(ROOT / "scripts/release/images.py", root / "scripts/release/images.py")
    shutil.copy2(ROOT / "scripts/dsh/authoritative_version.py",
                  root / "scripts/dsh/authoritative_version.py")
    shutil.copy2(ROOT / "scripts/dsh/acp_build.py", root / "scripts/dsh/acp_build.py")
    for relative in ("config/dsh/acp/authoritative.json", "config/dsh/acp-0.2.0-rc.2.identity.json"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    profiles = root / "plugins/dsh-byq/profiles/acp-0.2.0-rc.2"
    profiles.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "plugins/dsh-byq/profiles/acp-0.2.0-rc.2", profiles)
    return root / "scripts/ci/cleanup-resources.sh"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/ci" / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def _check(name, run_id, conclusion="SUCCESS", *, status="COMPLETED", started="2026-09-21T18:00:00Z"):
    return {"name": name, "status": status, "conclusion": conclusion,
            "detailsUrl": f"https://github.com/o/r/actions/runs/{run_id}/job/1",
            "startedAt": started}


def _run(run_id, head, *, name="BeyondQuant CI", status="completed", conclusion="success"):
    return {str(run_id): {"head_sha": head, "status": status, "conclusion": conclusion, "name": name}}


def _pr(head, checks, runs):
    return {"headRefOid": head, "baseRefName": "main", "mergeable": "MERGEABLE",
            "statusCheckRollup": checks, "runs": runs}


class GovernanceCiTests(unittest.TestCase):
    def test_classifier_failure_cannot_become_an_empty_successful_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            classifier = folder / "scripts/ci/classify-changes.sh"
            classifier.parent.mkdir(parents=True)
            classifier.write_text("#!/bin/bash\nexit 23\n")
            classifier.chmod(0o755)
            command = '''source scripts/ci/local-ci.sh
cd "$FAKE_PLAN_ROOT"
git() {
  case "$*" in
    fetch*) return 0;;
    rev-parse*|merge-base*) echo base;;
    diff*) echo README.md;;
    *) return 2;;
  esac
}
if compute_changed; then exit 99; else exit 0; fi
'''
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "FAKE_PLAN_ROOT": str(folder), "GITHUB_ACTIONS": "true"})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("classifier failed", result.stderr)

    def test_removed_inline_ddl_still_selects_integration(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "services/backend/app/store.py"
            source.parent.mkdir(parents=True)
            source.write_text("# DDL removed in this revision\n")
            git = folder / "git"
            git.write_text('#!/bin/bash\nprintf "CREATE TABLE former_table (id TEXT);\\n"\n')
            git.chmod(0o755)
            result = subprocess.run([str(ROOT / "scripts/ci/classify-changes.sh")], cwd=folder,
                input="services/backend/app/store.py\n", capture_output=True, text=True, check=True,
                env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "BYQ_CI_DIFF_BASE": "old-revision"})
            self.assertIn("integration=yes", result.stdout)

    def test_cleanup_failure_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            docker = folder / "docker"
            docker.write_text('''#!/bin/bash
case "$*" in
  info) test "$FAKE_DAEMON" = available;;
  "ps "*) exit 0;;
  "volume inspect byq-ci-postgres-cleanup-contract") exit 0;;
  *) exit 1;;
esac
''')
            docker.chmod(0o755)
            for mode in ("unavailable", "available"):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(ROOT / "scripts/ci/cleanup-resources.sh"),
                        "--scope=cleanup-contract", "--verify-only"], capture_output=True, text=True,
                        env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "FAKE_DAEMON": mode})
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("cleanup verification failed", result.stderr)

    def test_cleanup_retries_late_run_scoped_image_then_requires_stable_absence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            docker = folder / "docker"
            state = folder / "state"
            docker.write_text('''#!/bin/bash
case "$*" in
  info) exit 0;;
  "image inspect byq-ci-stack-cleanup-race-data-worker")
    count=0; test -f "$FAKE_STATE" && count="$(cat "$FAKE_STATE")"
    count=$((count + 1)); echo "$count" > "$FAKE_STATE"
    test "$count" -le 2;;
  "image inspect "*) exit 1;;
  "network inspect "*|"volume inspect "*) exit 1;;
  "ps "*) exit 0;;
  *) exit 0;;
esac
''')
            docker.chmod(0o755)
            result = subprocess.run([str(ROOT / "scripts/ci/cleanup-resources.sh"),
                "--scope=cleanup-race"], capture_output=True, text=True,
                env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}",
                     "FAKE_STATE": str(state), "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "6",
                     "BYQ_CI_CLEANUP_RETRY_SECONDS": "0"})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertGreaterEqual(int(state.read_text()), 4)

    def test_release_cleanup_accepts_only_the_canonical_full_captured_batch(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts/release"))
        import images

        sandbox_parent = Path(tempfile.mkdtemp())
        sandbox = sandbox_parent / "repo"
        cleanup_script = cleanup_script_sandbox(sandbox)
        scope = f"cleanup-release-{uuid.uuid4().hex}-release"
        folder = sandbox / ".ci-artifacts" / scope
        folder.mkdir(parents=True)
        manifest = folder / "image-ids.env"
        docker_dir = sandbox_parent / "fakebin"
        docker_dir.mkdir()
        docker = docker_dir / "docker"
        docker.write_text('''#!/bin/bash
case "$*" in
  info) exit 0;;
  "image inspect "*) exit 1;;
  "ps "*) exit 0;;
  "network inspect "*|"volume inspect "*) exit 1;;
  *) exit 0;;
esac
''')
        docker.chmod(0o755)
        env = {**os.environ, "PATH": f"{docker_dir}:{os.environ['PATH']}",
               "BYQ_CI_CLEANUP_RETRY_SECONDS": "0", "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "2"}
        try:
            manifest.write_text(''.join(
                f"{service}=sha256:{index + 1:064x}\n"
                for index, service in enumerate(images.SERVICES)
            ))
            accepted = subprocess.run(
                [str(cleanup_script), f"--scope={scope}", "--verify-only", "--quiet"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            self.assertFalse(manifest.exists())

            folder.mkdir(parents=True, exist_ok=True)
            manifest.write_text(f"backend=sha256:{'1' * 64}\n")
            incomplete = subprocess.run(
                [str(cleanup_script), f"--scope={scope}", "--verify-only", "--quiet"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(incomplete.returncode, 1)
            self.assertIn("full canonical service set", incomplete.stderr)
            self.assertTrue(manifest.exists())

            unknown_scope = f"cleanup-unknown-{uuid.uuid4().hex}-release"
            unknown_dir = sandbox / ".ci-artifacts" / unknown_scope
            unknown_dir.mkdir(parents=True)
            unknown_manifest = unknown_dir / "image-ids.env"
            unknown_manifest.write_text(f"not-authorized=sha256:{'2' * 64}\n")
            unknown = subprocess.run(
                [str(cleanup_script), f"--scope={unknown_scope}", "--verify-only", "--quiet"],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(unknown.returncode, 1)
            self.assertIn("not a run-scoped service", unknown.stderr)
            self.assertTrue(unknown_manifest.exists())
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            if 'unknown_dir' in locals():
                shutil.rmtree(unknown_dir, ignore_errors=True)
            shutil.rmtree(docker_dir, ignore_errors=True)
            shutil.rmtree(sandbox_parent, ignore_errors=True)

    def test_cleanup_removes_only_scoped_tag_and_retains_foreign_image_reference(self):
        import sys
        sys.path.insert(0, str(ROOT / "scripts/release"))
        import images

        scope = f"cleanup-shared-{uuid.uuid4().hex}"
        service = "acp-product-runner"
        image_id = "sha256:" + "a" * 64
        sandbox_parent = Path(tempfile.mkdtemp())
        sandbox = sandbox_parent / "repo"
        cleanup_script = cleanup_script_sandbox(sandbox)
        manifest_dir = sandbox / ".ci-artifacts" / scope
        manifest_dir.mkdir(parents=True)
        manifest = manifest_dir / "image-ids.env"
        manifest.write_text(f"{service}={image_id}\n")
        docker_dir = sandbox_parent / "fakebin"
        docker_dir.mkdir()
        docker = docker_dir / "docker"
        state = docker_dir / "state"
        calls = docker_dir / "calls"
        project_tag = f"byq-ci-stack-{scope}-{service}"
        docker.write_text(f'''#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_CALLS"
if [ "$1" = info ]; then exit 0; fi
if [ "$1" = ps ]; then exit 0; fi
if [ "$1" = image ] && [ "$2" = inspect ]; then
  if [ "$3" = "{project_tag}" ]; then test ! -f "$FAKE_STATE"; exit $?; fi
  if [ "$3" = "{image_id}" ]; then
    if [ "$4" = --format ]; then echo 'ghcr.io/other/beyondquant/acp-product-runner:retained'; fi
    exit 0
  fi
  exit 1
fi
if [ "$1" = image ] && [ "$2" = rm ]; then
  if [ "$3" = "{project_tag}" ]; then touch "$FAKE_STATE"; exit 0; fi
  if [ "$3" = "{image_id}" ]; then echo unsafe-id-removal >> "$FAKE_CALLS"; exit 91; fi
  exit 0
fi
case "$*" in
  "network inspect "*|"volume inspect "*) exit 1;;
  *) exit 0;;
esac
''')
        docker.chmod(0o755)
        try:
            result = subprocess.run(
                [str(cleanup_script), f"--scope={scope}", "--quiet"],
                capture_output=True, text=True,
                env={**os.environ, "PATH": f"{docker_dir}:{os.environ['PATH']}",
                     "FAKE_STATE": str(state), "FAKE_CALLS": str(calls),
                     "BYQ_CI_CLEANUP_RETRY_SECONDS": "0", "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "3"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = calls.read_text()
            self.assertIn(f"image rm {project_tag}", output)
            self.assertNotIn("image rm " + image_id, output)
            self.assertNotIn("system prune", output)
            self.assertNotIn("image prune", output)
            self.assertFalse(manifest.exists())
        finally:
            shutil.rmtree(manifest_dir, ignore_errors=True)
            shutil.rmtree(docker_dir, ignore_errors=True)
            shutil.rmtree(sandbox_parent, ignore_errors=True)

    def test_cleanup_retains_captured_image_with_repo_digest_reference(self):
        scope = f"cleanup-digest-{uuid.uuid4().hex}"
        service = "acp-product-runner"
        image_id = "sha256:" + "b" * 64
        sandbox_parent = Path(tempfile.mkdtemp())
        sandbox = sandbox_parent / "repo"
        cleanup_script = cleanup_script_sandbox(sandbox)
        manifest_dir = sandbox / ".ci-artifacts" / scope
        manifest_dir.mkdir(parents=True)
        manifest = manifest_dir / "image-ids.env"
        manifest.write_text(f"{service}={image_id}\n")
        docker_dir = sandbox_parent / "fakebin"
        docker_dir.mkdir()
        docker = docker_dir / "docker"
        calls = docker_dir / "calls"
        project_tag = f"byq-ci-stack-{scope}-{service}"
        docker.write_text(f'''#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_CALLS"
if [ "$1" = info ] || [ "$1" = ps ]; then exit 0; fi
if [ "$1" = image ] && [ "$2" = inspect ]; then
  if [ "$3" = "{image_id}" ]; then
    if [ "$4" = --format ] && [[ "$5" == *RepoDigests* ]]; then
      echo 'ghcr.io/beyondquant/acp-product-runner@sha256:{'c' * 64}'
    fi
    exit 0
  fi
  if [ "$3" = "{project_tag}" ]; then exit 1; fi
  exit 1
fi
if [ "$1" = image ] && [ "$2" = rm ]; then
  if [ "$3" = "{image_id}" ]; then echo unsafe-id-removal >> "$FAKE_CALLS"; exit 91; fi
  exit 0
fi
if [ "$1" = network ] || [ "$1" = volume ]; then exit 1; fi
exit 0
''')
        docker.chmod(0o755)
        try:
            result = subprocess.run(
                [str(cleanup_script), f"--scope={scope}", "--quiet"],
                capture_output=True, text=True,
                env={**os.environ, "PATH": f"{docker_dir}:{os.environ['PATH']}",
                     "FAKE_CALLS": str(calls), "BYQ_CI_CLEANUP_RETRY_SECONDS": "0",
                     "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr + calls.read_text())
            output = calls.read_text()
            self.assertIn(f"image rm {project_tag}", output)
            self.assertNotIn("image rm " + image_id, output)
            self.assertFalse(manifest.exists())
            self.assertNotIn("system prune", output)
            self.assertNotIn("image prune", output)
        finally:
            shutil.rmtree(manifest_dir, ignore_errors=True)
            shutil.rmtree(docker_dir, ignore_errors=True)
            shutil.rmtree(sandbox_parent, ignore_errors=True)

    def test_cleanup_removes_acp_resources_after_compose_config_failure_and_honors_keep_postgres(self):
        sandbox_parent = Path(tempfile.mkdtemp())
        sandbox = sandbox_parent / "repo"
        cleanup_script = cleanup_script_sandbox(sandbox)
        docker_dir = sandbox_parent / "fakebin"
        docker_dir.mkdir()
        docker = docker_dir / "docker"
        state = docker_dir / "resources.json"
        calls = docker_dir / "calls"
        docker.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as stream:
    stream.write(" ".join(args) + "\\n")
if args == ["info"]:
    raise SystemExit(0)
if args[:1] == ["compose"]:
    print("missing required Compose application settings", file=sys.stderr)
    raise SystemExit(19)
if args[:1] == ["ps"]:
    raise SystemExit(0)
if args[:2] == ["image", "inspect"]:
    raise SystemExit(1)
if args[:2] == ["image", "rm"]:
    raise SystemExit(0)
if args[0] in ("network", "volume") and args[1] == "inspect":
    resource = args[2]
    data = json.loads(pathlib.Path(os.environ["FAKE_STATE"]).read_text())
    owner = data[args[0]].get(resource)
    if owner is None:
        raise SystemExit(1)
    if "--format" in args:
        template = args[args.index("--format") + 1]
        if "com.docker.compose.project" in template and owner == "project":
            print(os.environ["COMPOSE_PROJECT_NAME"])
        elif "byq.ci.scope" in template and owner == "scope":
            print(os.environ["BYQ_CI_SCOPE"])
    raise SystemExit(0)
if args[0] in ("network", "volume") and args[1] == "rm":
    data = json.loads(pathlib.Path(os.environ["FAKE_STATE"]).read_text())
    for resource in args[2:]:
        if data[args[0]].get(resource) not in ("project", "scope"):
            raise SystemExit(2)
        del data[args[0]][resource]
    pathlib.Path(os.environ["FAKE_STATE"]).write_text(json.dumps(data))
    raise SystemExit(0)
raise SystemExit(0)
''')
        docker.chmod(0o755)
        try:
            for keep_postgres in (False, True):
                scope = f"cleanup-acp-{uuid.uuid4().hex}"
                project = f"byq-ci-stack-{scope}"
                networks = {
                    f"byq-ci-product-{scope}": "project",
                    f"byq-ci-signal-sandbox-{scope}": "project",
                    f"{project}-acp-judgment": "project",
                    f"byq-ci-network-{scope}": "scope",
                }
                volumes = {
                    f"byq-ci-postgres-{scope}": "project",
                    f"byq-ci-domain-{scope}": "project",
                    f"byq-ci-ml-model-{scope}": "project",
                    f"byq-ci-dsh-sessions-{scope}": "project",
                    f"byq-ci-workflow-traces-{scope}": "project",
                    f"{project}-acp-product-sessions": "project",
                    f"{project}-acp-product-state": "project",
                    f"{project}-acp-product-control": "project",
                    f"{project}-acp-judgment-sessions": "project",
                    f"{project}-acp-runner-control": "project",
                    f"{project}-acp-runner-state": "project",
                    f"byq-ci-postgres-data-{scope}": "scope",
                }
                state.write_text(json.dumps({"network": networks, "volume": volumes}))
                env = {**os.environ, "PATH": f"{docker_dir}:{os.environ['PATH']}",
                       "FAKE_STATE": str(state), "FAKE_CALLS": str(calls),
                       "BYQ_CI_CLEANUP_RETRY_SECONDS": "0",
                       "BYQ_CI_CLEANUP_MAX_ATTEMPTS": "1"}
                args = [str(cleanup_script), f"--scope={scope}", "--quiet"]
                if keep_postgres:
                    args.append("--keep-postgres")
                result = subprocess.run(args, capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0,
                                 result.stdout + result.stderr + calls.read_text() + state.read_text())
                remaining = json.loads(state.read_text())
                acp_network = f"{project}-acp-judgment"
                acp_volumes = {f"{project}-acp-{name}" for name in (
                    "product-sessions", "product-state", "product-control",
                    "judgment-sessions", "runner-control", "runner-state",
                )}
                self.assertNotIn(acp_network, remaining["network"])
                self.assertTrue(acp_volumes.isdisjoint(remaining["volume"]))
                if keep_postgres:
                    self.assertIn(f"byq-ci-network-{scope}", remaining["network"])
                    self.assertIn(f"byq-ci-postgres-data-{scope}", remaining["volume"])
                else:
                    self.assertNotIn(f"byq-ci-network-{scope}", remaining["network"])
                    self.assertNotIn(f"byq-ci-postgres-data-{scope}", remaining["volume"])
                output = calls.read_text()
                self.assertIn(
                    f"compose -f {sandbox}/compose.yml -f {sandbox}/compose.override.yml down --remove-orphans",
                    output,
                )
                self.assertNotIn("system prune", output)
                self.assertNotIn("volume prune", output)
        finally:
            shutil.rmtree(docker_dir, ignore_errors=True)
            shutil.rmtree(sandbox_parent, ignore_errors=True)

    def test_image_build_failure_never_runs_old_image(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            docker = folder / "docker"
            calls = folder / "calls"
            docker.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$FAKE_CALLS"\n'
                              'case "$*" in *" build "*) exit 19;; esac\nexit 0\n')
            docker.chmod(0o755)
            command = '''source scripts/ci/local-ci.sh
NO_CLEANUP=1
ONLY=runtime
acquire_heavy_capacity() { return 0; }
if ! build_test_images; then exit 1; fi
check_runtime
'''
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "PATH": f"{folder}:{os.environ['PATH']}", "FAKE_CALLS": str(calls), "BYQ_CI_SCOPE": "fake-image-contract", "BYQ_CI_GHA_CACHE": "0"})
            self.assertEqual(result.returncode, 1)
            self.assertIn("build backend runtime-adapter mcp", calls.read_text())
            self.assertNotIn("run --rm", calls.read_text())
            self.assertNotIn("beyondquant-runtime-adapter", calls.read_text())

    def test_build_and_tests_share_scope_and_environment_is_test_only(self):
        command = '''source scripts/ci/local-ci.sh
prepare_ci_compose_env
test "$(ci_image runtime-adapter)" = "byq-ci-stack-fake-env-contract-runtime-adapter"
test "$COMPOSE_FILE" = "$REPO_ROOT/compose.yml:$REPO_ROOT/compose.override.yml"
test "$COMPOSE_DISABLE_ENV_FILE" = 1
test "$BYQ_POSTGRES_VOLUME_EXTERNAL" = false
test "$BYQ_DATABASE_URL" = postgresql+psycopg://byq_app:byq-app-dev@postgres:5432/byq_domain
test "$BYQ_F6_EXECUTOR_ENABLED" = 0
test -z "$DEEPSEEK_API_KEY$OPENCODE_API_KEY$TUSHARE_TOKEN$BYQ_FEEDBACK_GITHUB_TOKEN$BYQ_FEEDBACK_HUB_URL"
test -z "${BYQ_DSH_RUNTIME_DOCKERFILE:-}${BYQ_DSH_COMPATIBILITY_RELEASE:-}${BYQ_DSH_SESSION_ROOT:-}${DSH_SESSION_ROOT:-}"
test "$BYQ_DSH_PROVIDER" = opencode-go-chat
test "$BYQ_DSH_MODEL" = deepseek-v4.1-flash
test "$BYQ_ACP_JUDGMENT_NETWORK_NAME" = "byq-ci-stack-fake-env-contract-acp-judgment"
test "$BYQ_ACP_PRODUCT_SESSIONS_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-product-sessions"
test "$BYQ_ACP_PRODUCT_STATE_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-product-state"
test "$BYQ_ACP_PRODUCT_CONTROL_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-product-control"
test "$BYQ_ACP_JUDGMENT_SESSIONS_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-judgment-sessions"
test "$BYQ_ACP_RUNNER_CONTROL_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-runner-control"
test "$BYQ_ACP_RUNNER_STATE_VOLUME_NAME" = "byq-ci-stack-fake-env-contract-acp-runner-state"
'''
        result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
            env={**os.environ, "BYQ_CI_SCOPE": "fake-env-contract", "BYQ_DATABASE_URL": "PRODUCTION",
                 "DEEPSEEK_API_KEY": "private", "OPENCODE_API_KEY": "private", "TUSHARE_TOKEN": "private",
                 "BYQ_FEEDBACK_GITHUB_TOKEN": "private", "BYQ_FEEDBACK_HUB_URL": "https://production.invalid",
                 "COMPOSE_FILE": "production.yml", "BYQ_POSTGRES_VOLUME_EXTERNAL": "true",
                 "BYQ_F6_EXECUTOR_ENABLED": "1",
                 "BYQ_DSH_RUNTIME_DOCKERFILE": "old-sdk.Dockerfile",
                 "BYQ_DSH_COMPATIBILITY_RELEASE": "old-sdk-release",
                 "BYQ_DSH_SESSION_ROOT": "/old-sdk/sessions", "DSH_SESSION_ROOT": "/old-sdk/sessions",
                 "BYQ_ACP_JUDGMENT_NETWORK_NAME": "foreign-network",
                 "BYQ_ACP_PRODUCT_SESSIONS_VOLUME_NAME": "foreign-volume"})
        self.assertEqual(result.returncode, 0, result.stderr)
        source = (ROOT / "scripts/ci/local-ci.sh").read_text()
        for service in ("backend", "gateway", "runtime-adapter", "mcp"):
            self.assertTrue(
                f'"$(ci_image {service})"' in source
                or f'"$(ci_image_ref {service})"' in source,
                f"run-scoped image reference missing for {service}")
            self.assertNotIn(f"beyondquant-{service}", source)
        self.assertIn("--no-build --wait", source)

    def test_compose_route_is_shared_checked_in_source_and_fails_closed(self):
        # ADR-0110: the ordered Compose route is the single checked-in selection
        # in scripts/release/images.py, consumed by the CI shell. A missing or
        # empty selection must abort, never fall back to a hard-coded route.
        expected = os.pathsep.join((
            str(ROOT / "compose.yml"), str(ROOT / "compose.override.yml")))
        positive = '''source scripts/ci/local-ci.sh
set_ci_compose_files
test "$COMPOSE_FILE" = "$EXPECTED_ROUTE"
test "${#CI_COMPOSE_FILES[@]}" -eq 2
'''
        result = subprocess.run(["bash", "-c", positive], cwd=ROOT, capture_output=True,
            text=True, env={**os.environ, "EXPECTED_ROUTE": expected,
                            "BYQ_CI_SCOPE": "route-shared-contract"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for body in ('acp_compose_route_files() { return 7; }',
                     'acp_compose_route_files() { printf ""; }'):
            negative = f'''source scripts/ci/local-ci.sh
{body}
COMPOSE_FILE="sentinel"
if set_ci_compose_files; then exit 9; fi
test "$COMPOSE_FILE" = "sentinel"
'''
            result = subprocess.run(["bash", "-c", negative], cwd=ROOT, capture_output=True,
                text=True, env={**os.environ, "BYQ_CI_SCOPE": "route-shared-contract"})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("no fallback route is permitted", result.stderr)
        source = (ROOT / "scripts/ci/local-ci.sh").read_text()
        self.assertNotIn(
            'CI_COMPOSE_FILES=("$REPO_ROOT/compose.yml" "$REPO_ROOT/compose.override.yml")',
            source)
        self.assertIn('scripts/release/images.py" route', source)

    def test_f6_release_lane_fails_closed_when_captured_batch_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            command_log = Path(temp) / "commands.txt"
            command = '''source scripts/ci/local-ci.sh
export COMPOSE_PROJECT_NAME="byq-ci-stack-$BYQ_CI_SCOPE"
CI_IMAGE_IDS[runtime-adapter]=sha256:captured-acp-image
run_interruptible() {
  printf '%q ' "$@" >> "$FAKE_COMMANDS"
  printf '\\n' >> "$FAKE_COMMANDS"
  if [[ "$1" == docker ]]; then return 0; fi
  "$@"
}
check_f6_chain
test "$FAIL" -eq 1
'''
            result = subprocess.run(["bash", "-c", command], cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "BYQ_CI_SCOPE": "f6-offline-" + uuid.uuid4().hex[:12],
                     "COMPOSE_FILE": os.pathsep.join((str(ROOT / "compose.yml"),
                                                       str(ROOT / "compose.override.yml"))),
                     "BYQ_F6_EXECUTOR_ENABLED": "0",
                     "FAKE_COMMANDS": str(command_log)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("F6 ACP Product/Worker background-completion release fixture", result.stdout)
            self.assertIn("[FAIL] F6 ACP Product/Worker background-completion release fixture", result.stdout)
            self.assertIn("ACP F6 release fixture failed closed: captured_image_manifest_invalid", result.stderr)
            calls = command_log.read_text()
            self.assertIn("sha256:captured-acp-image", calls)
            self.assertIn("--network none", calls)
            self.assertIn("scripts/evidence/acp-f6-release-fixture.py", calls)
            self.assertNotIn("runtime-candidate", calls)
            self.assertNotIn("docker compose", calls)

    def test_merge_preflight_fails_closed(self):
        evaluate = module("check-github-gates").evaluate
        repo = {"allow_auto_merge": True, "allow_squash_merge": True}
        protection = {"required_status_checks": {"strict": True, "contexts": ["local-ci", "ci-gate"]}}
        head = "a" * 40
        self.assertTrue(evaluate(repo, None))
        self.assertTrue(evaluate({**repo, "allow_auto_merge": False}, protection))
        self.assertTrue(evaluate(repo, {"required_status_checks": {"strict": False}}))
        pr = _pr(head, [_check("local-ci", 100, started="2026-09-21T18:00:00Z"),
                        _check("ci-gate", 100, started="2026-09-21T18:00:01Z")], {**_run(100, head)})
        self.assertEqual(evaluate(repo, protection, pr), [])
        extended = {"required_status_checks": {"strict": True, "contexts": ["local-ci", "ci-gate", "security"]}}
        self.assertTrue(evaluate(repo, extended, pr))
        review = {**protection, "required_pull_request_reviews": {"required_approving_review_count": 1}}
        self.assertTrue(evaluate(repo, review, pr))
        self.assertEqual(evaluate(repo, review, {**pr, "reviewDecision": "APPROVED"}), [])
        for result in ("SKIPPED", "NEUTRAL", "FAILURE", "CANCELLED"):
            with self.subTest(result=result):
                bad = _pr(head, [_check("local-ci", 100, result, started="2026-09-21T18:00:00Z"),
                                 _check("ci-gate", 100, started="2026-09-21T18:00:01Z")], {**_run(100, head)})
                self.assertTrue(evaluate(repo, protection, bad))

    def test_merge_preflight_selects_only_the_latest_run_for_the_exact_head(self):
        evaluate = module("check-github-gates").evaluate
        repo = {"allow_auto_merge": True, "allow_squash_merge": True}
        protection = {"required_status_checks": {"strict": True, "contexts": ["local-ci", "ci-gate"]}}
        head = "b" * 40
        # Older run on the SAME head: cancelled, exposing the generic matrix
        # `checks` name plus failed aggregate gates.
        old = [_check("plan", 100, "CANCELLED", started="2026-09-21T18:17:11Z"),
               _check("checks", 100, "CANCELLED", started="2026-09-21T18:17:12Z"),
               _check("local-ci", 100, "FAILURE", started="2026-09-21T18:17:15Z"),
               _check("ci-gate", 100, "FAILURE", started="2026-09-21T18:17:21Z")]
        # Newer run on the same head: expanded lane names, all green.
        new = [_check("plan", 200, started="2026-09-21T18:17:28Z"),
               _check("checks (backend, false)", 200, started="2026-09-21T18:17:39Z"),
               _check("local-ci", 200, started="2026-09-21T18:36:40Z"),
               _check("ci-gate", 200, started="2026-09-21T18:36:48Z")]
        pr = _pr(head, old + new, {**_run(100, head, conclusion="cancelled"), **_run(200, head)})
        self.assertEqual(evaluate(repo, protection, pr), [])
        # Latest run failure / cancellation / incompleteness is BLOCKED.
        for conclusion, status in (("failure", "completed"), ("cancelled", "completed"),
                                   ("success", "in_progress")):
            with self.subTest(conclusion=conclusion, status=status):
                runs = {**_run(100, head, conclusion="cancelled"),
                        **_run(200, head, status=status, conclusion=conclusion)}
                self.assertTrue(evaluate(repo, protection, {**pr, "runs": runs}))
        # Missing run metadata (ownership unconfirmed) is BLOCKED.
        self.assertTrue(evaluate(repo, protection, {**pr, "runs": _run(100, head, conclusion="cancelled")}))
        # A different head's success is NOT adopted.
        runs = {**_run(100, head, conclusion="cancelled"), **_run(200, "c" * 40)}
        self.assertTrue(evaluate(repo, protection, {**pr, "runs": runs}))
        # The older cancelled suite alone is BLOCKED, never silently accepted.
        self.assertTrue(evaluate(repo, protection, _pr(head, old,
            _run(100, head, conclusion="cancelled"))))

    def test_pull_request_trigger_excludes_body_only_edits(self):
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        self.assertIn("types: [opened, synchronize, reopened]", workflow)
        self.assertNotIn("ready_for_review]", workflow)
        self.assertNotIn("types: [opened, synchronize, reopened, edited", workflow)
        self.assertNotIn("edited]", workflow)


    def test_log_redaction_retains_failure_but_removes_secrets(self):
        redact = module("redact-log").redact
        raw = 'FAILED test_login Authorization: Bearer abc123 password="very secret" https://user:pass@host/path sk-abcdefghijklmnop known-secret-value'
        clean = redact(raw, ("known-secret-value",))
        self.assertIn("FAILED test_login", clean)
        for secret in ("abc123", "very secret", "user:pass", "abcdefghijklmnop", "known-secret-value"):
            self.assertNotIn(secret, clean)
        output = subprocess.check_output(["python3", str(ROOT / "scripts/ci/redact-log.py")],
            input="-----BEGIN RSA PRIVATE KEY-----\nprivatebytes\n-----END RSA PRIVATE KEY-----\nAssertionError\n", text=True)
        self.assertNotIn("privatebytes", output)
        self.assertIn("AssertionError", output)

    def test_fork_routing_and_non_skippable_aggregate_gate(self):
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 5)
        self.assertNotIn('"self-hosted"', workflow)
        self.assertNotIn('runs-on: ${{', workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("needs: [local-ci, contribution]", workflow)
        self.assertIn('test "$CI_RESULT" = success', workflow)
        self.assertIn('test "$CONTRIBUTION_RESULT" = success', workflow)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha || github.sha }}", workflow)
        self.assertIn("--expected-head", workflow)
        self.assertIn("COMPOSE_PARALLEL_LIMIT: '2'", workflow)
        self.assertIn("BYQ_CI_CLEANUP_MAX_ATTEMPTS: '20'", workflow)
        self.assertIn("stable_absence", (ROOT / "scripts/ci/cleanup-resources.sh").read_text())
        self.assertIn("sha256sum --check", workflow)
        self.assertIn("--redact=100", workflow)
        self.assertIn("python3 scripts/ci/redact-log.py | tee", workflow)
        self.assertIn("actions/upload-artifact@", workflow)
        self.assertIn("package-manager-cache: false", workflow)
        action_uses = re.findall(r"uses: actions/[\w-]+@([^\s]+)\s+#\s+(v[^\s]+)", workflow)
        self.assertEqual(len(action_uses), 7)
        for revision, release in action_uses:
            self.assertRegex(revision, r"^[0-9a-f]{40}$")
            self.assertRegex(release, r"^v(7\.|8$)")
        self.assertNotIn("# v5", workflow)

    def test_ci_upload_is_explicit_and_missing_evidence_fails(self):
        workflow = (ROOT / ".github/workflows/ci-selfhosted.yml").read_text()
        upload = workflow.split("- name: Upload sanitized CI evidence\n", 1)[1].split("\n  contribution:", 1)[0]
        self.assertIn("if: always()", upload)
        self.assertIn("include-hidden-files: true", upload)
        self.assertIn("if-no-files-found: error", upload)
        self.assertIn("path: |\n            .ci-artifacts/checks.log\n            .ci-artifacts/cleanup.log", upload)
        self.assertNotIn("*.log", upload)
        self.assertIn("retention-days: 7", upload)
        for name in ("checks", "cleanup"):
            self.assertIn(f"python3 scripts/ci/redact-log.py | tee .ci-artifacts/{name}.log", workflow)

    def test_worktree_verifier_rejects_primary_unregistered_and_symlink_escape(self):
        verify = module("verify-worktree").verify
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            repo = parent / "repo"
            root = parent / "worktrees"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=CI", "-c", "user.email=ci@example.invalid", "commit", "-qm", "initial", "--allow-empty"], check=True)
            tree = root / "feature"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-qb", "test-feature", str(tree)], check=True)
            verify(tree, root)
            with self.assertRaises(ValueError):
                verify(repo, parent)
            with self.assertRaises(ValueError):
                verify(tree / ".git", root)
            escape = root / "escape"
            escape.symlink_to(repo, target_is_directory=True)
            with self.assertRaises(ValueError):
                verify(escape, root)

    def test_current_phase_comes_from_status_not_frozen_test_literal(self):
        import re
        status = (ROOT / "docs/roadmap/STATUS.md").read_text()
        plan = (ROOT / "docs/roadmap/IMPLEMENTATION_PLAN.md").read_text()
        matches = re.findall(r"<!-- byq:current-completed-phase=(\d+) -->", status)
        self.assertEqual(len(matches), 1)
        self.assertRegex(plan, rf"Phase {matches[0]} .*COMPLETE")


if __name__ == "__main__":
    unittest.main()
