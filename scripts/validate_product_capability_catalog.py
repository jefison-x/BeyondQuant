#!/usr/bin/env python3
"""Validate the versioned BYQ user-facing capability catalogue."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/contracts/product-capability-catalog.v1.json"
ROUTER = ROOT / "apps/frontend/src/router/index.ts"
MCP = ROOT / "services/mcp/src/server.ts"
ALLOWED_LEVELS = {"EXPLAIN", "NAVIGATE", "READ", "PROPOSE", "EXECUTE", "UNAVAILABLE"}
ALLOWED_AUDIENCES = {"USER", "ADMIN"}
REQUIRED_ROUTES = {
    "/agent", "/dashboard", "/stock-pool", "/strategy", "/model-research", "/backtest",
    "/paper-trading", "/user/profile", "/user/appearance", "/user/assets", "/user/models",
    "/user/agent-policy", "/user/research", "/settings/system/overview",
    "/settings/system/data", "/settings/system/plugins",
}


def validate() -> None:
    document = json.loads(CATALOG.read_text(encoding="utf-8"))
    if document.get("schema_version") != "product-capability-catalog.v1":
        raise ValueError("unexpected product capability catalogue schema")
    if set(document.get("support_levels", [])) != ALLOWED_LEVELS:
        raise ValueError("catalogue support level vocabulary drifted")
    capabilities = document.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("catalogue must contain capabilities")

    router = ROUTER.read_text(encoding="utf-8")
    mcp = MCP.read_text(encoding="utf-8")
    identities: set[str] = set()
    routes: set[str] = set()
    for item in capabilities:
        if not isinstance(item, dict):
            raise ValueError("capability must be an object")
        capability_id = item.get("capability_id")
        route = item.get("route_id")
        if not isinstance(capability_id, str) or not capability_id:
            raise ValueError("capability_id is required")
        if capability_id in identities:
            raise ValueError(f"duplicate capability_id: {capability_id}")
        identities.add(capability_id)
        if not isinstance(route, str) or not route.startswith("/") or "?" in route or "#" in route:
            raise ValueError(f"invalid fixed route for {capability_id}")
        if route in routes:
            raise ValueError(f"duplicate route_id: {route}")
        routes.add(route)
        segments = [segment for segment in route.split("/") if segment]
        if segments[:2] == ["settings", "system"]:
            if 'path: "settings/system"' not in router:
                raise ValueError(f"route {route} is not represented in the Product router")
            segments = segments[2:]
        for segment in segments:
            if f'path: "{segment}"' not in router:
                raise ValueError(f"route {route} is not represented in the Product router")
        if item.get("audience") not in ALLOWED_AUDIENCES:
            raise ValueError(f"invalid audience for {capability_id}")
        support = item.get("support")
        if not isinstance(support, list) or not support or not set(support) <= ALLOWED_LEVELS:
            raise ValueError(f"invalid support levels for {capability_id}")
        if "UNAVAILABLE" in support and set(support) - {"EXPLAIN", "NAVIGATE", "UNAVAILABLE"}:
            raise ValueError(f"unavailable capability overclaims Agent access: {capability_id}")
        for field in ("name", "purpose"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{field} is required for {capability_id}")
        for field in ("prerequisites", "agent_tools", "limitations"):
            if not isinstance(item.get(field), list):
                raise ValueError(f"{field} must be a list for {capability_id}")
        for tool in item["agent_tools"]:
            if not isinstance(tool, str) or f'"{tool}"' not in mcp:
                raise ValueError(f"unknown MCP tool {tool!r} for {capability_id}")

    missing = REQUIRED_ROUTES - routes
    if missing:
        raise ValueError(f"catalogue misses stable Product routes: {sorted(missing)}")


if __name__ == "__main__":
    validate()
    print("Product capability catalogue PASS")
