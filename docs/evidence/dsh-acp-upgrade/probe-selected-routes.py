"""Offline pinned-DSH config probe; no ACP process or provider request.

Usage: python3 probe-selected-routes.py OFFICIAL_SOURCE DEDICATED_PATCH
Requires PyYAML on the host running this evidence probe, not in Runtime Adapter.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def main() -> None:
    source, profile = map(Path, sys.argv[1:])
    assert source.joinpath("apps/cli/lib/bin.js").is_file()
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() \
        == "639ed015397290b3745d163aafe02ffee4aa3f84"
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=source)
    rows = yaml.safe_load(profile.read_text(encoding="utf-8"))
    routes = next(row["config"]["providers"] for row in rows if row.get("id") == "llm-pi-ai")
    assert len(routes) == 6

    with tempfile.TemporaryDirectory(prefix="byq-acp-route-probe-") as temporary:
        for selected in ("deepseek-official", *routes):
            if selected == "deepseek-official":
                overlay = [
                    {"id": "llm-deepseek", "config": {
                        "baseURL": "http://127.0.0.1:43210/anthropic"}},
                    {"id": "llm-pi-ai", "disabled": True},
                ]
            else:
                route = dict(routes[selected])
                # Anthropic SDK appends /v1/messages; OpenAI SDK appends its
                # endpoint beneath the configured /v1 root. This probe still
                # checks composition only, not actual HTTP dispatch.
                route["baseURL"] = ("http://127.0.0.1:43210" if
                                    route["api"] == "anthropic-messages" else
                                    "http://127.0.0.1:43210/v1")
                overlay = [
                    {"id": "llm-deepseek", "disabled": True},
                    {"id": "llm-pi-ai", "config": {"providers": {selected: route}}},
                ]
            patch = Path(temporary) / f"{selected}.yml"
            patch.write_text(yaml.safe_dump(overlay, allow_unicode=True, sort_keys=False),
                             encoding="utf-8")
            environment = {
                "PATH": os.environ["PATH"], "HOME": temporary,
                "DSH_HOME": str(Path(temporary) / selected),
            }
            result = subprocess.run(
                ["node", "apps/cli/lib/bin.js", "--profile", "acp", "--patch",
                 str(profile), "--patch", str(patch), "--dump-config"],
                cwd=source, env=environment, capture_output=True, text=True, check=True,
            )
            loaded = {row["id"]: row for row in yaml.load(result.stdout, Loader=yaml.BaseLoader)}
            deepseek, pi_ai = loaded["llm-deepseek"], loaded["llm-pi-ai"]
            for disabled_id in ("llm-deepseek-account", "compaction-basic", "image-offload"):
                assert loaded[disabled_id].get("disabled") == "true"
            if selected == "deepseek-official":
                assert pi_ai.get("disabled") == "true"
                assert deepseek["config"]["baseURL"] == "http://127.0.0.1:43210/anthropic"
            else:
                assert deepseek.get("disabled") == "true"
                assert list(pi_ai["config"]["providers"]) == [selected]
                assert (pi_ai["config"]["providers"][selected]["baseURL"]
                        == route["baseURL"])
            print(f"{selected}: PASS (offline composition only)")


if __name__ == "__main__":
    main()
