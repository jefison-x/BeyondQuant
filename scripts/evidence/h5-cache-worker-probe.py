"""Actual Data Worker, validated cached inputs, no provider credentials."""
import json, os, subprocess, sys, time
from sqlalchemy.engine import make_url
assert os.environ.get('BYQ_H5_EVIDENCE') == '1'
assert make_url(os.environ['BYQ_DATABASE_URL']).database == 'byq_domain_test'
sys.path.insert(0, '/app')
from app.index_snapshot_demand import index_snapshot_requirement
from app.market_readiness import MarketReadinessStore
from app.market_automation import MarketAutomationStore
ready, automation = MarketReadinessStore(), MarketAutomationStore()
_, requirement = index_snapshot_requirement('000300.SH','20260815')
assessment = ready.assess(requirement)
assert assessment['state'] == 'ready' and assessment['snapshot']['member_count'] == 300
repair = automation.request_data_repair(requirement=requirement, requested_by='h5-real-cache-worker')
assert repair['status'] == 'queued', 'probe must exercise a fresh worker claim'
process = subprocess.Popen([sys.executable, '/worker/worker.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        row = automation.get_data_repairs([repair['request_id']])[0]
        if row['status'] in {'completed','failed'}: break
        if process.poll() is not None: raise AssertionError('worker exited before receipt')
        time.sleep(0.2)
    assert row['status'] == 'completed', row['status']
    print(json.dumps({'worker':'actual-data-worker', 'state':row['status'], 'members':300,
        'requested_as_of':'20260815','provider_credentials':'not-configured','network':'internal-only'}))
finally:
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired: process.kill(); process.wait()
    ready.close(); automation.close()
