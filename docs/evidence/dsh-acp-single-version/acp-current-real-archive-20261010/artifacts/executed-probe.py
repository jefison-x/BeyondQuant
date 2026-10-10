import hashlib, importlib.util, json, os, resource, shutil, subprocess, sys, time, traceback
from pathlib import Path
ROOT=Path('/home/jefison/projects/.byq-worktrees/dsh-acp-single-version')
SCOPE='acp-current-real-archive-20261010-v2-6e43b1'
OUT=ROOT/'.ci-artifacts'/SCOPE
SOURCE=ROOT/'scripts/release/images.py'
SOURCE_HASH='dc68c24fd4436b0ddeee89b7e7486e8ec1894d3bcc2fb5faee37a9e257f6b783'
IMAGE_TAG='byq-acp-unified:cur-2d581097-20261010-retryfix'
IMAGE_ID='sha256:15cdf5f97009e21af50c3cfd87d2f8d42af91e8ccaa2a82d57966bc4c2fbc6f5'
CONFIG_ID='sha256:a2ba7f82b86233338f1f2a49932f52bec6325f41e9b6b7842515d74f7a132ec3'
TAGS={role:f'byq-acp-archive-proof:{SCOPE}-{role}' for role in ('adapter','product','judgment')}
ARCHIVE=OUT/'three-alias-image.tar'
def hashfile(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()
def run(*args):
 p=subprocess.run(args,capture_output=True,text=True)
 if p.returncode: raise RuntimeError(f'command failed ({p.returncode}): {args!r}: {p.stderr[:600]}')
 return p.stdout
def image(ref):
 d=json.loads(run('docker','image','inspect',ref));assert len(d)==1
 return d[0]
def absent(ref):
 p=subprocess.run(['docker','image','inspect',ref],capture_output=True,text=True)
 if p.returncode==0:return False
 if 'no such image' not in p.stderr.lower():raise RuntimeError('cannot prove tag absence: '+p.stderr[:600])
 return True
def snapshot():
 ids=run('docker','ps','-aq','--no-trunc').splitlines()
 rows=json.loads(run('docker','container','inspect',*ids)) if ids else []
 containers={d['Id']:{'name':d['Name'],'image':d['Image'],'running':d['State']['Running'],
  'status':d['State']['Status'],'exit_code':d['State']['ExitCode'],'oom':d['State']['OOMKilled'],
  'health':d['State'].get('Health',{}).get('Status'),'restart_count':d['RestartCount']} for d in rows}
 support=json.loads((ROOT/'.ci-artifacts/acpunified-20261010-c42f17/retained-batch-images.json').read_text())['images']
 assert len(support)==14
 inspected=json.loads(run('docker','image','inspect',IMAGE_TAG,*[x['tag'] for x in support.values()]))
 ids_by_ref={IMAGE_TAG:inspected[0]['Id']}
 for (service,item),d in zip(support.items(),inspected[1:]):
  assert d['Id']==item['image_id'],service
  ids_by_ref[item['tag']]=d['Id']
 assert ids_by_ref[IMAGE_TAG]==IMAGE_ID
 return {'containers':containers,'preserved_image_tags':ids_by_ref,
         'container_count':len(containers),'running_count':sum(x['running'] for x in containers.values()),
         'available_bytes':shutil.disk_usage(ROOT).free}
def inputs():
 old=json.loads((ROOT/'.ci-artifacts/acp-unified-retry-buildkit-20261010/source-before.json').read_text())
 now={k:hashfile(ROOT/k) for k in old}
 assert len(now)==91 and now==old,'current image source inputs changed'
 return now
os.chdir(ROOT)
assert SOURCE.is_file() and hashfile(SOURCE)==SOURCE_HASH
assert not OUT.exists() and OUT.resolve()==OUT
assert shutil.disk_usage(ROOT).free>3*1024**3
for tag in TAGS.values():assert absent(tag),tag
OUT.mkdir()
receipt={'schema':'acp-current-source-real-three-alias-archive.v1','status':'RUNNING',
 'scope':'Actual current Ubuntu containerd image save and final-source parser/source binding only; not images.export or publication',
 'source_file':str(SOURCE),'source_sha256_before':hashfile(SOURCE),'head':run('git','rev-parse','HEAD').strip(),
 'image_tag':IMAGE_TAG,'expected_manifest_id':IMAGE_ID,'expected_config_id':CONFIG_ID,
 'aliases':TAGS,'script_sha256':hashfile(Path(__file__)),
 'forbidden_actions':['build','container start','load','publish','network','provider','F6','daemon configuration','prune','volume deletion'],
 'docker_mutations_allowed':['three new scope aliases','exact non-force removal of owned aliases']}
created=[];error=None;cleanup=[];before=None;start=time.monotonic()
try:
 receipt['before']=before=snapshot(); receipt['image_inputs_before']=inputs()
 receipt['docker_server_version']=json.loads(run('docker','version','--format','{{json .Server}}'))
 receipt['docker_driver_status']=json.loads(run('docker','info','--format','{{json .DriverStatus}}'))
 receipt['disk_filesystem_device']=os.stat(OUT).st_dev
 sys.dont_write_bytecode=True
 spec=importlib.util.spec_from_file_location('acp_final_release_images',SOURCE);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 inspection=mod._inspect_local_image(IMAGE_TAG)
 assert inspection['id']==IMAGE_ID and inspection['descriptor_digest']==IMAGE_ID
 for tag in TAGS.values():
  created.append(tag);run('docker','tag',IMAGE_ID,tag)
  assert image(tag)['Id']==IMAGE_ID
 save_start=time.monotonic();run('docker','save','-o',str(ARCHIVE),*TAGS.values())
 receipt['archive']={'path':str(ARCHIVE),'size_bytes':ARCHIVE.stat().st_size,'sha256':hashfile(ARCHIVE),
  'save_elapsed_seconds':round(time.monotonic()-save_start,3),'hash_chunk_bytes':1024*1024}
 assert 0<ARCHIVE.stat().st_size<2*1024**3
 parse_start=time.monotonic()
 bindings=mod.inspect_image_archive(ARCHIVE,{tag:IMAGE_ID for tag in TAGS.values()})
 assert set(bindings)==set(TAGS.values())
 for tag,binding in bindings.items():
  assert binding['format']=='oci' and binding['image_id']==CONFIG_ID and binding['manifest_digest']==IMAGE_ID
  assert binding['os']=='linux' and binding['architecture']=='amd64'
  assert len(binding['layer_digests'])==len(binding['layer_sizes'])==len(binding['rootfs_diff_ids'])==28
  assert binding['rootfs_diff_ids']==inspection['rootfs_diff_ids']
  mod._verify_local_image_binding(mod._inspect_local_image(tag),binding,captured_id=IMAGE_ID,source=True)
 assert len({json.dumps(x,sort_keys=True) for x in bindings.values()})==1
 receipt['bindings_by_tag']=bindings
 receipt['parser_elapsed_seconds']=round(time.monotonic()-parse_start,3)
 receipt['max_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
 receipt['identity_checks']={'tags':3,'unique_images':1,'ordered_layers':28,'canonical_config':CONFIG_ID,
  'captured_manifest':IMAGE_ID,'source_inspection_and_archive':'PASS','all_three_bindings_equal':True,
  'docker_load':'NOT_RUN','full_17_service_export':'NOT_RUN','registry_attestation':'NOT_RUN'}
 receipt['status']='PASS'
except Exception as exc:
 error=f'{type(exc).__name__}: {exc}';receipt['status']='FAIL';receipt['error']=error
 receipt['traceback']=traceback.format_exc(limit=6)
finally:
 cleanup_errors=[];archive_receipt_durable=False
 def cleanup_error(stage,exc):
  cleanup_errors.append({'stage':stage,'error':f'{type(exc).__name__}: {exc}'})
  receipt['status']='FAIL'
 # An unreadable archive or unwritable receipt must not block alias cleanup.
 try:
  if ARCHIVE.exists() and 'archive' not in receipt:
   receipt['archive']={'path':str(ARCHIVE),'size_bytes':ARCHIVE.stat().st_size,'sha256':hashfile(ARCHIVE),'partial_or_failed':True}
  with (OUT/'proof-before-cleanup.json').open('w') as stream:
   stream.write(json.dumps(receipt,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
  dir_fd=os.open(OUT,os.O_RDONLY|os.O_DIRECTORY)
  try: os.fsync(dir_fd)
  finally: os.close(dir_fd)
  archive_receipt_durable='archive' in receipt and 'sha256' in receipt['archive']
 except Exception as exc: cleanup_error('pre-cleanup-receipt',exc)
 # All targets were proven absent before mutation. Reconcile even a failed tag command.
 for tag in reversed(list(TAGS.values())):
  try:
   if absent(tag):
    cleanup.append({'tag':tag,'verified_absent':True,'no_delete_needed':True});continue
   assert image(tag)['Id']==IMAGE_ID,'scope alias identity changed; retained'
   output=run('docker','image','rm',tag);assert absent(tag),'alias still present'
   cleanup.append({'tag':tag,'command':['docker','image','rm',tag],'exit_code':0,'verified_absent':True,'output':output.strip()})
  except Exception as exc:
   cleanup.append({'tag':tag,'error':str(exc)});cleanup_error('alias-cleanup',exc)
 # Retain the tar if its durable hash receipt could not be created.
 try:
  if ARCHIVE.exists():
   assert ARCHIVE.is_file() and not ARCHIVE.is_symlink() and ARCHIVE.parent==OUT
   if not archive_receipt_durable: raise RuntimeError('archive retained because complete hash receipt was not durably saved')
   ARCHIVE.unlink();receipt['archive_removed_after_hash_receipt']=True
 except Exception as exc: cleanup_error('archive-cleanup',exc)
 receipt['alias_cleanup']=cleanup
 try:
  receipt['image_inputs_after']=inputs();receipt['source_sha256_after']=hashfile(SOURCE)
  assert receipt['source_sha256_after']==SOURCE_HASH
  receipt['source_unchanged']=True
 except Exception as exc: cleanup_error('source-postcheck',exc)
 try:
  receipt['after']=snapshot()
  if before is not None:
   assert receipt['after']['containers']==before['containers'],'original containers changed'
   assert receipt['after']['preserved_image_tags']==before['preserved_image_tags'],'preserved images changed'
  assert all(absent(tag) for tag in TAGS.values())
  receipt['preservation_check']='PASS'
 except Exception as exc:
  receipt['preservation_check']='FAIL';receipt['preservation_error']=str(exc);cleanup_error('resource-postcheck',exc)
 receipt['cleanup_errors']=cleanup_errors
 receipt['total_elapsed_seconds']=round(time.monotonic()-start,3)
 try:
  (OUT/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
 except Exception as exc:
  cleanup_error('final-receipt',exc)
  fallback=Path('/tmp')/(SCOPE+'-fallback-result.json')
  try:
   with fallback.open('x') as stream: stream.write(json.dumps(receipt,indent=2)+'\n')
   receipt['fallback_receipt']=str(fallback)
  except Exception as fallback_exc: receipt['fallback_error']=str(fallback_exc)
 print(json.dumps({k:receipt.get(k) for k in ('status','source_sha256_before','source_sha256_after','archive','parser_elapsed_seconds','max_rss_kib','preservation_check','error','cleanup_errors','fallback_receipt','fallback_error')}))
 sys.exit(0 if receipt['status']=='PASS' else 1)
