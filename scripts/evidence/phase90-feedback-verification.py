#!/usr/bin/env python3
"""Verify Product feedback persistence, idempotency and two-user isolation."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = os.environ.get("BYQ_GOLDEN_ORIGIN", "http://127.0.0.1:18080").rstrip("/")


class Client:
    def __init__(self, username: str, password: str) -> None:
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.call("POST", "/api/product/auth/login", {"username": username, "password": password}, 200)

    def call(self, method: str, path: str, payload: object = None, expected: int = 200) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(ORIGIN + path, data=data, headers={"content-type": "application/json"} if data else {}, method=method)
        try:
            with self.opener.open(request, timeout=30) as response:
                status, body = response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            status, body = error.code, json.loads(error.read() or b"{}")
        if status != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {body}")
        return body


def feedback_content() -> dict[str, object]:
    return {
        "schema_version": "product-feedback.v1",
        "category": "performance", "component": "xiaoba", "severity": "normal",
        "title": "Phase90 restart persistence feedback",
        "description": "Verify durable feedback and strict workspace isolation.",
        "reproduction_steps": ["Open feedback workspace", "Save a private draft"],
        "expected_behavior": "The feedback remains owner scoped after restart.",
        "actual_behavior": "Acceptance test evidence.",
        "diagnostics": {"include_product_version": True},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    owner = Client(os.environ.get("BYQ_GOLDEN_OWNER_USERNAME", "ci-admin"), os.environ.get("BYQ_GOLDEN_OWNER_PASSWORD", "ci-bootstrap-test-only"))
    other = Client(os.environ.get("BYQ_PHASE90_OTHER_USERNAME", "phase74-user"), os.environ.get("BYQ_PHASE90_OTHER_PASSWORD", "phase74-user-test-only"))
    if args.verify:
        with open(args.manifest, encoding="utf-8") as handle:
            identity = json.load(handle)
        detail = owner.call("GET", f"/api/product/feedback/items/{identity['feedback_id']}")["feedback"]
        if detail["title"] != feedback_content()["title"] or detail["status"] != "submitted":
            raise AssertionError("feedback changed across Product service restart")
    else:
        payload = {**feedback_content(), "idempotency_key": "phase90-create-restart"}
        created = owner.call("POST", "/api/product/feedback/items", payload, 201)["feedback"]
        replay = owner.call("POST", "/api/product/feedback/items", payload, 201)["feedback"]
        if created["feedback_id"] != replay["feedback_id"]:
            raise AssertionError("create idempotency replay produced a second feedback item")
        preview = owner.call("POST", f"/api/product/feedback/items/{created['feedback_id']}/preview", {"expected_version": created["version"]})
        submitted = owner.call("POST", f"/api/product/feedback/items/{created['feedback_id']}/submit", {
            "expected_version": created["version"], "preview_hash": preview["preview_hash"],
            "disclosure_confirmed": True, "idempotency_key": "phase90-submit-restart",
        })["feedback"]
        identity = {"feedback_id": submitted["feedback_id"], "status": submitted["status"]}
        with open(args.manifest, "w", encoding="utf-8") as handle:
            json.dump(identity, handle, sort_keys=True)
        unsafe = {**feedback_content(), "title": "Phase90 security vulnerability report", "idempotency_key": "phase90-unsafe"}
        owner.call("POST", "/api/product/feedback/items", unsafe, 422)

    feedback_id = identity["feedback_id"]
    other.call("GET", f"/api/product/feedback/items/{feedback_id}", expected=404)
    encoded = urllib.parse.quote(str(feedback_content()["title"]))
    other_page = other.call("GET", f"/api/product/feedback/items?status=all&category=all&query={encoded}&limit=10&offset=0")
    if other_page["items"] or other_page["total"]:
        raise AssertionError("secondary user can enumerate owner feedback")
    moderation = owner.call("GET", f"/api/product/feedback/moderation/items/{feedback_id}")["feedback"]
    if moderation["status"] != "submitted" or "owner_principal" in json.dumps(moderation):
        raise AssertionError("moderation projection is invalid or leaked owner identity")
    print(json.dumps({"status": "passed", "restart_verified": args.verify, "feedback_id": feedback_id, "secondary_user_hidden": True}, indent=2))


if __name__ == "__main__":
    main()
