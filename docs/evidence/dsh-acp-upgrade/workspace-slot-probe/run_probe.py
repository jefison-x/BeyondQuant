from __future__ import annotations
import json, pathlib, subprocess, time

root = pathlib.Path('/tmp/byq-acp-product-slot-probe-final-20261005')
evidence = root / 'evidence'
evidence.mkdir(exist_ok=True)
runner = 'byq-acp-product-slot-probe-final-20261005'
client = 'byq-acp-product-slot-client-final-20261005'
runner_image = 'byq-acp-product-runner:qualification-20261005-final'
client_image = 'byq-runtime-adapter-acp:qualification-20261005-slot'
expected_runner_id = 'sha256:6722c919993d35201249a0eecf80b5bda3f4be7122a356876e2493dc2f318dca'
expected_client_id = 'sha256:de094b9c628308744f3544cdebf0bf9c69838864f61c2b345b57a829d09dbe5a'

def call(args, *, timeout=20):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)

def image_id(name):
    p=call(['docker','image','inspect',name])
    if p.returncode:
        raise RuntimeError('image inspect failed: '+p.stderr.strip())
    return json.loads(p.stdout)[0]['Id']

def inspect(name):
    p=call(['docker','inspect',name])
    if p.returncode:
        return None
    x=json.loads(p.stdout)[0]
    hc=x.get('HostConfig') or {}
    cfg=x.get('Config') or {}
    return {
        'Id':x.get('Id'), 'Image':x.get('Image'),
        'State':{k:(x.get('State') or {}).get(k) for k in ('Status','Running','ExitCode','OOMKilled','Error','StartedAt','FinishedAt')},
        'ReadonlyRootfs':hc.get('ReadonlyRootfs'), 'NetworkMode':hc.get('NetworkMode'),
        'CapDrop':hc.get('CapDrop'), 'CapAdd':hc.get('CapAdd'), 'SecurityOpt':hc.get('SecurityOpt'),
        'User':cfg.get('User'), 'Mounts':[{k:m.get(k) for k in ('Type','Source','Destination','RW')} for m in x.get('Mounts',[])],
    }

def save(name, data):
    (evidence/name).write_text(data, encoding='utf-8')

rid=image_id(runner_image); cid=image_id(client_image)
save('image-identity.txt', f'runner={rid}\nclient={cid}\n')
if rid != expected_runner_id or cid != expected_client_id:
    print('IMAGE_IDENTITY=FAIL')
    print(f'runner_id={rid}')
    print(f'client_id={cid}')
    raise SystemExit(2)
print('IMAGE_IDENTITY=PASS')

run_args=['docker','run','-d','--name',runner,'--network','none','--read-only',
 '--cap-drop','ALL','--cap-add','CHOWN','--cap-add','SETGID','--cap-add','SETUID','--cap-add','KILL',
 '--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
 '--env-file',str(root/'runner.env'),
 '--mount',f'type=bind,source={root}/control,target=/run/byq-acp-product-runner',
 '--mount',f'type=bind,source={root}/state,target=/var/lib/byq/acp-product-runner-state',
 '--mount',f'type=bind,source={root}/workspace,target=/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/workspace_probe',
 '--mount',f'type=bind,source={root}/fake_mcp.py,target=/tmp/fake_mcp.py,readonly',runner_image]
p=call(run_args,timeout=30)
save('runner-start.stdout',p.stdout); save('runner-start.stderr',p.stderr)
if p.returncode:
    print('RUNNER_CONTAINER_CREATE=FAIL')
    print('stderr='+p.stderr.strip()[:500])
    raise SystemExit(3)
print('RUNNER_CONTAINER_CREATE=PASS')

ready_cmd=['docker','exec','--user','0:0',runner,'python3','-c',
 "from pathlib import Path; p=Path('/run/byq-acp-product-runner/ready'); print('READY' if p.is_file() and p.read_text(encoding='ascii')=='workspace_probe\\n' else 'WAIT')"]
ready=False
for _ in range(60):
    q=call(ready_cmd,timeout=10)
    if q.returncode==0 and q.stdout.strip()=='READY':
        ready=True; break
    st=inspect(runner)
    if st is None or not st['State']['Running']:
        break
    time.sleep(0.25)
if not ready:
    st=inspect(runner)
    save('runner-inspect-not-ready.json',json.dumps(st,indent=2,sort_keys=True)+'\n')
    logs=call(['docker','logs',runner],timeout=15)
    save('runner-logs-not-ready.stdout',logs.stdout)
    save('runner-logs-not-ready.stderr',logs.stderr)
    print('READONLY_RUNNER_READY=FAIL')
    print('container_retained_for_review=true')
    print('inspect='+str(evidence/'runner-inspect-not-ready.json'))
    print('logs='+str(evidence/'runner-logs-not-ready.stderr'))
    raise SystemExit(4)
print('READONLY_RUNNER_READY=PASS')

f=call(['docker','exec','-d',runner,'python3','/tmp/fake_mcp.py'],timeout=10)
save('fake-mcp-start.stdout',f.stdout); save('fake-mcp-start.stderr',f.stderr)
if f.returncode:
    print('LOCAL_SYNTHETIC_MCP_START=FAIL')
    raise SystemExit(5)
probe_mcp=['docker','exec',runner,'python3','-c',
 "import socket; s=socket.create_connection(('127.0.0.1',18300),timeout=2); s.close(); print('MCP_READY')"]
for _ in range(20):
    q=call(probe_mcp,timeout=5)
    if q.returncode==0 and q.stdout.strip()=='MCP_READY': break
    time.sleep(0.25)
else:
    print('LOCAL_SYNTHETIC_MCP_READY=FAIL')
    raise SystemExit(6)
print('LOCAL_SYNTHETIC_MCP_READY=PASS')

client_args=['docker','run','--rm','--name',client,'--network','none','--read-only',
 '--cap-drop','ALL','--security-opt','no-new-privileges:true','--user','10002:10002','--group-add','10006',
 '--workdir','/app','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777',
 '--env-file',str(root/'client.env'),
 '--mount',f'type=bind,source={root}/control,target=/run/byq-acp-product-runner',
 '--mount',f'type=bind,source={root}/workspace,target=/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/workspace_probe',
 '--mount',f'type=bind,source={root}/client_probe.py,target=/tmp/client_probe.py,readonly',
 '--entrypoint','python3',client_image,'/tmp/client_probe.py']
q=call(client_args,timeout=180)
save('client-probe.stdout',q.stdout); save('client-probe.stderr',q.stderr)
print(q.stdout,end='')
if q.returncode:
    st=inspect(runner)
    save('runner-inspect-client-failure.json',json.dumps(st,indent=2,sort_keys=True)+'\n')
    logs=call(['docker','logs',runner],timeout=15)
    save('runner-logs-client-failure.stdout',logs.stdout)
    save('runner-logs-client-failure.stderr',logs.stderr)
    print('CLIENT_PROBE=FAIL')
    print('container_retained_for_review=true')
    print('evidence='+str(evidence))
    raise SystemExit(7)
expected=('ADAPTER_UID_HOME_TMP=PASS','OFFICIAL_ACP_INITIALIZE=PASS',
          'OFFICIAL_ACP_SESSION_NEW=PASS','OFFICIAL_ACP_SESSION_CLOSE=PASS','SIGNED_EXIT_CLEANUP=PROVEN')
if not all(line in q.stdout.splitlines() for line in expected):
    print('CLIENT_PROBE=FAIL_INCOMPLETE_ASSERTIONS')
    raise SystemExit(8)
print('CLIENT_PROBE=PASS')

st=inspect(runner)
save('runner-inspect-success.json',json.dumps(st,indent=2,sort_keys=True)+'\n')
logs=call(['docker','logs',runner],timeout=15)
save('runner-logs-success.stdout',logs.stdout); save('runner-logs-success.stderr',logs.stderr)
stop=call(['docker','stop','--timeout','3',runner],timeout=15)
save('runner-stop.stdout',stop.stdout); save('runner-stop.stderr',stop.stderr)
remove=call(['docker','rm',runner],timeout=15)
save('runner-remove.stdout',remove.stdout); save('runner-remove.stderr',remove.stderr)
if stop.returncode or remove.returncode:
    print('PROBE_CONTAINER_CLEANUP=FAIL')
    print('evidence='+str(evidence))
    raise SystemExit(9)
print('PROBE_CONTAINER_CLEANUP=PASS')
print('EVIDENCE_DIR='+str(evidence))
