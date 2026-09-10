#!/usr/bin/env python3
"""Isolated real HTTP delayed-commit/MCP timeout/Gateway restart receipt probe.
Requires the dedicated tmpfs probe PostgreSQL and immutable CI images; no host ports.
"""
import json
import subprocess
import time
from pathlib import Path

SCOPE='f2-watch-probe'
NET='byq-ci-net-'+SCOPE
PREFIX='byq-ci-stack-local-u7-f2-watch-30-'
BACKEND='byq-ci-backend-'+SCOPE
GATEWAY='byq-ci-gateway-'+SCOPE

def run(*args,input=None):
    return subprocess.run(list(args),input=input,text=True,capture_output=True,check=True,timeout=60).stdout.strip()

def py(container,code,payload=None):
    return run('docker','exec','-i',container,'python','-c',code,input=json.dumps(payload) if payload is not None else None)

# Refuse any similarly named resource not explicitly isolated for this probe.
assert run('docker','inspect','-f','{{ index .Config.Labels "byq.ci.scope" }}','byq-ci-pg-'+SCOPE)==SCOPE
assert run('docker','network','inspect','-f','{{ index .Labels "byq.ci.scope" }}',NET)==SCOPE
for service,name in [('backend',BACKEND),('gateway',GATEWAY)]:
    args=['docker','run','-d','--name',name,'--label','byq.ci.scope='+SCOPE,'--network',NET]
    if service=='backend':
        args+=['--network-alias','backend','-e','BYQ_DATABASE_URL=postgresql+psycopg://byq_app:byq-app-dev@byq-ci-pg-f2-watch-probe:5432/byq_domain_test']
    else:
        args+=['-e','BYQ_BACKEND_URL=http://backend:8000','-e','BYQ_F6_EXECUTOR_ENABLED=0']
    run(*args,PREFIX+service+':latest')
    for _ in range(30):
        try:
            py(name,"import urllib.request; urllib.request.urlopen('http://127.0.0.1:"+('8000' if service=='backend' else '8100')+"/healthz',timeout=2)")
            break
        except subprocess.CalledProcessError: time.sleep(1)
    else: raise AssertionError(service+' startup failed')
seed=json.loads(py(BACKEND,"""
import json
from tests.workspace_helpers import trusted_agent_context
from app.conversation_catalog import ConversationCatalogStore
h=trusted_agent_context('f2-http-restart',session_id='f2-http-session',trace_id='f2-http-trace')
s=ConversationCatalogStore();c=s.create('f2-http-restart','f2-http-session','f2-http-trace');s.close()
print(json.dumps({'headers':h,'conversation':c['conversation_id']}))
"""))
py(GATEWAY,"""
import sys,json
from app import main
v=json.load(sys.stdin);h=v['headers']
s=main.ProductSession(conversation_id=v['conversation'],session_id=h['x-byq-session-id'],trace_id=h['x-byq-trace-id'],
 principal=main.Principal(subject=h['x-byq-owner-principal']),workspace_id=h['x-byq-workspace-id'])
main.lifecycle_delivery.register(s)
""",seed)
proxy='''import json,time,urllib.request
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_POST(self):
  body=self.rfile.read(int(self.headers['Content-Length']))
  if self.path=='/v1/research/tasks':
   with open('/tmp/f2-original-posts','a') as f:f.write('original\\n')
   time.sleep(14)
  req=urllib.request.Request('http://127.0.0.1:8000'+self.path,data=body,headers=dict(self.headers),method='POST')
  with urllib.request.urlopen(req,timeout=10) as r:status,data=r.status,r.read()
  try:self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
ThreadingHTTPServer(('0.0.0.0',8201),Handler).serve_forever()
'''
run('docker','exec','-i',BACKEND,'python','-c',"import sys;open('/tmp/f2-proxy.py','w').write(sys.stdin.read())",input=proxy)
run('docker','exec','-d',BACKEND,'python','/tmp/f2-proxy.py')
time.sleep(1)
node="""
import {fetchByqResearchTaskCreate} from './dist/src/research.js';
const seed=JSON.parse(process.env.F2_SEED);
const result=await fetchByqResearchTaskCreate('http://backend:8201',{
 owner_principal:'f2-http-restart',title:'Delayed original request',objective:'Synthetic HTTP timeout recovery',
 trace_id:'f2-http-trace',idempotency_key:'f2-http-original'},(url,init)=>fetch(url,{...init,headers:{...init.headers,...seed.headers}}));
console.log(result.content[0].text);
"""
reply=json.loads(run('docker','run','--rm','--label','byq.ci.scope='+SCOPE,'--network',NET,
 '-e','F2_SEED='+json.dumps(seed),PREFIX+'mcp:latest','node','--input-type=module','-e',node))
assert reply['status']=='outcome_unknown',reply
watch=reply['submission_watch']['watch_id']
before=run('docker','inspect','-f','{{.State.StartedAt}}',GATEWAY)
run('docker','restart',GATEWAY)
after=run('docker','inspect','-f','{{.State.StartedAt}}',GATEWAY)
assert before!=after
read="""
import json,sys
from app.research import ResearchStore
v=json.load(sys.stdin);h=v['headers'];ctx={k.removeprefix('x-byq-').replace('-','_'):x for k,x in h.items()}
s=ResearchStore();print(json.dumps(s.get_submission_watch(v['watch'],trusted_context=ctx)));s.close()
"""
for _ in range(45):
    state=json.loads(py(BACKEND,read,{**seed,'watch':watch}))
    if state['status']=='confirmed':break
    time.sleep(1)
else:raise AssertionError(state)
count=py(BACKEND,"print(len(open('/tmp/f2-original-posts').readlines()))")
assert count=='1'
assert 1<state['attempts']<=8
assert run('docker','exec',GATEWAY,'printenv','BYQ_F6_EXECUTOR_ENABLED')=='0'
print(json.dumps({'result':'PASS','watch':watch,'state':state,'original_http_posts':int(count),
 'gateway_restart':{'before':before,'after':after},'f6_enabled':False,'runtime_or_provider_started':False,
 'images':{s:run('docker','image','inspect','-f','{{.Id}}',PREFIX+s+':latest') for s in ('backend','gateway','mcp')}},indent=2))
