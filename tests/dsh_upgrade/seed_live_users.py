#!/usr/bin/env python3
"""Create isolated synthetic Product users for repeated U5 approval journeys."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import main


USERS = ("u5-g3b", "u5-g3c")
PASSWORD = "U5SyntheticUserOnly123"


def main_seed() -> None:
    client = TestClient(main.app)
    created: list[str] = []
    for username in USERS:
        response = client.post(
            "/v1/users",
            headers={"x-byq-actor-role": "admin"},
            json={
                "username": username,
                "password": PASSWORD,
                "display_name": f"U5 synthetic {username}",
                "role": "user",
            },
        )
        if response.status_code != 201:
            raise AssertionError(
                f"synthetic user creation failed with {response.status_code}: {response.text}"
            )
        created.append(username)
    print(json.dumps({"created": created, "synthetic": True}, sort_keys=True))


if __name__ == "__main__":
    main_seed()
