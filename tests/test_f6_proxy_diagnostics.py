"""Execute closed proxy collector with synthetic Docker/HTTP, never real calls."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("f6_proxy_diagnostics", ROOT / "scripts/ci/f6-proxy-diagnostics.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
PROJECT = "byq-ci-stack-contract"
IDS = {"gateway": "a" * 64, "frontend": "b" * 64}

class ProxyDiagnostics(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"COMPOSE_PROJECT_NAME": PROJECT})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.calls = []
        self.http_calls = []
        self.bad = None
        self.http = [401, 401]
        self.logs = b''

    def runner(self, args, **kw):
        self.calls.append(args)
        self.assertTrue(kw["capture_output"])
        self.assertEqual(kw["timeout"], 5)
        self.assertFalse(kw["check"])
        out = b''
        if args[1:3] == ["compose", "-p"]:
            out = (IDS[args[-1]] + "\n").encode()
        elif args[1] == "inspect":
            service = next(s for s, cid in IDS.items() if cid == args[-1])
            labels = {"com.docker.compose.project": PROJECT, "com.docker.compose.service": service,
                      "com.docker.compose.project.working_dir": str(ROOT)}
            binding = {"HostIp": "127.0.0.1", "HostPort": "32100" if service == "gateway" else "32101"}
            if self.bad == "scope" and service == "frontend": labels["com.docker.compose.project"] = "protected-other-project"
            if self.bad == "binding" and service == "frontend": binding["HostIp"] = "0.0.0.0"
            network = {"Ports": {"8100/tcp" if service == "gateway" else "80/tcp": [binding]},
                       "Networks": {"product": {"IPAddress": "172.24.0.2" if service == "gateway" else "172.24.0.3"}}}
            out = ("\n".join(json.dumps(v) for v in [args[-1], labels, "2026-10-03T01:00:00.123Z", network]) + "\n").encode()
        elif args[1] == "logs":
            out = self.logs
        else: self.fail("non-read-only command")
        return subprocess.CompletedProcess(args, 0, out, b'')

    def requester(self, port):
        self.http_calls.append(port)
        return self.http[len(self.http_calls)-1]

    def collect(self):
        return module.collect(PROJECT, "before_browser", self.runner, self.requester)

    def test_healthy_paths_observed_with_fresh_ports_and_no_logs(self):
        result = self.collect()
        self.assertEqual(result["status"], "observed_only_not_acceptance")
        self.assertEqual(self.http_calls, ["32100", "32101"])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(result["resources"]["frontend"]["anonymous_me_status"], 401)
        self.assertNotIn("proxy_errors", result)

    def test_proxy_failure_keeps_direct_fact_and_closed_upstream_categories(self):
        self.http = [401, 502]
        secret = 'cookie-body-env-secret-sentinel'
        self.logs = (secret + ' connect() failed (111: Connection refused) upstream: "http://172.24.0.9:8100/api/auth/me"').encode()
        result = self.collect()
        self.assertEqual(result["resources"]["gateway"]["anonymous_me_status"], 401)
        self.assertTrue(result["proxy_errors"]["connect_refused"])
        self.assertEqual(result["proxy_errors"]["upstream_ips"], ["172.24.0.9"])
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(self.calls[-1][1:6], ["logs", "--since", "2026-10-03T01:00:00.123Z", "--tail", "80"])
        self.assertEqual(result["proxy_error_window"], "since_current_gateway_start_tail80")

    def test_invalid_stage_project_and_environment_reject_without_calls(self):
        for project,stage in [("production", "before_browser"), (PROJECT, "raw-input-secret")]:
            result=module.collect(project,stage,self.runner,self.requester)
            self.assertEqual(result["status"], "scope_rejected")
            self.assertNotIn("raw-input-secret", json.dumps(result))
        with patch.dict(os.environ, {"COMPOSE_PROJECT_NAME":"other"}):
            self.assertEqual(self.collect()["status"], "scope_rejected")
        self.assertEqual(self.calls, [])

    def test_both_resources_qualified_before_http_or_logs(self):
        for bad in ["scope", "binding"]:
            with self.subTest(bad=bad):
                self.bad = bad
                result = self.collect()
                self.assertEqual(result["status"], "unqualified")
                self.assertEqual(self.http_calls, [])
                self.assertFalse(any(args[1]=="logs" for args in self.calls))

    def test_docker_timeout_is_unknown_and_never_retried(self):
        calls=[]
        def timeout(args, **kw):
            calls.append(args)
            raise subprocess.TimeoutExpired(args,5,output=b'private-output')
        result=module.collect(PROJECT,"after_restart",timeout,self.requester)
        self.assertEqual(len(calls),1)
        self.assertEqual(result["status"],"unqualified")
        self.assertNotIn("private-output",json.dumps(result))
        self.assertEqual(self.http_calls, [])

    def test_redirect_success_and_unavailable_are_observations_not_pass(self):
        for status in [200,302,"unavailable"]:
            self.http_calls=[]; self.http=[401,status]
            result=self.collect()
            self.assertEqual(result["status"],"observed_only_not_acceptance")
            self.assertEqual(result["resources"]["frontend"]["anonymous_me_status"],status)
            self.assertEqual(result["business_outcomes"],"unknown")

    def test_oversized_log_is_unqualified_without_raw_bytes(self):
        self.assertEqual(module.error_categories(b'x'*(module.MAX_BYTES+1)), {"status":"unqualified"})
        categories=module.error_categories(b'No route to host; upstream timed out; upstream: "http://999.2.3.4:8100"')
        self.assertTrue(categories["no_route"])
        self.assertTrue(categories["timed_out"])
        self.assertEqual(categories["upstream_ips"],[])

    def test_native_http_disables_environment_proxy_and_redirects_without_cookie(self):
        seen=[]
        class Response:
            status=401
            def __enter__(self):return self
            def __exit__(self,*args):return False
        def opener(*handlers):
            self.assertEqual(handlers[0].proxies,{})
            self.assertIsInstance(handlers[1],module.NoRedirect)
            return types.SimpleNamespace(open=lambda url,timeout: (seen.append((url,timeout)) or Response()))
        with patch.object(module.urllib.request,"build_opener",opener):
            self.assertEqual(module.anonymous_me("32100"),401)
        self.assertEqual(seen,[("http://127.0.0.1:32100/api/auth/me",2)])
        self.assertIsNone(module.NoRedirect().redirect_request(None,None,None,None,None,None))

    def test_four_sampling_points_and_driver_collector_failure_do_not_replay(self):
        source=ROOT/"scripts/evidence/f6-chain-verification.py"
        tree=ast.parse(source.read_text())
        helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_proxy_diagnostic")
        code=ast.Module(body=[helper],type_ignores=[])
        calls=[]
        def run(args,**kw):
            calls.append((args,kw));raise subprocess.TimeoutExpired(args,35)
        ns={"Path":Path,"__file__":str(source),"subprocess":types.SimpleNamespace(run=run,SubprocessError=subprocess.SubprocessError),
            "sys":types.SimpleNamespace(executable="python3"),"os":os}
        exec(compile(code,str(source),"exec"),ns)
        with contextlib.redirect_stdout(io.StringIO()) as output:ns["_proxy_diagnostic"]("before_restart")
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1]["timeout"],35)
        self.assertIn("cause unknown",output.getvalue())
        sampling=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                  and n.func.id=="_proxy_diagnostic"]
        self.assertEqual(sampling,["before_restart","after_restart"])
        shell=(ROOT/"scripts/ci/local-ci.sh").read_text()
        self.assertLess(shell.index("--stage before_browser"),shell.index("npx playwright test --config playwright.f6.config.ts"))
        self.assertLess(shell.index("--stage after_browser"),shell.index("  if restore_f6_runtime; then"))

if __name__=="__main__":unittest.main()
