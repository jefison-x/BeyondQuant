from __future__ import annotations
import importlib.util, sys
from pathlib import Path
MODULE=Path(__file__).parents[1]/"relay.py"; SPEC=importlib.util.spec_from_file_location("feedback_hub_relay",MODULE)
assert SPEC and SPEC.loader
relay=importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=relay; SPEC.loader.exec_module(relay)

def test_config_requires_https_and_users_need_no_github_values(monkeypatch) -> None:
    monkeypatch.setenv("BYQ_FEEDBACK_HUB_URL","https://feedback.example.org")
    monkeypatch.setenv("BYQ_FEEDBACK_HUB_RELAY_TOKEN","relay-token")
    config=relay.Config.from_env(); assert config.hub_url=="https://feedback.example.org"
    assert not any("github" in field for field in config.__dataclass_fields__)

def test_delivery_preserves_exact_snapshot_and_receipt(monkeypatch) -> None:
    calls=[]; config=relay.Config("http://backend","relay-token","https://feedback.example.org","relay-worker",15)
    event={"event_id":"feedback_hub_event_"+"a"*32,"installation_id":"byq-installation-"+"b"*32,
           "snapshot_hash":"c"*64,"snapshot":{"schema_version":"submitted-feedback-snapshot.v1"},"lease_fence":3}
    monkeypatch.setattr(relay,"_json_request",lambda url,**kwargs:calls.append((url,kwargs)) or {"schema_version":"central-feedback-receipt.v1","receipt_id":"central_feedback_"+"d"*32,"status_token":"e"*64,"status":"received"})
    monkeypatch.setattr(relay,"_backend",lambda _config,path,**kwargs:calls.append((path,kwargs)) or {})
    relay._deliver(config,event)
    assert calls[0][1]["payload"]["snapshot_hash"]=="c"*64
    assert calls[1][0].endswith("/complete") and calls[1][1]["payload"]["status_token"]=="e"*64


def test_malformed_success_receipt_is_unknown_and_never_completed(monkeypatch):
    config=relay.Config('http://backend','relay-token','https://feedback.example.org','relay-worker',15)
    event={'event_id':'feedback_hub_event_'+'a'*32,'installation_id':'byq-installation-'+'b'*32,
        'snapshot_hash':'c'*64,'snapshot':{},'lease_fence':3}
    for receipt in ({}, {'receipt_id':'wrong','status_token':'e'*64},
        {'schema_version':'central-feedback-receipt.v1','receipt_id':'central_feedback_'+'d'*32,
         'status_token':'e'*64,'status':'invented'},
        {'schema_version':'central-feedback-receipt.v1','receipt_id':'central_feedback_'+'d'*32,
         'status_token':'e'*64,'status':[]}):
        calls=[]
        monkeypatch.setattr(relay,'_json_request',lambda *args,**kwargs:receipt)
        monkeypatch.setattr(relay,'_backend',lambda config,path,**kwargs:calls.append((path,kwargs['payload'])) or {})
        relay._deliver(config,event)
        assert len(calls)==1 and calls[0][0].endswith('/retry')
        assert calls[0][1]['error_category']=='hub_unavailable'
        assert calls[0][1]['lease_fence']==3


def test_http_commit_then_lost_reply_reuses_same_original_event(monkeypatch):
    import json, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    persisted={}; attempts=[]; callbacks=[]
    class Hub(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['content-length'])))
            attempts.append(body)
            key=(body['installation_id'],body['event_id'],body['snapshot_hash'])
            receipt=persisted.setdefault(key,{'schema_version':'central-feedback-receipt.v1',
                'receipt_id':'central_feedback_'+'d'*32,'status_token':'e'*64,'status':'publishing'})
            if len(attempts)==1:
                self.close_connection=True
                self.connection.shutdown(2)
                self.connection.close()
                return
            raw=json.dumps(receipt).encode()
            self.send_response(202); self.send_header('content-length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def log_message(self,*args): pass
    hub=ThreadingHTTPServer(('127.0.0.1',0),Hub)
    thread=threading.Thread(target=hub.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(relay,'_backend',lambda config,path,**kwargs:callbacks.append((path,kwargs['payload'])) or {})
    event={'event_id':'feedback_hub_event_'+'a'*32,'installation_id':'byq-installation-'+'b'*32,
        'snapshot_hash':'c'*64,'snapshot':{'schema_version':'submitted-feedback-snapshot.v1'},'lease_fence':1}
    try:
        first=relay.Config('http://backend','relay-token',f'http://127.0.0.1:{hub.server_port}','worker-original',15)
        relay._deliver(first,event)
        assert callbacks[-1][0].endswith('/retry') and callbacks[-1][1]['error_category']=='hub_unavailable'
        # A different worker/fence represents a durable re-claim, not a local write loop.
        replacement=relay.Config(first.backend_url,first.service_token,first.hub_url,'worker-replacement',15)
        relay._deliver(replacement,{**event,'lease_fence':2})
        assert callbacks[-1][0].endswith('/complete')
        assert callbacks[-1][1]['receipt_id']=='central_feedback_'+'d'*32
        assert callbacks[-1][1]['lease_fence']==2
        assert len(persisted)==1 and len(attempts)==2 and attempts[0]==attempts[1]
    finally:
        hub.shutdown();hub.server_close();thread.join(timeout=2)


def test_invalid_json_encoding_and_oversized_http_success_stay_unknown(monkeypatch):
    import io
    import pytest
    class Response(io.BytesIO):
        status=202
    for raw in (b'{',b'\xff',b'[]',b'{}'+b' '*(64*1024)):
        monkeypatch.setattr(relay.urllib.request,'urlopen',lambda *args,**kwargs:Response(raw))
        with pytest.raises(relay.RelayError) as error:
            relay._json_request('https://feedback.example.org/v1/intake',method='POST',payload={},expected=202)
        assert error.value.category=='hub_unavailable'


def test_status_refresh_reserves_durable_candidates_before_remote_reads(monkeypatch):
    config=relay.Config('http://backend','relay-token','https://feedback.example.org','relay-worker',15)
    item={'event_id':'feedback_hub_event_'+'a'*32,'receipt_id':'central_feedback_'+'d'*32,'status_token':'e'*64}
    calls=[]
    def backend(_config,path,**kwargs):
        calls.append((path,kwargs))
        return {'schema_version':'feedback-hub-status-checks.v1','items':[item]}
    def remote(url,**kwargs):
        assert calls[0]==('/internal/feedback-hub/status-checks/claim',{'payload':{'limit':10}})
        assert url.endswith('/v1/status/'+item['receipt_id'])
        assert kwargs['headers']['authorization']=='Bearer '+item['status_token']
        return {'schema_version':'central-feedback-status.v1','receipt_id':item['receipt_id'],'status':'accepted','github_issue':None}
    monkeypatch.setattr(relay,'_backend',backend)
    monkeypatch.setattr(relay,'_json_request',remote)
    relay._refresh_statuses(config)
    assert calls[1][0]=='/internal/feedback-hub/'+item['event_id']+'/status'
    assert calls[1][1]['payload']['status']=='accepted'


def test_http_redirect_cannot_forward_credentials():
    import pytest
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    received = []
    class Sink(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            received.append(dict(self.headers))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{sink.server_port}/untrusted')
            self.end_headers()
    source = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (sink, source)]
    for thread in threads: thread.start()
    try:
        with pytest.raises(relay.RelayError):
            relay._json_request(f'http://127.0.0.1:{source.server_port}/receipt',
                headers={'Authorization':'Bearer synthetic-redirect-token',
                         'x-byq-feedback-hub-relay-token':'synthetic-service-token'})
        assert received == [], 'redirect target must receive neither request nor credential'
    finally:
        for server in (source, sink): server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=2)
