"""Bounded U6 synthetic old -> new -> old rehearsal; never deploy production.

Run as a module. Raw logical backups stay in a private temporary directory;
stdout and result.json contain identities, counts and outcomes only.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from scripts.dsh.admission import initialize, set_state
from scripts.dsh.retain_u6_ci_images import load_receipt
from . import live_stack
from .live_model_probe import Client, PROMPTS, assistant_messages, counts, fake_hub_evidence

OLD, NEW = "dsh-0.1.1rc1", "dsh-0.1.2rc1"


def emit(stage, **values):
    print(json.dumps({"stage": stage, **values}, sort_keys=True), flush=True)


class Rehearsal:
    def __init__(self, directory: Path, environment: dict, ci_scope: str | None = None):
        if re.fullmatch(r"/tmp/byq-u6-[a-z0-9_]{8}", str(directory)) is None:
            raise ValueError("only a dedicated synthetic temporary directory is allowed")
        self.directory, self.environment = directory, environment
        if ci_scope is not None and re.fullmatch(r"local-u6-[a-z0-9-]{3,60}", ci_scope) is None:
            raise ValueError("only an explicit U6 CI image scope is allowed")
        self.ci_scope = ci_scope
        self.scope = "byq-u5-u6-" + directory.name.removeprefix("byq-u6-").replace("_", "-")
        self.gate = directory / "gate" / "admission.state"
        self.release = OLD
        self.files = {release: directory / f"{release}.json" for release in (OLD, NEW)}
        self.result = {"schema_version": "dsh-u6-rehearsal.v1", "scope": self.scope,
                       "result": "IN_PROGRESS", "production_changed": False, "steps": []}

    def prepare(self):
        # The gate is non-secret and must be traversable by container UIDs.
        # Raw backups have their own private directory and 0600 files.
        self.directory.chmod(0o755)
        self.gate.parent.mkdir(mode=0o755)
        (self.directory / "backups").mkdir(mode=0o700)
        initialize(self.gate)
        for release, path in self.files.items():
            value = live_stack.manifest(self.scope, release, 18210, rehearsal_gate=str(self.gate.parent))
            with path.open("x") as output:
                json.dump(value, output, indent=2)

    def compose(self, release, *args):
        return ["docker", "compose", "--env-file", "/dev/null", "-p", self.scope,
                "-f", str(self.files[release]), *args]

    def container(self, service):
        return f"{self.scope}-{service}-1"

    def check(self):
        checked = live_stack.preflight(self.files[self.release])
        checked["build_revision"] = live_stack.attest_runtime_build(self.files[self.release])
        return checked

    def run_command(self, command, *, timeout=900):
        # Build/start output is not evidence; it can contain dependency output.
        subprocess.run(command, env=self.environment, check=True, timeout=timeout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def runtime(self):
        return json.loads(subprocess.check_output([
            "docker", "exec", self.container("runtime-adapter"), "python3", "-c",
            "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8400/internal/runtime/operations', timeout=5).read().decode())",
        ], env=self.environment, text=True, timeout=10))

    def drain(self):
        set_state(self.gate, "closed", timeout=30)
        deadline = time.monotonic() + 930
        while time.monotonic() < deadline:
            value = self.runtime()
            active = value.get("sessions", {}).get("active_prompts")
            if type(active) is not int or active < 0:
                raise AssertionError("invalid drain accounting")
            if active == 0:
                self.result["steps"].append({"drained": self.release, "active_prompts": 0})
                return
            time.sleep(1)
        raise TimeoutError("bounded drain expired; no force-kill or switch authorized")

    def switch(self, target):
        self.check()
        self.drain()
        previous_release = self.release
        before = self.identities()
        self.run_command(self.compose(target, "up", "-d", "--no-deps", "--no-build", "--wait",
                                      "--wait-timeout", "120", "runtime-adapter"), timeout=150)
        self.release = target
        checked = self.check()
        # Seal the previous namespace after its process shutdown, so legitimate
        # shutdown writes are not misclassified as writes by the other release.
        self.result.setdefault("namespace_checkpoints", {})[previous_release] = self.namespace_digest(previous_release)
        after = self.identities()
        for service in live_stack.SERVICES - {"runtime-adapter"}:
            if before[service] != after[service]:
                raise AssertionError("non-runtime service restarted during switch")
        if self.runtime()["runtime"]["release_id"] != target:
            raise AssertionError("installed target identity mismatch")
        self.result["steps"].append({"switched": target, "images": checked["images"],
                                     "build_revision": checked["build_revision"],
                                     "non_runtime_containers_unchanged": True})
        emit("switched", release=target, scope=self.scope)
        set_state(self.gate, "open")

    def namespace_digest(self, release):
        if release not in {OLD, NEW}:
            raise ValueError("unknown release namespace")
        code = (
            "import hashlib,json,pathlib,sys; root=pathlib.Path('/var/lib/byq/dsh-sessions')/sys.argv[1]; "
            "files=sorted(p for p in root.rglob('*') if p.is_file()); "
            "values=[(str(p.relative_to(root)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in files]; "
            "print(json.dumps({'files':len(files),'digest':hashlib.sha256(json.dumps(values).encode()).hexdigest()}))"
        )
        value = json.loads(subprocess.check_output(["docker", "exec", self.container("runtime-adapter"),
            "python3", "-c", code, release], env=self.environment, text=True, timeout=30))
        if value["files"] == 0:
            raise AssertionError("release namespace contains no actual runtime files")
        return value

    def identities(self):
        values = live_stack.docker_json("inspect", *[self.container(name) for name in sorted(live_stack.SERVICES)])
        return {value["Config"]["Labels"]["com.docker.compose.service"]:
                {"id": value["Id"], "started_at": value["State"]["StartedAt"]} for value in values}

    def wait_answer(self, client, session, previous, timeout=900):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            replay = client.call("GET", f"/v1/agent/sessions/{session}")
            answers = assistant_messages(replay)
            if len(answers) > previous:
                return len(answers)
            time.sleep(1)
        raise TimeoutError("bounded synthetic turn did not produce a public answer")

    def browser_window(self, stage, seconds, session):
        emit(stage, seconds=seconds, session=session, scope=self.scope)
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            time.sleep(max(0, min(1, until - time.monotonic())))

    def followup(self, client, session):
        self.check()
        before = counts(client)
        previous = len(assistant_messages(client.call("GET", f"/v1/agent/sessions/{session}")))
        # Reopened IDLE conversations accept a normal turn, not resume (which
        # is reserved for READY/interrupted/failed sessions). After replacement
        # the same Product turn endpoint rehydrates a missing Runtime session.
        client.call("POST", f"/v1/agent/sessions/{session}/turns", {"content": PROMPTS["G5"]})
        self.wait_answer(client, session, previous)
        if counts(client) != before:
            raise AssertionError("G5 changed domain object counts")
        self.result["steps"].append({"followup": self.release, "public_session_id": session,
                                     "domain_counts_unchanged": True})

    def sql(self, database, query):
        return subprocess.check_output(["docker", "exec", self.container("postgres"),
            "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "byq_app", "-d", database, "-Atc", query],
            env=self.environment, text=True, timeout=30).strip()

    def database_counts(self, database):
        tables = self.sql(database, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").splitlines()
        if not tables or any(re.fullmatch(r"[a-z][a-z0-9_]*", name) is None for name in tables):
            raise AssertionError("unexpected synthetic table inventory")
        return {name: int(self.sql(database, f'SELECT count(*) FROM public."{name}"')) for name in tables}

    def critical_rows(self, database):
        # Compare values/IDs/links as well as counts, without exporting row text.
        tables = ("product_conversations", "product_conversation_messages", "agent_approvals",
                  "product_feedback", "product_feedback_revisions", "backtest_jobs", "artifacts", "research_tasks")
        return {name: self.sql(database, f'''SELECT md5(coalesce(string_agg(row_to_json(t)::text,
            E'\\n' ORDER BY row_to_json(t)::text), '')) FROM public."{name}" t''') for name in tables}

    def seed_domain_fixture(self):
        self.check()
        result = subprocess.run(["docker", "exec", "-i", self.container("backend"), "python", "-"],
            input=(live_stack.ROOT / "tests/dsh_upgrade/seed_live_fixture.py").read_text(),
            text=True, capture_output=True, env=self.environment, check=True, timeout=120)
        seeded = json.loads(result.stdout.strip().splitlines()[-1])
        if seeded.get("synthetic") is not True or seeded.get("status") != "completed":
            raise AssertionError("synthetic domain fixture was not completed")
        self.result["domain_fixture"] = seeded

    def backup_restore(self):
        self.check()
        self.drain()
        before = self.database_counts("byq_domain")
        original_rows = self.critical_rows("byq_domain")
        backup = self.directory / "backups" / "synthetic-domain.dump"
        with backup.open("xb") as output:
            os.chmod(backup, 0o600)
            subprocess.run(["docker", "exec", self.container("postgres"), "pg_dump", "-U", "byq_app",
                            "-d", "byq_domain", "-Fc"], stdout=output, env=self.environment, check=True, timeout=120)
        self.sql("postgres", "CREATE DATABASE byq_u6_restore OWNER byq_app")
        with backup.open("rb") as source:
            subprocess.run(["docker", "exec", "-i", self.container("postgres"), "pg_restore", "-U", "byq_app",
                            "-d", "byq_u6_restore", "--exit-on-error", "--no-owner"], stdin=source,
                           env=self.environment, check=True, timeout=120)
        restored = self.database_counts("byq_u6_restore")
        restored_rows = self.critical_rows("byq_u6_restore")
        if (before != restored or original_rows != restored_rows
                or self.sql("byq_u6_restore", "SELECT count(*) FROM pg_constraint WHERE NOT convalidated") != "0"):
            raise AssertionError("logical restore did not preserve table counts and validated relationships")
        with backup.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        self.result["backup_restore"] = {"sha256": digest,
            "bytes": backup.stat().st_size, "mode": oct(backup.stat().st_mode & 0o777),
            "table_counts": restored, "constraints_validated": True, "production_database_touched": False}
        self.result["backup_restore"]["critical_row_fingerprints"] = restored_rows

    def journey(self, browser_window):
        self.prepare()
        emit("building", scope=self.scope, output=str(self.directory))
        if self.ci_scope:
            self.reuse_ci_images()
            self.run_command(self.compose(OLD, "build", "fake-hub"))
        else:
            self.run_command(self.compose(NEW, "build", "runtime-adapter"))
        self.run_command(self.compose(OLD, "up", "-d", "--no-build" if self.ci_scope else "--build", "--wait", "--wait-timeout", "240",
                                      *sorted(live_stack.SERVICES)))
        self.result["initial"] = self.check()
        self.seed_domain_fixture()
        set_state(self.gate, "open")
        client = Client("http://127.0.0.1:18210", "u5-admin", "U5AdminTestOnly123")
        initial_counts = counts(client)
        if initial_counts["backtests"] != 1:
            raise AssertionError("completed fixture is not visible through Product API")
        self.result["domain_counts_before"] = initial_counts
        session = str(client.call("POST", "/v1/agent/sessions", {})["session_id"])
        self.result["public_session_id"] = session
        client.call("POST", f"/v1/agent/sessions/{session}/turns", {"content": PROMPTS["G6"]})
        self.wait_answer(client, session, 0)
        approvals = client.call("GET", "/api/product/approvals?status=pending&limit=50&offset=0")["approvals"]
        pending = [item for item in approvals if item.get("conversation_id") == session]
        if len(pending) != 1:
            raise AssertionError("G6 must create exactly one pending approval")
        approval = pending[0]["approval_id"]
        self.result["approval_id"] = approval
        self.drain()
        self.browser_window("maintenance-browser-window", browser_window, session)
        self.backup_restore()
        self.switch(NEW)
        # Decide while closed: preserve durable queued state without submitting.
        self.drain()
        client.call("POST", f"/api/product/approvals/{approval}/decision",
                    {"decision": "approved", "rationale": "U6 synthetic rollback qualification."})
        records = client.call("GET", "/api/product/approvals?limit=50&offset=0")["approvals"]
        record = next(item for item in records if item["approval_id"] == approval)
        if record.get("continuation_status") != "queued":
            raise AssertionError("maintenance lost the durable queued continuation")
        set_state(self.gate, "open")
        self.check()
        previous = len(assistant_messages(client.call("GET", f"/v1/agent/sessions/{session}")))
        client.call("POST", f"/api/product/approvals/{approval}/continue")
        self.wait_answer(client, session, previous)
        # Duplicate retry must not create a second action or model turn.
        client.call("POST", f"/api/product/approvals/{approval}/continue")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            hub = fake_hub_evidence(self.container("fake-hub"))
            if hub["received"] == 1:
                break
            time.sleep(1)
        if hub["received"] != 1 or counts(client)["feedback"] != 1:
            raise AssertionError("expected exactly one synthetic feedback and fake intake")
        self.result["continuation"] = {"queued_across_maintenance": True, "fake_hub": hub, "feedback_count": 1}
        self.followup(client, session)
        self.drain()
        self.browser_window("candidate-browser-window", browser_window, session)
        if self.namespace_digest(OLD) != self.result["namespace_checkpoints"][OLD]:
            raise AssertionError("candidate modified the old release namespace")
        self.switch(OLD)
        self.followup(client, session)
        self.drain()
        if self.namespace_digest(NEW) != self.result["namespace_checkpoints"][NEW]:
            raise AssertionError("rollback modified the candidate release namespace")
        self.result["namespace_cross_writes"] = 0
        final_counts = counts(client)
        for key in ("backtests", "artifacts", "ml_training", "ml_predictions"):
            if final_counts[key] != initial_counts[key]:
                raise AssertionError("runtime switch changed existing domain object counts")
        self.result["domain_counts_after"] = final_counts
        if counts(client)["feedback"] != 1 or fake_hub_evidence(self.container("fake-hub"))["received"] != 1:
            raise AssertionError("rollback replayed a mutation")
        self.result["result"] = "PASS"

    def reuse_ci_images(self):
        # Alias the exact tested artifacts into the closed fixture; never tag a
        # production name or resolve a registry's floating candidate remotely.
        receipts = {}
        retained = load_receipt(self.ci_scope)
        self.result["retained_ci_artifact"] = retained
        for release in (OLD, NEW):
            value = json.loads(self.files[release].read_text())
            names = ["runtime-adapter"] if release == NEW else ["runtime-adapter", "backend", "mcp", "gateway", "frontend", "feedback-hub-relay"]
            for name in names:
                source_name = "runtime-candidate" if release == NEW else name
                tested = retained["images"][source_name]
                source = tested["retained_tag"]
                identity = live_stack.docker_json("image", "inspect", source)[0]["Id"]
                if identity != tested["image_id"]:
                    raise AssertionError("invalid tested image identity")
                target = value["services"][name]["image"]
                self.run_command(["docker", "image", "tag", identity, target], timeout=30)
                if live_stack.docker_json("image", "inspect", target)[0]["Id"] != identity:
                    raise AssertionError("image alias differs from tested artifact")
                receipts[f"{release}/{name}"] = {"source": source, "image_id": identity}
        self.result["reused_ci_images"] = receipts

    def qualify_remaining_scenarios(self):
        """Re-run fixed G1-G4 on the certified-image candidate, after core rollback.

        These authorized synthetic mutations are separate from the core journey's
        unchanged-domain assertions. Probe assertions remain authoritative; there
        are no scenario retries or relaxed success conditions here.
        """
        self.switch(NEW)
        self.result["additional_model_scenarios"] = []
        for scenario in ("G1", "G2", "G3", "G4"):
            self.check()
            emit("candidate-model-scenario", scenario=scenario, scope=self.scope)
            command = [sys.executable, "-m", "tests.dsh_upgrade.live_model_probe", scenario,
                       "--release", NEW, "--stack-file", str(self.files[NEW])]
            if scenario == "G3":
                command.append("--approve")
            if scenario == "G2":
                command.extend(["--backtest-id", self.result["domain_fixture"]["backtest_job_id"]])
            probe_environment = live_stack.compose_environment()
            probe_environment.pop("DEEPSEEK_API_KEY", None)
            completed = subprocess.run(command, env=probe_environment,
                capture_output=True, text=True, timeout=1020, cwd=live_stack.ROOT)
            if completed.returncode:
                self.result["additional_model_scenarios"].append({"scenario": scenario,
                    "result": "FAIL", "exit_code": completed.returncode})
                raise AssertionError(f"bounded candidate {scenario} qualification failed")
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            if result.get("result") != "PASS" or result.get("scenario") != scenario:
                raise AssertionError("model probe did not return matching PASS evidence")
            self.result["additional_model_scenarios"].append(result)
            emit("candidate-model-scenario-passed", scenario=scenario, scope=self.scope)
        self.drain()
        self.switch(OLD)
        self.drain()

    def g2_only(self):
        if not self.ci_scope:
            raise ValueError("targeted G2 requires retained tested artifacts")
        self.result["mode"] = "targeted-g2-object-context"
        self.prepare()
        self.release = NEW
        emit("building", scope=self.scope, output=str(self.directory))
        self.reuse_ci_images()
        self.run_command(self.compose(NEW, "build", "fake-hub"))
        self.run_command(self.compose(NEW, "up", "-d", "--no-build", "--wait", "--wait-timeout", "240",
                                      *sorted(live_stack.SERVICES)))
        self.result["initial"] = self.check()
        self.seed_domain_fixture()
        set_state(self.gate, "open")
        emit("candidate-model-scenario", scenario="G2-with-object-context", scope=self.scope)
        environment = live_stack.compose_environment()
        environment.pop("DEEPSEEK_API_KEY", None)
        completed = subprocess.run([sys.executable, "-m", "tests.dsh_upgrade.live_model_probe", "G2",
            "--release", NEW, "--stack-file", str(self.files[NEW]), "--backtest-id",
            self.result["domain_fixture"]["backtest_job_id"]], env=environment, capture_output=True,
            text=True, timeout=1020, cwd=live_stack.ROOT)
        if completed.returncode:
            raise AssertionError("targeted G2 actual-summary qualification failed")
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.result["g2_context_requalification"] = result
        if result.get("result") != "PASS" or not result.get("successful_backtest_summary_reads"):
            raise AssertionError("targeted G2 lacks actual summary evidence")
        client = Client("http://127.0.0.1:18210", "u5-admin", "U5AdminTestOnly123")
        answers = assistant_messages(client.call("GET", f"/v1/agent/sessions/{result['session_id']}"))
        answer = "\n\n".join(answers)
        if not answer or len(answer) > 100000:
            raise AssertionError("invalid bounded synthetic public answer")
        path = self.directory / "backups/g2-public-answer.txt"
        with path.open("x") as output:
            os.chmod(path, 0o600)
            output.write(answer)
        self.result["public_answer_sha256"] = hashlib.sha256(answer.encode()).hexdigest()
        self.drain()
        self.result["result"] = "PASS"

    def cleanup(self):
        path = self.files[self.release]
        if path.exists():
            live_stack.preflight(path, require_healthy=False)
            self.run_command(self.compose(self.release, "down", "--volumes"), timeout=120)
        for kind in ("container", "network", "volume"):
            remaining = subprocess.check_output(["docker", kind, "ls", *( ["-a"] if kind == "container" else []), "-q", "--filter",
                f"label={live_stack.LABEL}={self.scope}"], env=self.environment, text=True)
            if remaining.strip():
                raise AssertionError("synthetic resources retained after cleanup")
        self.result["cleanup"] = "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key-env-file", type=Path, required=True)
    parser.add_argument("--browser-window-seconds", type=int, choices=range(301), default=180)
    parser.add_argument("--ci-scope", help="reuse exact images from a successful isolated U6 CI run")
    parser.add_argument("--qualify-g1-g4", action="store_true",
                        help="also re-run fixed candidate G1-G4 after the core rollback journey")
    parser.add_argument("--g2-only", action="store_true", help="one targeted G2 with verified synthetic object context")
    args = parser.parse_args()
    if args.g2_only and args.qualify_g1_g4:
        parser.error("targeted G2 cannot also run the full scenario set")
    environment = live_stack.compose_environment()
    environment["DEEPSEEK_API_KEY"] = live_stack.model_key_from_env_file(args.model_key_env_file)
    available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))
    if available < 3145728:
        raise ValueError("insufficient memory for isolated rehearsal")
    with open("/tmp/byq-ci-heavy.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rehearsal = Rehearsal(Path(tempfile.mkdtemp(prefix="byq-u6-")), environment, args.ci_scope)
        try:
            if args.g2_only:
                rehearsal.g2_only()
            else:
                rehearsal.journey(args.browser_window_seconds)
            if args.qualify_g1_g4:
                rehearsal.qualify_remaining_scenarios()
        except BaseException as error:
            rehearsal.result.update(result="FAIL", failure_type=type(error).__name__)
            raise
        finally:
            try:
                rehearsal.cleanup()
            except BaseException:
                rehearsal.result.update(result="FAIL", cleanup="FAIL")
                raise
            finally:
                with (rehearsal.directory / "result.json").open("x") as output:
                    json.dump(rehearsal.result, output, indent=2, sort_keys=True)
                emit("finished", result=rehearsal.result["result"], output=str(rehearsal.directory / "result.json"))


if __name__ == "__main__":
    main()
