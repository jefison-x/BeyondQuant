"""Closed, read-only Frontend/Gateway diagnostics for the dedicated F6 CI stack.

These observations neither establish business effects nor repair/replay actions.
No response body, request credential, environment or raw log is published.
"""
from __future__ import annotations
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STAGES = {"before_restart", "after_restart", "before_browser", "after_browser"}
INSPECT = '{{json .Id}}\n{{json .Config.Labels}}\n{{json .State.StartedAt}}\n{{json .NetworkSettings}}'
MAX_BYTES = 262144

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def anonymous_me(port: str) -> int | str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/auth/me", timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as error:
        try:
            return error.code
        finally:
            error.close()
    except (urllib.error.URLError, OSError, TimeoutError):
        return "unavailable"


def error_categories(payload: bytes) -> dict:
    if len(payload) > MAX_BYTES:
        return {"status": "unqualified"}
    text = payload.decode("utf-8", errors="replace")
    ips = set()
    for value in re.findall(r'upstream: "http://([0-9.]+):8100', text):
        try:
            ips.add(str(ipaddress.IPv4Address(value)))
        except ValueError:
            pass
    return {"status": "observed_tail_only", "connect_refused": "connect() failed (111: Connection refused)" in text,
            "no_route": "No route to host" in text, "timed_out": "upstream timed out" in text,
            "upstream_ips": sorted(ips)[:8]}


def collect(project: str, stage: str, runner=subprocess.run, requester=anonymous_me) -> dict:
    report = {"schema_version": "byq.f6.proxy-diagnostic.v1", "stage": stage if stage in STAGES else "unknown",
              "status": "unqualified", "business_outcomes": "unknown", "resources": {}}
    if (stage not in STAGES or re.fullmatch(r"byq-ci-stack-[A-Za-z0-9][A-Za-z0-9_-]{0,80}", project) is None
            or os.environ.get("COMPOSE_PROJECT_NAME") != project):
        report["status"] = "scope_rejected"
        return report
    def run(args):
        response = runner(args, capture_output=True, timeout=5, check=False)
        if response.returncode or len(response.stdout) > MAX_BYTES or len(response.stderr) > MAX_BYTES:
            raise ValueError("unqualified command")
        return response
    try:
        # Qualify BOTH exact resources before any HTTP request or log read.
        for service, container_port in (("gateway", "8100/tcp"), ("frontend", "80/tcp")):
            response = run(["docker", "compose", "-p", project, "ps", "-q", service])
            cid = response.stdout.decode("ascii").strip()
            if re.fullmatch(r"[0-9a-f]{64}", cid) is None:
                raise ValueError("unqualified identity")
            response = run(["docker", "inspect", "--format", INSPECT, cid])
            lines = response.stdout.splitlines()
            if len(lines) != 4:
                raise ValueError("unqualified metadata")
            identity, labels, started, network = [json.loads(line) for line in lines]
            if (identity != cid or labels.get("com.docker.compose.project") != project
                    or labels.get("com.docker.compose.service") != service
                    or labels.get("com.docker.compose.project.working_dir") != str(ROOT)
                    or not isinstance(started, str) or re.fullmatch(r"[0-9TZ:.+-]{20,40}", started) is None):
                raise ValueError("unqualified ownership")
            bindings = network["Ports"][container_port]
            if len(bindings) != 1 or bindings[0]["HostIp"] != "127.0.0.1":
                raise ValueError("nonloopback binding")
            port = bindings[0]["HostPort"]
            if not isinstance(port, str) or not port.isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError("unqualified port")
            ips = sorted({str(ipaddress.ip_address(row["IPAddress"])) for row in network["Networks"].values()})
            if not 1 <= len(ips) <= 8:
                raise ValueError("unqualified addresses")
            report["resources"][service] = {"id": cid, "started_at": started, "ips": ips, "published_port": int(port)}
        for service in ("gateway", "frontend"):
            status = requester(str(report["resources"][service]["published_port"]))
            if status != "unavailable" and (type(status) is not int or not 100 <= status <= 599):
                raise ValueError("unqualified HTTP status")
            report["resources"][service]["anonymous_me_status"] = status
        if report["resources"]["frontend"]["anonymous_me_status"] != 401:
            response = run(["docker", "logs", "--since", report["resources"]["gateway"]["started_at"],
                            "--tail", "80", report["resources"]["frontend"]["id"]])
            report["proxy_errors"] = error_categories(response.stdout + response.stderr)
            report["proxy_error_window"] = "since_current_gateway_start_tail80"
        report["status"] = "observed_only_not_acceptance"
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OSError, subprocess.SubprocessError):
        report["status"] = "unqualified"
        # Preserve only already qualified metadata/status; no parser input escapes.
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--stage", required=True, choices=sorted(STAGES))
    args = parser.parse_args()
    print("F6 proxy diagnostics: " + json.dumps(collect(args.project, args.stage), sort_keys=True))
    return 0  # Diagnostic failure never changes or substitutes F6/browser acceptance.

if __name__ == "__main__":
    raise SystemExit(main())
