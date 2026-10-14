"""Closed Product approval requests; domain stores remain the authority."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import execute, fetch_one
from .research_continuation import _request_v2
from packages.contracts.product_approval_requests import (
    REQUEST_SCHEMA, LIST_SCHEMA, DECISION_SCHEMA, REQUEST_TYPES,
    REQUEST_KEY, validate_request_shape,
)

REQUEST_ID_RE = re.compile(r"^approval_request_[0-9a-f]{32}$")
MATERIALIZATION_ERROR_CODES = frozenset({
    "domain_validation_failed", "domain_conflict", "domain_scope_unavailable",
    "domain_request_rejected", "domain_unavailable",
    "domain_fact_missing", "domain_fact_draft", "domain_fact_mismatch",
})


class ProductApprovalConflict(Exception):
    pass


class ProductApprovalNotFound(Exception):
    pass

SCHEMA_DDL = [
    """CREATE TABLE IF NOT EXISTS product_approval_requests (
        request_id TEXT PRIMARY KEY,
        request_type TEXT NOT NULL CHECK (request_type IN
          ('continuation_consent','strategy_version','ml_strategy_version')),
        owner_principal TEXT NOT NULL,
        workspace_id TEXT NOT NULL,
        task_id TEXT NOT NULL REFERENCES research_tasks(task_id),
        resource_artifact_id TEXT REFERENCES artifacts(artifact_id),
        content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
        conversation_id TEXT,
        request_key TEXT NOT NULL,
        request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
        request_json JSONB NOT NULL,
        status TEXT NOT NULL CHECK (status IN
          ('pending','decision_recorded','approved','rejected','outcome_unknown','needs_attention')),
        decision TEXT CHECK (decision IN ('approved','rejected')),
        decision_key TEXT,
        decision_sha256 TEXT,
        decision_by TEXT,
        decision_at TIMESTAMPTZ,
        rationale TEXT,
        materialization_error_code TEXT CHECK (materialization_error_code IS NULL OR
          materialization_error_code IN ('domain_validation_failed','domain_conflict','domain_scope_unavailable',
            'domain_request_rejected','domain_unavailable','domain_fact_missing','domain_fact_draft','domain_fact_mismatch')),
        domain_artifact_id TEXT REFERENCES artifacts(artifact_id),
        permission_json JSONB,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        UNIQUE(owner_principal, workspace_id, request_key),
        CHECK ((status='pending' AND decision IS NULL AND decision_key IS NULL)
            OR (status<>'pending' AND decision IS NOT NULL AND decision_key IS NOT NULL)),
        CHECK (request_type='continuation_consent' OR conversation_id IS NULL),
        CHECK ((request_type='continuation_consent' AND resource_artifact_id IS NULL)
            OR (request_type<>'continuation_consent' AND resource_artifact_id IS NOT NULL))
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS product_approval_one_unresolved_target
        ON product_approval_requests(owner_principal,workspace_id,request_type,task_id,
          COALESCE(resource_artifact_id,''))
        WHERE status IN ('pending','decision_recorded','outcome_unknown','needs_attention')""",
    """CREATE INDEX IF NOT EXISTS product_approval_requests_inbox
        ON product_approval_requests(owner_principal,workspace_id,status,created_at DESC,request_id)""",
]


def _canonical(value: object) -> tuple[dict[str, Any], str]:
    if not isinstance(value, dict):
        raise ValueError("approval request must be an object")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 16_384:
        raise ValueError("approval request is too large")
    return value, encoded


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(value: object, field: str) -> str:
    if not isinstance(value, str) or REQUEST_KEY.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def _request_id(value: object) -> str:
    if not isinstance(value, str) or REQUEST_ID_RE.fullmatch(value) is None:
        raise ValueError("request_id is invalid")
    return value


def normalize_request(payload: object) -> tuple[str, str, str, list[str], dict[str, Any], str]:
    payload = validate_request_shape(payload)
    assert isinstance(payload, dict)
    kind = payload.get("request_type")
    if kind not in REQUEST_TYPES:
        raise ValueError("approval request type is unsupported")
    key = _key(payload.get("request_key"), "request_key")
    task = payload.get("task_id")
    if not isinstance(task, str) or not re.fullmatch(r"task_[0-9a-f]{32}", task):
        raise ValueError("task_id is invalid")
    if kind == "continuation_consent":
        if set(payload) != {"schema_version", "request_type", "request_key", "task_id",
                            "confirmed_artifact_ids", "execution_profile_id"}:
            raise ValueError("continuation consent request fields are invalid")
        grant = _request_v2({
            "idempotency_key": key,
            "confirmed_artifact_ids": payload["confirmed_artifact_ids"],
            "execution_profile_id": payload["execution_profile_id"],
        })
        artifacts = grant["confirmed_artifact_ids"]
        body = {"task_id": task, "conversation_id": None,
                "confirmed_artifact_ids": artifacts,
                "execution_profile_id": grant["execution_profile"]["profile_id"],
                "execution_profile": grant["execution_profile"],
                "request_limits": grant["request_limits"], "max_turns": grant["max_turns"],
                "valid_seconds": grant["valid_seconds"],
                "turn_timeout_seconds": grant["turn_timeout_seconds"]}
        target = None
        resource_sha = _sha(json.dumps(body, sort_keys=True, separators=(",", ":")))
    else:
        artifact_key = "strategy_version_artifact_id" if kind == "strategy_version" else "ml_strategy_artifact_id"
        if set(payload) != {"schema_version", "request_type", "request_key", "task_id", artifact_key}:
            raise ValueError("strategy approval request fields are invalid")
        target = payload[artifact_key]
        if not isinstance(target, str) or not re.fullmatch(r"artifact_[0-9a-f]{32}", target):
            raise ValueError(f"{artifact_key} is invalid")
        body = {"task_id": task, artifact_key: target}
        artifacts = [target]
        resource_sha = ""
    _, encoded = _canonical(body)
    return kind, task, key, artifacts, body, resource_sha


class ProductApprovalRequestMixin:
    def create_product_approval_request(self, payload: object, *, owner: str, workspace: str) -> dict[str, object]:
        kind, task_id, key, artifact_ids, body, resource_sha = normalize_request(payload)
        with self._transaction() as connection:
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"product-approval-key|{owner}|{workspace}|{key}"})
            execute(connection, "SELECT pg_advisory_xact_lock(hashtext(:scope))",
                    {"scope": f"product-approval-target|{owner}|{workspace}|{kind}|{task_id}|{','.join(artifact_ids)}"})
            task = fetch_one(connection, "SELECT * FROM research_tasks WHERE task_id=:task FOR UPDATE", {"task": task_id})
            if task is None or task.get("owner_principal") != owner or task.get("workspace_id") != workspace:
                raise ValueError("research task not found")
            conversation_id = task.get("conversation_id")
            if kind == "continuation_consent":
                if not isinstance(conversation_id, str) or not conversation_id:
                    raise ValueError("continuation consent requires the task's original conversation")
                actual = []
                for artifact_id in artifact_ids:
                    artifact = fetch_one(connection, """SELECT artifact_id,kind,status,content_sha256
                        FROM artifacts WHERE artifact_id=:artifact AND task_id=:task
                          AND owner_principal=:owner AND workspace_id=:workspace FOR SHARE""",
                        {"artifact": artifact_id, "task": task_id, "owner": owner, "workspace": workspace})
                    if artifact is None or artifact["kind"] not in {"strategy_version", "ml_strategy_version"} or artifact["status"] != "validated":
                        raise ValueError("confirmed strategy Artifact is not valid in this task/workspace")
                    actual.append({"artifact_id": artifact_id, "content_sha256": artifact["content_sha256"],
                                   "kind": artifact["kind"]})
                body["conversation_id"] = conversation_id
                body["confirmed_artifacts"] = actual
                resource_sha = _sha(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            else:
                artifact_id = artifact_ids[0]
                artifact = fetch_one(connection, """SELECT artifact_id,task_id,owner_principal,workspace_id,
                    kind,status,content_sha256 FROM artifacts WHERE artifact_id=:artifact FOR SHARE""",
                    {"artifact": artifact_id})
                expected_kind = "strategy_version" if kind == "strategy_version" else "ml_strategy_version"
                if (artifact is None or artifact["task_id"] != task_id or artifact["owner_principal"] != owner
                        or artifact["workspace_id"] != workspace or artifact["kind"] != expected_kind
                        or artifact["status"] != "validated"):
                    raise ValueError("validated strategy version not found in this task/workspace")
                resource_sha = artifact["content_sha256"]
                body["content_sha256"] = resource_sha
            request_digest = _sha(json.dumps({"request_type": kind, **body}, sort_keys=True, separators=(",", ":")))
            existing = fetch_one(connection, """SELECT * FROM product_approval_requests
                WHERE owner_principal=:owner AND workspace_id=:workspace AND request_key=:key""",
                {"owner": owner, "workspace": workspace, "key": key})
            if existing is not None:
                if existing["request_type"] != kind or existing["request_sha256"] != request_digest:
                    raise ProductApprovalConflict("approval request key was reused")
                return self._product_approval_request_row(existing)
            if kind == "continuation_consent" and task.get("continuation_permission") is not None:
                raise ProductApprovalConflict("continuation permission already exists")
            target_resource = artifact_ids[0] if kind != "continuation_consent" else None
            if kind != "continuation_consent":
                approval_kind = "strategy_approval" if kind == "strategy_version" else "ml_strategy_approval"
                target_field = "strategy_version_artifact_id" if kind == "strategy_version" else "ml_strategy_artifact_id"
                prior = fetch_one(connection, f"""SELECT artifact_id FROM artifacts
                    WHERE task_id=:task AND owner_principal=:owner AND workspace_id=:workspace
                      AND kind=:kind AND status='validated' AND content->>'decision'='approved'
                      AND content->>'execution_authorized'='true'
                      AND content->>'{target_field}'=:resource LIMIT 1""",
                    {"task": task_id, "owner": owner, "workspace": workspace,
                     "kind": approval_kind, "resource": target_resource})
                if prior is not None:
                    raise ProductApprovalConflict("this exact strategy version is already approved")
            unresolved = fetch_one(connection, """SELECT request_id FROM product_approval_requests
                WHERE owner_principal=:owner AND workspace_id=:workspace AND request_type=:kind
                  AND task_id=:task AND resource_artifact_id IS NOT DISTINCT FROM :resource
                  AND status IN ('pending','decision_recorded','outcome_unknown','needs_attention') LIMIT 1""",
                {"owner": owner, "workspace": workspace, "kind": kind,
                 "task": task_id, "resource": target_resource})
            if unresolved is not None:
                raise ProductApprovalConflict("an approval request for this exact target is already unresolved")
            request_id = f"approval_request_{uuid.uuid4().hex}"
            now = _now()
            row = fetch_one(connection, """INSERT INTO product_approval_requests
                (request_id,request_type,owner_principal,workspace_id,task_id,resource_artifact_id,
                 content_sha256,conversation_id,request_key,request_sha256,request_json,status,
                 created_at,updated_at,version)
                VALUES (:id,:kind,:owner,:workspace,:task,:resource,:sha,:conversation,:key,:digest,
                 CAST(:body AS jsonb),'pending',:now,:now,1) RETURNING *""",
                {"id": request_id, "kind": kind, "owner": owner, "workspace": workspace,
                 "task": task_id, "resource": target_resource,
                 "sha": resource_sha, "conversation": conversation_id if kind == "continuation_consent" else None,
                 "key": key, "digest": request_digest,
                 "body": json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "now": now})
            return self._product_approval_request_row(row)

    def get_product_approval_request(self, request_id: object, *, owner: str, workspace: str) -> dict[str, object]:
        request_id = _request_id(request_id)
        row = self._fetch_one("""SELECT * FROM product_approval_requests WHERE request_id=:id
            AND owner_principal=:owner AND workspace_id=:workspace""",
            {"id": request_id, "owner": owner, "workspace": workspace})
        if row is None:
            raise ProductApprovalNotFound("approval request not found")
        return self._product_approval_request_row(row)

    def get_product_approval_request_by_key(self, request_key: str, *, owner: str, workspace: str) -> dict[str, object]:
        _key(request_key, "request_key")
        row = self._fetch_one("""SELECT * FROM product_approval_requests WHERE request_key=:key
            AND owner_principal=:owner AND workspace_id=:workspace ORDER BY created_at DESC LIMIT 1""",
            {"key": request_key, "owner": owner, "workspace": workspace})
        if row is None:
            raise ProductApprovalNotFound("approval request not found")
        return self._product_approval_request_row(row)

    def list_product_approval_requests(self, *, owner: str, workspace: str, status: str,
                                       limit: int, offset: int) -> dict[str, object]:
        if status not in {"pending", "unresolved", "approved", "rejected", "all"}:
            raise ValueError("approval request status is invalid")
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ValueError("approval request pagination is invalid")
        status_filter = ("" if status == "all" else
                         "AND status='pending'" if status == "pending" else
                         "AND status IN ('decision_recorded','outcome_unknown','needs_attention')" if status == "unresolved" else
                         "AND status=:status")
        params = {"owner": owner, "workspace": workspace, "status": status, "limit": limit, "offset": offset}
        rows = self._execute(f"""SELECT * FROM product_approval_requests WHERE owner_principal=:owner
            AND workspace_id=:workspace {status_filter} ORDER BY created_at DESC,request_id DESC LIMIT :limit OFFSET :offset""", params)
        counts = self._fetch_one("""SELECT
            count(*) FILTER (WHERE (:status='all' OR (:status='pending' AND status='pending')
                OR (:status='unresolved' AND status IN ('decision_recorded','outcome_unknown','needs_attention')) OR status=:status)) AS total,
            count(*) FILTER (WHERE status='pending') AS pending_count,
            count(*) FILTER (WHERE status IN ('decision_recorded','outcome_unknown','needs_attention')) AS attention_count
            FROM product_approval_requests WHERE owner_principal=:owner AND workspace_id=:workspace
            """, params)
        return {"schema_version": LIST_SCHEMA,
                "requests": [self._product_approval_request_row(row)["request"] for row in rows],
                "total": int(counts["total"]), "pending_count": int(counts["pending_count"]),
                "attention_count": int(counts["attention_count"]),
                "limit": limit, "offset": offset}

    def claim_product_approval_decision(self, request_id: str, *, owner: str, workspace: str,
                                        decision: str, decision_key: str, rationale: str,
                                        actor: str) -> dict[str, object]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("approval decision is invalid")
        _key(decision_key, "decision_key")
        if not isinstance(rationale, str) or len(rationale) > 2000:
            raise ValueError("approval rationale is invalid")
        digest = _sha(json.dumps({"decision": decision, "rationale": rationale}, sort_keys=True, separators=(",", ":")))
        with self._transaction() as connection:
            row = fetch_one(connection, """SELECT * FROM product_approval_requests WHERE request_id=:id
                AND owner_principal=:owner AND workspace_id=:workspace FOR UPDATE""",
                {"id": request_id, "owner": owner, "workspace": workspace})
            if row is None:
                raise ProductApprovalNotFound("approval request not found")
            claimed_now = False
            if row["status"] == "pending":
                now = _now()
                row = fetch_one(connection, """UPDATE product_approval_requests SET status='decision_recorded',
                    decision=:decision,decision_key=:key,decision_sha256=:digest,decision_by=:actor,
                    decision_at=:now,rationale=:rationale,updated_at=:now,version=version+1
                    WHERE request_id=:id RETURNING *""",
                    {"id": request_id, "decision": decision, "key": decision_key, "digest": digest,
                     "actor": actor, "now": now, "rationale": rationale})
                claimed_now = True
            elif (row.get("decision_key") != decision_key or row.get("decision_sha256") != digest
                  or row.get("decision") != decision):
                raise ProductApprovalConflict("approval request already has a different decision")
            return self._product_approval_request_row(row), claimed_now

    def finish_product_approval_decision(self, request_id: str, *, owner: str, workspace: str,
                                         status: str, domain_artifact_id: str | None = None,
                                         permission: dict[str, object] | None = None,
                                         materialization_error_code: str | None = None) -> dict[str, object]:
        if status not in {"approved", "rejected", "outcome_unknown", "needs_attention"}:
            raise ValueError("approval result status is invalid")
        if materialization_error_code is not None and materialization_error_code not in MATERIALIZATION_ERROR_CODES:
            raise ValueError("approval materialization error code is invalid")
        if status == "needs_attention" and materialization_error_code is None:
            raise ValueError("needs_attention requires a safe materialization error code")
        if status != "needs_attention" and materialization_error_code is not None:
            raise ValueError("materialization error code is only valid for needs_attention")
        current = self.get_product_approval_request(request_id, owner=owner, workspace=workspace)
        current_request = current["request"]
        if current_request["status"] in {"approved", "rejected"}:
            return current
        if (current_request["status"] == status
                and current_request.get("domain_artifact_id") == domain_artifact_id
                and current_request.get("permission") == permission
                and current_request.get("materialization_error_code") == materialization_error_code):
            return current
        with self._transaction() as connection:
            row = fetch_one(connection, """UPDATE product_approval_requests SET status=:status,
                domain_artifact_id=:artifact, permission_json=CAST(:permission AS jsonb),
                materialization_error_code=:error_code,
                updated_at=:now,version=version+1 WHERE request_id=:id AND owner_principal=:owner
                  AND workspace_id=:workspace AND status IN ('decision_recorded','outcome_unknown','needs_attention')
                RETURNING *""",
                {"id": request_id, "owner": owner, "workspace": workspace, "status": status,
                 "artifact": domain_artifact_id,
                 "permission": None if permission is None else json.dumps(permission, ensure_ascii=False),
                 "error_code": materialization_error_code,
                 "now": _now()})
            if row is None:
                return self.get_product_approval_request(request_id, owner=owner, workspace=workspace)
            return self._product_approval_request_row(row)

    def get_product_approval_domain_artifact(self, request_id: str, *, owner: str,
                                             workspace: str) -> dict[str, Any] | None:
        """Read only the artifact created for this request's stable domain key."""
        row = self._fetch_one("""SELECT a.* FROM product_approval_requests r
            JOIN artifacts a ON a.task_id=r.task_id AND a.idempotency_key=:domain_key
              AND a.owner_principal=r.owner_principal AND a.workspace_id=r.workspace_id
            WHERE r.request_id=:request AND r.owner_principal=:owner AND r.workspace_id=:workspace
              AND r.request_type IN ('strategy_version','ml_strategy_version')""",
            {"domain_key": f"product-approval-{request_id}", "request": request_id,
             "owner": owner, "workspace": workspace})
        return row

    @staticmethod
    def _product_approval_request_row(row: dict[str, Any]) -> dict[str, object]:
        body = row["request_json"]
        if isinstance(body, str):
            body = json.loads(body)
        result = {"request_id": row["request_id"], "request_type": row["request_type"],
                  "status": row["status"], "owner_principal": row["owner_principal"],
                  "workspace_id": row["workspace_id"], "task_id": row["task_id"],
                  "resource_artifact_id": row["resource_artifact_id"],
                  "content_sha256": row["content_sha256"], "request_key": row["request_key"],
                  "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
                  "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
                  **body}
        for field in ("decision", "decision_key", "decision_by", "decision_at", "rationale", "domain_artifact_id"):
            if row.get(field) is not None:
                value = row[field]
                result[field] = value.isoformat() if field == "decision_at" and hasattr(value, "isoformat") else value
        if row.get("materialization_error_code") is not None:
            result["materialization_error_code"] = row["materialization_error_code"]
        permission = row.get("permission_json")
        if isinstance(permission, str):
            permission = json.loads(permission)
        if permission is not None:
            result["permission"] = permission
        return {"schema_version": REQUEST_SCHEMA, "request": result}
