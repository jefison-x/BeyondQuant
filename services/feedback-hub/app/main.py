"""Anonymous central feedback intake, moderation and fixed GitHub outbox."""
from __future__ import annotations

import hashlib, hmac, json, os, re, secrets, uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Iterator

from fastapi import FastAPI, HTTPException, Request
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

MAX_BYTES, HOURLY_LIMIT, MAX_ATTEMPTS = 32 * 1024, 5, 6
PREVIEW_SCHEMA = "feedback-publication-preview.v1"
CATEGORIES = {"bug", "feature", "performance", "usability", "other"}
COMPONENTS = {
    "xiaoba", "stock_pool", "strategy", "model_research", "backtest",
    "data_center", "system_settings", "auth", "runtime", "other",
}
SEVERITIES = {"low", "normal", "high"}
ENVIRONMENT_FIELDS = {
    "product_version", "deployment_kind", "browser_family", "os_family", "performance_summary",
}
REPOSITORY = os.getenv("BYQ_FEEDBACK_GITHUB_REPOSITORY", "jefison-x/BeyondQuant")
DATABASE_URL = os.getenv("BYQ_FEEDBACK_HUB_DATABASE_URL", "postgresql+psycopg://byq_hub:change-me@postgres:5432/byq_feedback_hub")
ADMIN_TOKEN = os.getenv("BYQ_FEEDBACK_HUB_ADMIN_TOKEN", "")
PUBLISHER_TOKEN = os.getenv("BYQ_FEEDBACK_PUBLISHER_TOKEN", "")
STATUS_SECRET = os.getenv("BYQ_FEEDBACK_HUB_STATUS_SECRET", "")
EVENT_ID = re.compile(r"^feedback_hub_event_[0-9a-f]{32}$")
INSTALLATION_ID = re.compile(r"^byq-installation-[0-9a-f]{32}$")
RECEIPT_ID = re.compile(r"^central_feedback_[0-9a-f]{32}$")
UNSAFE = tuple(re.compile(value, re.I) for value in (
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", r"(?:https?://|www\.)\S+",
    r"(?:password|passwd|secret|authorization|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S{4,}",
    r"(?:gh[oprsu]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    r"(?:security vulnerability|remote code execution|credential leak|安全漏洞|远程代码执行|凭据泄露)",
))

def utcnow() -> str: return datetime.now(timezone.utc).isoformat()
def canonical(value: object) -> str: return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
def digest(value: object) -> str: return hashlib.sha256(canonical(value).encode()).hexdigest()
def opaque(value: str) -> str: return hmac.new(STATUS_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
def receipt_token(receipt: str) -> str: return opaque(f"feedback-status:{receipt}")

def _params(values: dict[str, Any]) -> dict[str, Any]:
    return {key: Jsonb(value) if isinstance(value, (dict, list)) else value for key, value in values.items()}

def execute(connection: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    result = connection.execute(text(sql), _params(params or {}))
    if not result.returns_rows: return []
    return [{key: value.isoformat() if isinstance(value, datetime) else value for key, value in dict(row).items()}
            for row in result.mappings().all()]

def one(connection: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = execute(connection, sql, params); return rows[0] if rows else None

class HubStore:
    def __init__(self, database_url: str = DATABASE_URL) -> None:
        if len(STATUS_SECRET) < 32: raise RuntimeError("BYQ_FEEDBACK_HUB_STATUS_SECRET must contain at least 32 characters")
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", REPOSITORY) is None: raise RuntimeError("fixed repository is invalid")
        self.engine = create_engine(database_url, pool_pre_ping=True, future=True); self.bootstrap()

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        with self.engine.begin() as connection: yield connection

    def bootstrap(self) -> None:
        statements = (
            """CREATE TABLE IF NOT EXISTS central_feedback(receipt_id TEXT PRIMARY KEY,installation_hash TEXT NOT NULL,
            source_event_hash TEXT NOT NULL,snapshot_json JSONB NOT NULL,snapshot_hash TEXT NOT NULL,fingerprint TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('received','triaged','accepted','rejected','duplicate','publishing','published')),
            duplicate_of TEXT REFERENCES central_feedback(receipt_id),github_repository TEXT,github_issue_number INTEGER,
            github_html_url TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE(installation_hash,source_event_hash))""",
            "CREATE INDEX IF NOT EXISTS central_feedback_page ON central_feedback(status,created_at,receipt_id)",
            "CREATE INDEX IF NOT EXISTS central_feedback_rate ON central_feedback(installation_hash,created_at)",
            "CREATE INDEX IF NOT EXISTS central_feedback_fingerprint ON central_feedback(fingerprint)",
            """CREATE TABLE IF NOT EXISTS central_feedback_audit(audit_id TEXT PRIMARY KEY,receipt_id TEXT NOT NULL
            REFERENCES central_feedback(receipt_id),action TEXT NOT NULL,actor TEXT NOT NULL,from_status TEXT,to_status TEXT NOT NULL,
            detail_json JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS central_feedback_outbox(event_id TEXT PRIMARY KEY,receipt_id TEXT NOT NULL UNIQUE
            REFERENCES central_feedback(receipt_id),snapshot_json JSONB NOT NULL,snapshot_hash TEXT NOT NULL,state TEXT NOT NULL
            CHECK(state IN ('queued','publishing','retry_wait','published','failed_terminal')),attempt INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL,lease_owner TEXT,lease_expires_at TIMESTAMPTZ,lease_fence INTEGER NOT NULL DEFAULT 0,
            last_error_category TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS central_feedback_outbox_due ON central_feedback_outbox(state,next_attempt_at,event_id)",
        )
        with self.tx() as connection:
            for statement in statements: connection.execute(text(statement))

    @staticmethod
    def snapshot(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != {"schema_version", "public_content", "redactions", "preview_hash"}:
            raise ValueError("snapshot shape is invalid")
        if value["schema_version"] != "submitted-feedback-snapshot.v1":
            raise ValueError("snapshot schema is invalid")
        public = value["public_content"]
        required = {
            "category", "component", "title", "description", "reproduction_steps",
            "expected_behavior", "actual_behavior", "severity", "environment",
        }
        if not isinstance(public, dict) or set(public) != required:
            raise ValueError("public content shape is invalid")
        if public["category"] not in CATEGORIES or public["component"] not in COMPONENTS or public["severity"] not in SEVERITIES:
            raise ValueError("feedback classification is invalid")
        fields = (("title", 4, 160), ("description", 1, 8000),
                  ("expected_behavior", 0, 2000), ("actual_behavior", 0, 2000))
        if any(not isinstance(public[field], str) or not minimum <= len(public[field]) <= maximum
               for field, minimum, maximum in fields):
            raise ValueError("feedback text is invalid")
        steps = public["reproduction_steps"]
        if (not isinstance(steps, list) or len(steps) > 12
                or any(not isinstance(step, str) or not 1 <= len(step) <= 500 for step in steps)):
            raise ValueError("steps are invalid")
        environment = public["environment"]
        if (not isinstance(environment, dict) or set(environment) - ENVIRONMENT_FIELDS
                or any(not isinstance(item, str) or not 1 <= len(item) <= 80 for item in environment.values())):
            raise ValueError("environment is invalid")
        redactions = value["redactions"]
        if (not isinstance(redactions, dict) or set(redactions) != {"categories", "count"}
                or not isinstance(redactions["categories"], list) or not isinstance(redactions["count"], int)
                or redactions["count"] != len(redactions["categories"])):
            raise ValueError("redactions are invalid")
        if any(pattern.search(canonical(public)) for pattern in UNSAFE):
            raise ValueError("content cannot enter a public issue")
        preview_hash = value["preview_hash"]
        expected_preview_hash = digest({"schema_version": PREVIEW_SCHEMA, "public_content": public})
        if not isinstance(preview_hash, str) or not hmac.compare_digest(preview_hash, expected_preview_hash):
            raise ValueError("preview hash is invalid")
        return value

    def intake(self, payload: object) -> dict[str, Any]:
        allowed = {"schema_version","installation_id","event_id","snapshot_hash","snapshot"}
        if not isinstance(payload, dict) or set(payload) != allowed or payload.get("schema_version") != "central-feedback-intake.v1" or len(canonical(payload).encode()) > MAX_BYTES: raise ValueError("intake is invalid or too large")
        installation, event = payload.get("installation_id"), payload.get("event_id")
        if not isinstance(installation,str) or INSTALLATION_ID.fullmatch(installation) is None: raise ValueError("installation id is invalid")
        if not isinstance(event,str) or EVENT_ID.fullmatch(event) is None: raise ValueError("event id is invalid")
        snapshot = self.snapshot(payload.get("snapshot")); snapshot_hash = payload.get("snapshot_hash")
        if snapshot_hash != digest(snapshot): raise ValueError("snapshot hash does not match")
        installation_hash, event_hash, timestamp = opaque(installation), opaque(event), utcnow()
        with self.tx() as connection:
            execute(connection, "SELECT pg_advisory_xact_lock(hashtextextended(:installation, 0))", {"installation": installation_hash})
            existing = one(connection,"SELECT receipt_id,snapshot_hash,status FROM central_feedback WHERE installation_hash=:i AND source_event_hash=:e FOR UPDATE",{"i":installation_hash,"e":event_hash})
            if existing:
                if existing["snapshot_hash"] != snapshot_hash: raise RuntimeError("idempotency conflict")
                return {"schema_version":"central-feedback-receipt.v1","receipt_id":existing["receipt_id"],"status_token":receipt_token(existing["receipt_id"]),"status":existing["status"]}
            count = one(connection,"SELECT COUNT(*) AS count FROM central_feedback WHERE installation_hash=:i AND created_at>=:cutoff",{"i":installation_hash,"cutoff":(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()})
            if count and int(count["count"]) >= HOURLY_LIMIT: raise OverflowError("rate limit reached")
            public=snapshot["public_content"]; fingerprint=digest({"category":public["category"],"component":public["component"],"title":public["title"].strip().casefold(),"description":public["description"].strip().casefold()})
            receipt=f"central_feedback_{uuid.uuid4().hex}"
            execute(connection,"""INSERT INTO central_feedback(receipt_id,installation_hash,source_event_hash,snapshot_json,
            snapshot_hash,fingerprint,status,created_at,updated_at) VALUES(:r,:i,:e,:s,:h,:f,'received',:n,:n)""",
                    {"r":receipt,"i":installation_hash,"e":event_hash,"s":snapshot,"h":snapshot_hash,"f":fingerprint,"n":timestamp})
            self._audit(connection,receipt,"receive",None,"received",{"snapshot_hash":snapshot_hash},timestamp)
        return {"schema_version":"central-feedback-receipt.v1","receipt_id":receipt,"status_token":receipt_token(receipt),"status":"received"}

    @staticmethod
    def _audit(connection: Connection, receipt: str, action: str, source: str | None, target: str, detail: dict[str,Any], timestamp: str) -> None:
        execute(connection,"""INSERT INTO central_feedback_audit(audit_id,receipt_id,action,actor,from_status,to_status,detail_json,created_at)
        VALUES(:a,:r,:x,'central-hub',:s,:t,:d,:n)""",{"a":f"hub_audit_{uuid.uuid4().hex}","r":receipt,"x":action,"s":source,"t":target,"d":detail,"n":timestamp})

    def status(self, receipt: str) -> dict[str, Any]:
        with self.tx() as connection: row=one(connection,"SELECT receipt_id,status,github_repository,github_issue_number,github_html_url FROM central_feedback WHERE receipt_id=:r",{"r":receipt})
        if row is None: raise LookupError("feedback not found")
        issue={"repository":row["github_repository"],"issue_number":row["github_issue_number"],"html_url":row["github_html_url"]} if row["status"]=="published" else None
        return {"schema_version":"central-feedback-status.v1","receipt_id":receipt,"status":row["status"],"github_issue":issue}

    def list(self, status: str, limit: int, offset: int) -> dict[str,Any]:
        statuses={"received","triaged","accepted","rejected","duplicate","publishing","published","all"}
        if status not in statuses: raise ValueError("status is invalid")
        limit=min(max(limit,1),100); offset=max(offset,0); where="TRUE" if status=="all" else "status=:status"; params={"status":status,"limit":limit,"offset":offset}
        with self.tx() as connection:
            count=one(connection,f"SELECT COUNT(*) AS count FROM central_feedback WHERE {where}",params)
            rows=execute(connection,f"""SELECT receipt_id,status,snapshot_json,snapshot_hash,fingerprint,duplicate_of,
            github_repository,github_issue_number,github_html_url,created_at,updated_at FROM central_feedback WHERE {where}
            ORDER BY created_at,receipt_id LIMIT :limit OFFSET :offset""",params)
        return {"schema_version":"central-feedback-admin-catalog.v1","items":rows,"total":int(count["count"] if count else 0),"limit":limit,"offset":offset}

    def moderate(self, receipt: str, action: str, payload: object) -> dict[str,Any]:
        if not isinstance(payload,dict) or set(payload)-{"rationale","duplicate_of"}: raise ValueError("moderation request is invalid")
        rationale=payload.get("rationale")
        if not isinstance(rationale,str) or not 3<=len(rationale)<=1000: raise ValueError("rationale is invalid")
        transitions={"triage":("received","triaged"),"accept":("triaged","accepted"),"reject":("triaged","rejected"),"duplicate":("triaged","duplicate")}
        if action not in transitions: raise ValueError("action is invalid")
        source,target=transitions[action]; timestamp=utcnow(); duplicate=None
        with self.tx() as connection:
            row=one(connection,"SELECT * FROM central_feedback WHERE receipt_id=:r FOR UPDATE",{"r":receipt})
            if row is None: raise LookupError("feedback not found")
            if row["status"] != source: raise RuntimeError("feedback state changed")
            if action=="duplicate":
                duplicate=payload.get("duplicate_of")
                if not isinstance(duplicate,str) or RECEIPT_ID.fullmatch(duplicate) is None or duplicate==receipt or one(connection,"SELECT receipt_id FROM central_feedback WHERE receipt_id=:r",{"r":duplicate}) is None: raise ValueError("duplicate target is invalid")
            execute(connection,"UPDATE central_feedback SET status=:t,duplicate_of=:d,updated_at=:n WHERE receipt_id=:r",{"t":target,"d":duplicate,"n":timestamp,"r":receipt})
            if action=="accept":
                publication={"schema_version":"feedback-publication.v1","public_content":row["snapshot_json"]["public_content"],"redactions":row["snapshot_json"]["redactions"]}
                execute(connection,"""INSERT INTO central_feedback_outbox(event_id,receipt_id,snapshot_json,snapshot_hash,state,
                attempt,next_attempt_at,lease_fence,created_at,updated_at) VALUES(:e,:r,:s,:h,'queued',0,:n,0,:n,:n)""",
                        {"e":f"feedback_outbox_{uuid.uuid4().hex}","r":receipt,"s":publication,"h":digest(publication),"n":timestamp})
            self._audit(connection,receipt,action,source,target,{"rationale":rationale,"duplicate_of":duplicate},timestamp)
        return self.status(receipt)

    def claim(self, payload: dict[str,Any]) -> dict[str,Any]:
        worker=str(payload.get("worker_id", "")); limit=min(max(int(payload.get("limit",5)),1),10); seconds=min(max(int(payload.get("lease_seconds",60)),15),300)
        if not 3<=len(worker)<=80: raise ValueError("worker id is invalid")
        current=datetime.now(timezone.utc); timestamp=current.isoformat(); expiry=(current+timedelta(seconds=seconds)).isoformat(); events=[]
        with self.tx() as connection:
            rows=execute(connection,"""SELECT * FROM central_feedback_outbox WHERE ((state IN ('queued','retry_wait') AND
            next_attempt_at<=:n) OR (state='publishing' AND lease_expires_at<:n)) ORDER BY next_attempt_at,event_id
            FOR UPDATE SKIP LOCKED LIMIT :l""",{"n":timestamp,"l":limit})
            for row in rows:
                attempt=int(row["attempt"])+1; fence=int(row["lease_fence"])+1
                execute(connection,"""UPDATE central_feedback_outbox SET state='publishing',attempt=:a,lease_owner=:w,
                lease_expires_at=:x,lease_fence=:f,updated_at=:n WHERE event_id=:e""",{"a":attempt,"w":worker,"x":expiry,"f":fence,"n":timestamp,"e":row["event_id"]})
                execute(connection,"UPDATE central_feedback SET status='publishing',updated_at=:n WHERE receipt_id=:r",{"n":timestamp,"r":row["receipt_id"]})
                events.append({"event_id":row["event_id"],"feedback_id":row["receipt_id"],"publication_id":row["receipt_id"],"snapshot_hash":row["snapshot_hash"],"snapshot":row["snapshot_json"],"attempt":attempt,"lease_fence":fence,"lease_expires_at":expiry})
        return {"schema_version":"feedback-publisher-claim.v1","events":events}

    def result(self, event: str, payload: dict[str,Any], success: bool) -> dict[str,Any]:
        timestamp=utcnow()
        with self.tx() as connection:
            row=one(connection,"SELECT * FROM central_feedback_outbox WHERE event_id=:e FOR UPDATE",{"e":event})
            if row is None: raise LookupError("publication not found")
            if row["state"]!="publishing" or row["lease_owner"]!=payload.get("worker_id") or int(row["lease_fence"])!=payload.get("lease_fence"): raise RuntimeError("publication lease is stale")
            if success:
                number=payload.get("issue_number"); url=f"https://github.com/{REPOSITORY}/issues/{number}"
                if payload.get("repository")!=REPOSITORY or not isinstance(number,int) or number<1 or payload.get("html_url")!=url: raise ValueError("publication target is invalid")
                execute(connection,"UPDATE central_feedback_outbox SET state='published',lease_owner=NULL,lease_expires_at=NULL,updated_at=:n WHERE event_id=:e",{"n":timestamp,"e":event})
                execute(connection,"""UPDATE central_feedback SET status='published',github_repository=:p,github_issue_number=:i,
                github_html_url=:u,updated_at=:n WHERE receipt_id=:r""",{"p":REPOSITORY,"i":number,"u":url,"n":timestamp,"r":row["receipt_id"]})
                return {"schema_version":"feedback-publisher-result.v1","status":"published","issue_number":number,"html_url":url}
            category=str(payload.get("error_category","provider_unavailable")); terminal=category in {"authentication_failed","permission_denied","repository_unavailable","issues_disabled","validation_rejected","reconciliation_conflict"} or int(row["attempt"])>=MAX_ATTEMPTS; target="failed_terminal" if terminal else "retry_wait"; retry=min(max(int(payload.get("retry_after_seconds",30)),5),3600)
            execute(connection,"""UPDATE central_feedback_outbox SET state=:s,next_attempt_at=:x,lease_owner=NULL,
            lease_expires_at=NULL,last_error_category=:c,updated_at=:n WHERE event_id=:e""",{"s":target,"x":(datetime.now(timezone.utc)+timedelta(seconds=retry)).isoformat(),"c":category,"n":timestamp,"e":event})
            execute(connection,"UPDATE central_feedback SET status='accepted',updated_at=:n WHERE receipt_id=:r",{"n":timestamp,"r":row["receipt_id"]})
            return {"schema_version":"feedback-publisher-result.v1","status":target,"error_category":category,"attempt":row["attempt"]}

store: HubStore|None=None

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global store
    if len(ADMIN_TOKEN) < 32:
        raise RuntimeError("BYQ_FEEDBACK_HUB_ADMIN_TOKEN must contain at least 32 characters")
    if len(PUBLISHER_TOKEN) < 32:
        raise RuntimeError("BYQ_FEEDBACK_PUBLISHER_TOKEN must contain at least 32 characters")
    store=HubStore()
    try:
        yield
    finally:
        store.engine.dispose()
        store=None

app=FastAPI(title="BeyondQuant Central Feedback Hub",version="1.0",lifespan=lifespan)
def active() -> HubStore:
    if store is None: raise HTTPException(503,"hub storage is unavailable")
    return store
def bearer(request: Request, expected: str, purpose: str) -> None:
    raw=request.headers.get("authorization",""); supplied=raw[7:] if raw.startswith("Bearer ") else ""
    if not expected or not supplied or not secrets.compare_digest(supplied,expected): raise HTTPException(401,f"{purpose} authentication failed")
def publisher(request: Request) -> None:
    supplied=request.headers.get("x-byq-feedback-publisher-token","")
    if not PUBLISHER_TOKEN or not supplied or not secrets.compare_digest(supplied,PUBLISHER_TOKEN): raise HTTPException(401,"publisher authentication failed")
@app.get("/healthz")
def health() -> dict[str,str]: return {"service":"central-feedback-hub","status":"ok"}
@app.post("/v1/intake",status_code=202)
def intake(payload:dict[str,Any])->dict[str,Any]:
    try:return active().intake(payload)
    except OverflowError as exc:raise HTTPException(429,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.get("/v1/status/{receipt}")
def status(receipt:str,request:Request)->dict[str,Any]:
    if RECEIPT_ID.fullmatch(receipt) is None:raise HTTPException(404,"feedback not found")
    bearer(request,receipt_token(receipt),"feedback status")
    try:return active().status(receipt)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
@app.get("/v1/admin/feedback")
def admin_list(request:Request,status:str="received",limit:int=20,offset:int=0)->dict[str,Any]:
    bearer(request,ADMIN_TOKEN,"feedback administrator")
    try:return active().list(status,limit,offset)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.post("/v1/admin/feedback/{receipt}/{action}")
def moderate(receipt:str,action:str,payload:dict[str,Any],request:Request)->dict[str,Any]:
    bearer(request,ADMIN_TOKEN,"feedback administrator")
    try:return active().moderate(receipt,action,payload)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.post("/internal/feedback-publications/heartbeat")
def heartbeat(payload:dict[str,Any],request:Request)->dict[str,Any]:
    publisher(request)
    if payload.get("configured") is not True or payload.get("repository")!=REPOSITORY:raise HTTPException(409,"publisher destination is not fixed repository")
    return {"schema_version":"feedback-publisher-heartbeat.v1","accepted":True,"configured":True}
@app.post("/internal/feedback-publications/claim")
def claim(payload:dict[str,Any],request:Request)->dict[str,Any]:
    publisher(request)
    try:return active().claim(payload)
    except (ValueError,TypeError) as exc:raise HTTPException(422,str(exc)) from exc
def finish(event:str,payload:dict[str,Any],request:Request,success:bool)->dict[str,Any]:
    publisher(request)
    try:return active().result(event,payload,success)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(409,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
@app.post("/internal/feedback-publications/{event}/complete")
def complete(event:str,payload:dict[str,Any],request:Request)->dict[str,Any]:return finish(event,payload,request,True)
@app.post("/internal/feedback-publications/{event}/retry")
def retry(event:str,payload:dict[str,Any],request:Request)->dict[str,Any]:return finish(event,payload,request,False)
