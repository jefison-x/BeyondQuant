"""Last-layer, one-route DSH configuration for a closed judgment invocation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .research_judgment_acp_provider_routes import selected_route

_LOOPBACK = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})(/[^?#]*)?\Z")
_API = {"chat": "openai-completions", "responses": "openai-responses",
        "messages": "anthropic-messages"}


def private_provider_overlay(*, route_name: str, model: str,
                             proxy_base_url: str) -> list[dict]:
    """Return only the selected route with its fixed local proxy endpoint."""
    route = selected_route(route_name)
    matched = _LOOPBACK.fullmatch(proxy_base_url) if isinstance(proxy_base_url, str) else None
    if (matched is None or int(matched[1]) > 65535
            or (matched[2] or "") != route.local_base_path
            or not isinstance(model, str) or not model
            or len(model) > 128 or any(ord(char) < 32 for char in model)):
        raise ValueError("exact selected ACP proxy route and model are required")
    no_retry = {"mode": "normal", "maxRetries": 0}
    if route.name == "deepseek-official":
        return [{"id": "llm-deepseek", "config": {
            "apiKeyEnv": "DEEPSEEK_API_KEY", "baseURL": proxy_base_url,
            "retryPolicy": no_retry}},
            {"id": "llm-pi-ai", "disabled": True}]
    return [{"id": "llm-deepseek", "disabled": True},
            {"id": "llm-pi-ai", "config": {"providers": {route.name: {
                "api": _API[route.protocol], "apiKeyEnv": "OPENCODE_API_KEY",
                "baseURL": proxy_base_url, "retryPolicy": no_retry,
                "models": [{"id": model}],
            }}}}]


def write_private_provider_overlay(directory: Path, *, route_name: str,
                                   model: str, proxy_base_url: str) -> Path:
    """Write the nonsecret private overlay once; never replace a running one."""
    overlay = private_provider_overlay(route_name=route_name, model=model,
                                       proxy_base_url=proxy_base_url)
    directory = Path(directory)
    info = os.stat(directory, follow_symlinks=False)
    if not directory.is_dir() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("private ACP overlay directory is required")
    path = directory / "selected-provider.patch.yml"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(overlay, sort_keys=True, separators=(",", ":")).encode())
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path
