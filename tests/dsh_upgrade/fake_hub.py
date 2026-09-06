"""Test-only Hub sink. No upstream URL, publisher, credential or outbound client."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Sink:
    def __init__(self):
        self.lock = threading.Lock()
        self.receipts = {}
        self.attempts = 0

    def accept(self, body):
        if not isinstance(body, dict) or set(body) != {"schema_version", "installation_id", "event_id", "snapshot_hash", "snapshot"}:
            raise ValueError("invalid envelope")
        if body["schema_version"] != "central-feedback-intake.v1" or digest(body["snapshot"]) != body["snapshot_hash"]:
            raise ValueError("invalid schema or snapshot hash")
        key = digest([body["installation_id"], body["event_id"]])
        with self.lock:
            self.attempts += 1
            existing = self.receipts.get(key)
            if existing and existing["snapshot_hash"] != body["snapshot_hash"]:
                raise ValueError("idempotency conflict")
            self.receipts[key] = {"receipt_id": "central_feedback_" + key[:32], "snapshot_hash": body["snapshot_hash"],
                                  "status_token": digest([key, "synthetic-status-only"]), "status": "received"}
            return {k: v for k, v in self.receipts[key].items() if k != "snapshot_hash"}

    def evidence(self):
        with self.lock:
            return {"schema_version": "byq-u5-fake-hub.v1", "received": len(self.receipts),
                    "attempts": self.attempts, "published": 0,
                    "snapshot_hashes": sorted(row["snapshot_hash"] for row in self.receipts.values())}


SINK = Sink()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self.reply(200, {"service": "byq-u5-fake-hub", "status": "ok"})
        elif self.path == "/evidence":
            self.reply(200, SINK.evidence())
        elif self.path.startswith("/v1/status/"):
            with SINK.lock:
                row = next((r for r in SINK.receipts.values() if self.path == "/v1/status/" + r["receipt_id"]), None)
                if row and self.headers.get("authorization") == "Bearer " + row["status_token"]:
                    self.reply(200, {"schema_version": "central-feedback-status.v1", "receipt_id": row["receipt_id"], "status": "received", "github_issue": None})
                else:
                    self.reply(404, {"detail": "not found"})
        else:
            self.reply(404, {"detail": "not found"})

    def do_POST(self):
        if self.path != "/v1/intake":
            self.reply(404, {"detail": "not found"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            if not 0 < length <= 32768:
                raise ValueError("body limit")
            self.reply(202, SINK.accept(json.loads(self.rfile.read(length))))
        except (ValueError, TypeError):
            self.reply(422, {"detail": "invalid synthetic intake"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8800), Handler).serve_forever()
