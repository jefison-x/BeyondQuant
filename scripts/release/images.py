#!/usr/bin/env python3
"""Trusted-main image handoff and publication. No source rebuild in publish."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dsh.authoritative_version import load_authoritative_version  # noqa: E402

SERVICES = ('backend', 'gateway', 'runtime-adapter', 'mcp', 'frontend', 'data-worker',
            'backtest-worker', 'factor-worker', 'optimization-worker',
            'signal-worker', 'ml-worker', 'signal-sandbox', 'feedback-hub-relay',
            'acp-product-runner', 'acp-judgment-runner', 'mcp-acp-judgment',
            'judgment-consumer')
DSH_ROLE_SERVICES = {
    'adapter': 'runtime-adapter',
    'ordinary_runner': 'acp-product-runner',
    'judgment_runner': 'acp-judgment-runner',
}
# ADR-0110: the adapter, ordinary-runner and judgment-runner roles are one
# build and one image. A single stable tuple orders the three role services so
# the release identity can read the shared image id back from the built images.
ACP_ROLE_SERVICES = (
    'runtime-adapter', 'acp-product-runner', 'acp-judgment-runner',
)
ACP_SINGLE_IMAGE = 'single-image'
ACP_PER_ROLE_IMAGE = 'per-role-image'
ACP_ROLE_IMAGE_TOPOLOGIES = (ACP_SINGLE_IMAGE, ACP_PER_ROLE_IMAGE)
# ADR-0110: under the explicitly selected single-image topology the three ACP
# role services are one build and publish once to one candidate repository with
# one SBOM. The default per-role route never references this repository, so a
# per-role release is not silently rewritten to the unified artifact.
ACP_UNIFIED_SERVICE = 'acp-unified'
ACP_UNIFIED_REPOSITORY = f'ghcr.io/jefison-x/beyondquant/{ACP_UNIFIED_SERVICE}'
ACP_UNIFIED_SBOM = f'{ACP_UNIFIED_SERVICE}.spdx.json'
# ADR-0110: the expected release topology is derived from the checked-in Compose
# route that the release lane actually builds, never from an ambient selector.
# The operative route is compose.yml + compose.override.yml (which includes the
# three per-role ACP builds); the future single-image route is selected only by
# a Compose declaration whose three ACP services truly share one build/image.
ACP_COMPOSE_ROUTE = ('compose.yml', 'compose.override.yml')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
SCOPE = re.compile(r'[A-Za-z0-9_.-]+')
HANDOFF_V1 = 'byq-release-images.v1'
HANDOFF_V2 = 'byq-release-images.v2'
PUBLIC_MANIFEST_V2 = 'byq-release.v2'


def capture_manifest_path(scope):
    if not isinstance(scope, str) or scope in ('.', '..') or not SCOPE.fullmatch(scope):
        raise ValueError('invalid CI scope for captured image identities')
    return Path('.ci-artifacts') / scope / 'image-ids.env'


def read_captured_image_ids(path):
    captured = {}
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError('captured CI image identity manifest is missing or unreadable') from exc
    for line in lines:
        if not line or '=' not in line:
            raise ValueError('captured CI image identity manifest is malformed')
        service, image_id = line.split('=', 1)
        if service not in SERVICES or service in captured or not DIGEST.fullmatch(image_id):
            raise ValueError('captured CI image identity manifest has an invalid entry')
        captured[service] = image_id
    if set(captured) != set(SERVICES):
        raise ValueError('captured CI image identity manifest does not contain the full release batch')
    return captured


def _read_compose_document(path):
    path = Path(path)
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError(f'ACP Compose route file is unreadable: {path.name}') from exc
    try:
        import yaml
    except ImportError as exc:
        raise ValueError('Compose YAML parser is unavailable for ACP topology derivation') from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f'ACP Compose route file is malformed: {path.name}') from exc
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError('ACP Compose route file must be a mapping')
    return document


def acp_compose_route_files(compose_route=None):
    """Return the ordered absolute Compose route files for the checked-in route.

    ADR-0110: ``ACP_COMPOSE_ROUTE`` is the single checked-in authority for the
    release/CI Compose lane. The CI shell reads it through ``images.py route`` so
    the Compose build commands and the release export cannot drift apart. The
    selection is never read from the environment; a future unified route must be
    edited into ``ACP_COMPOSE_ROUTE`` and pass the topology derivation. A missing
    or unreadable route file fails closed with no fallback.
    """
    if compose_route is None:
        route = ACP_COMPOSE_ROUTE
    elif isinstance(compose_route, (str, Path)):
        route = (compose_route,)
    else:
        route = tuple(compose_route)
    files = []
    for name in route:
        path = Path(name)
        if not path.is_absolute():
            path = ROOT / path
        try:
            path = path.resolve()
        except OSError as exc:
            raise ValueError('ACP Compose route file is unresolvable') from exc
        if not path.is_file() or not os.access(path, os.R_OK):
            raise ValueError(f'ACP Compose route file is missing or unreadable: {path.name}')
        files.append(str(path))
    if not files:
        raise ValueError('ACP Compose route selection is empty')
    return files


def _compose_route(compose_files):
    """Return the ordered ``(path, document)`` chain for the selected route.

    ADR-0110: includes are followed so the derivation observes the same merged
    declarations Compose would build, not a flattened best guess.
    """
    if compose_files is None:
        compose_files = acp_compose_route_files()
    elif isinstance(compose_files, (str, Path)):
        compose_files = [compose_files]
    route = []
    pending = [Path(path) for path in compose_files]
    seen = set()
    while pending:
        path = pending.pop(0)
        try:
            path = path.resolve()
        except OSError as exc:
            raise ValueError('ACP Compose route file is unresolvable') from exc
        if path in seen:
            continue
        seen.add(path)
        document = _read_compose_document(path)
        route.append((path, document))
        includes = document.get('include', [])
        if includes is None:
            includes = []
        if not isinstance(includes, list):
            raise ValueError('ACP Compose include declaration is invalid')
        for item in includes:
            if isinstance(item, str):
                included = path.parent / item
            elif isinstance(item, dict) and isinstance(item.get('path'), str):
                included = path.parent / item['path']
            else:
                raise ValueError('ACP Compose include entry is invalid')
            pending.append(included)
    return route


def _merge_build_declaration(current, declared):
    # Compose merges ``build`` mappings key-by-key; a scalar or a missing key
    # must not erase the effective Dockerfile declared earlier in the route.
    if isinstance(declared, str):
        return {'context': declared}
    if not isinstance(declared, dict):
        return current
    if isinstance(current, dict):
        merged = dict(current)
        merged.update(declared)
        return merged
    return dict(declared)


def acp_image_topology_from_compose(compose_files=None):
    """Derive the expected ACP topology from the selected Compose declaration.

    ADR-0110: the expected topology is read from the actual checked-in Compose
    build declaration rather than an ambient selector. A route whose three ACP
    services declare one shared Dockerfile AND one shared image reference is the
    single-image route; three distinct Dockerfiles are the operative per-role
    route. Any partial or inconsistent declaration fails closed, and equal local
    image ids alone never select single-image.
    """
    builds = {service: None for service in ACP_ROLE_SERVICES}
    images = {service: None for service in ACP_ROLE_SERVICES}
    for _path, document in _compose_route(compose_files):
        services = document.get('services') or {}
        if not isinstance(services, dict):
            raise ValueError('ACP Compose services declaration is invalid')
        for service in ACP_ROLE_SERVICES:
            entry = services.get(service)
            if not isinstance(entry, dict):
                continue
            if 'build' in entry:
                builds[service] = _merge_build_declaration(builds[service], entry['build'])
            if 'image' in entry:
                images[service] = entry['image']
    dockerfiles = {}
    for service in ACP_ROLE_SERVICES:
        build = builds[service]
        dockerfiles[service] = build.get('dockerfile') if isinstance(build, dict) else None
    if any(value is None for value in dockerfiles.values()):
        raise ValueError('selected ACP Compose route does not declare three buildable role services')
    if len(set(dockerfiles.values())) == 1:
        if any(image is None for image in images.values()) or len(set(images.values())) != 1:
            raise ValueError('shared ACP Dockerfile must also share one image reference')
        return ACP_SINGLE_IMAGE
    if len(set(dockerfiles.values())) == len(ACP_ROLE_SERVICES):
        return ACP_PER_ROLE_IMAGE
    raise ValueError('selected ACP Compose route partially shares the role build')


def observe_acp_image_binding(image_ids):
    """Observe the three ACP roles' image binding from the built images.

    The adapter, ordinary-runner and judgment-runner image ids are read back
    from ``docker image inspect`` (never from a build arg). Three equal ids are
    the single-image shape and three distinct ids are the per-role shape; a
    partial share is neither and is rejected. This is an observation only: it
    never authorizes a topology by itself.
    """
    if not isinstance(image_ids, dict):
        raise ValueError('ACP role image identities are invalid')
    resolved: dict[str, str] = {}
    for service in ACP_ROLE_SERVICES:
        image_id = image_ids.get(service)
        if not isinstance(image_id, str) or not DIGEST.fullmatch(image_id):
            raise ValueError('ACP role image identity is missing or invalid')
        resolved[service] = image_id
    unique = set(resolved.values())
    if len(unique) == 1:
        return ACP_SINGLE_IMAGE, next(iter(unique))
    if len(unique) == len(ACP_ROLE_SERVICES):
        return ACP_PER_ROLE_IMAGE, None
    raise ValueError(
        'ACP roles must either share one image id or keep three distinct role images'
    )


def acp_image_binding(image_ids, topology):
    """Bind the observed ACP role images to an explicitly selected topology.

    A triple tag alias (all three role ids equal) is only valid when the
    single-image route was explicitly selected. Under the operative per-role
    route it fails closed, so a per-role release is never silently promoted to
    the shared-image topology.
    """
    observed, shared_image_id = observe_acp_image_binding(image_ids)
    if observed != topology:
        raise ValueError(
            'captured ACP role image ids do not match the selected '
            f'{topology} release topology'
        )
    return observed, shared_image_id


def validate_acp_topology(topology):
    if topology not in ACP_ROLE_IMAGE_TOPOLOGIES:
        raise ValueError('release ACP image topology is missing or invalid')
    return topology


def release_repository(service, topology):
    """Return the registry repository a service publishes to for a topology.

    ADR-0110: under single-image the three ACP role services resolve to the one
    unified repository; every other service and the per-role route keep the
    service-specific repository unchanged.
    """
    validate_acp_topology(topology)
    if topology == ACP_SINGLE_IMAGE and service in ACP_ROLE_SERVICES:
        return ACP_UNIFIED_REPOSITORY
    return f'ghcr.io/jefison-x/beyondquant/{service}'


def release_sbom_filename(service, topology):
    """Return the SBOM file name a service binds for a topology."""
    validate_acp_topology(topology)
    if topology == ACP_SINGLE_IMAGE and service in ACP_ROLE_SERVICES:
        return ACP_UNIFIED_SBOM
    return service + '.spdx.json'


def validate_acp_release_binding(image_ids, refs, sboms, topology):
    """Fail closed unless the published ACP binding matches the selected topology.

    ADR-0110: under the explicitly selected single-image topology all three ACP
    role services must bind the identical digest-pinned unified repository ref
    and the identical SBOM receipt. Under the operative per-role topology each
    role keeps its own service repository and SBOM. A missing, mixed or partial
    role binding is rejected in either topology, so a forged shared shape or a
    partially published batch never validates.
    """
    topology = validate_acp_topology(topology)
    observed, _shared = acp_image_binding(image_ids, topology)
    role_refs = {}
    role_sboms = {}
    for service in ACP_ROLE_SERVICES:
        reference = refs.get(service) if isinstance(refs, dict) else None
        repository = release_repository(service, topology)
        prefix = repository + '@'
        if (not isinstance(reference, str) or not reference.startswith(prefix)
                or not DIGEST.fullmatch(reference[len(prefix):])):
            raise ValueError('published ACP role reference does not match the selected topology')
        sbom = sboms.get(service) if isinstance(sboms, dict) else None
        if (not isinstance(sbom, tuple) or len(sbom) != 2
                or sbom[0] != release_sbom_filename(service, topology)
                or not isinstance(sbom[1], str) or not DIGEST.fullmatch(sbom[1])):
            raise ValueError('published ACP role SBOM does not match the selected topology')
        role_refs[service] = reference
        role_sboms[service] = sbom
    if observed == ACP_SINGLE_IMAGE:
        if len(set(role_refs.values())) != 1:
            raise ValueError('single-image ACP topology must bind one shared registry ref')
        if len(set(role_sboms.values())) != 1:
            raise ValueError('single-image ACP topology must bind one shared SBOM receipt')
    elif len(set(role_refs.values())) != len(ACP_ROLE_SERVICES):
        raise ValueError('per-role ACP topology must bind distinct role repositories')


def make_dsh_identity(selection, image_ids, topology=None):
    if not isinstance(selection, dict) or not isinstance(image_ids, dict):
        raise ValueError('authoritative ACP selection or captured images are invalid')
    if topology is None:
        topology = acp_image_topology_from_compose()
    role_versions = selection.get('roles')
    if (not isinstance(role_versions, dict)
            or set(role_versions) != set(DSH_ROLE_SERVICES)
            or selection.get('sdk_online_fallback') is not False):
        raise ValueError('authoritative ACP selection is incomplete or permits SDK fallback')
    release_id = selection.get('release_id')
    _, shared_image_id = acp_image_binding(image_ids, topology)
    roles = {}
    for role, service in DSH_ROLE_SERVICES.items():
        if role_versions[role] != release_id or service not in image_ids:
            raise ValueError('authoritative ACP role does not bind the expected image')
        roles[role] = {
            'service': service,
            'release_id': role_versions[role],
            'image_id': shared_image_id if shared_image_id is not None else image_ids[service],
        }
    identity = {
        'schema_version': 'byq-dsh-release-identity.v1',
        'release_id': release_id,
        'source_commit': selection.get('source_commit'),
        'pnpm_lock_sha256': selection.get('pnpm_lock_sha256'),
        'compatibility_family': selection.get('compatibility_family'),
        'sdk_online_fallback': False,
        'roles': roles,
    }
    validate_dsh_identity(identity, image_ids, topology)
    return identity


def validate_dsh_identity(identity, image_ids, topology=None):
    fields = {'schema_version', 'release_id', 'source_commit', 'pnpm_lock_sha256',
              'compatibility_family', 'sdk_online_fallback', 'roles'}
    if not isinstance(identity, dict) or set(identity) != fields:
        raise ValueError('invalid DSH release identity schema')
    if not isinstance(image_ids, dict):
        raise ValueError('release image identity map is invalid')
    release_id = identity['release_id']
    source_commit = identity['source_commit']
    lock_sha = identity['pnpm_lock_sha256']
    if (identity['schema_version'] != 'byq-dsh-release-identity.v1'
            or not isinstance(release_id, str)
            or not re.fullmatch(r'dsh-v[0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)(?:\.[0-9]+)?)?', release_id)
            or identity['compatibility_family'] != release_id + '-acp'
            or not isinstance(source_commit, str)
            or not re.fullmatch(r'[0-9a-f]{40}', source_commit)
            or not isinstance(lock_sha, str)
            or not re.fullmatch(r'[0-9a-f]{64}', lock_sha)
            or identity['sdk_online_fallback'] is not False):
        raise ValueError('invalid or non-ACP DSH release identity')
    roles = identity['roles']
    if not isinstance(roles, dict) or set(roles) != set(DSH_ROLE_SERVICES):
        raise ValueError('DSH identity must name exactly the three DSH roles')
    if topology is None:
        _, shared_image_id = observe_acp_image_binding(image_ids)
    else:
        _, shared_image_id = acp_image_binding(image_ids, topology)
    for role, service in DSH_ROLE_SERVICES.items():
        item = roles[role]
        expected_image_id = shared_image_id if shared_image_id is not None else image_ids[service]
        if (not isinstance(item, dict) or set(item) != {'service', 'release_id', 'image_id'}
                or item['service'] != service or item['release_id'] != release_id
                or service not in image_ids or item['image_id'] != expected_image_id
                or not DIGEST.fullmatch(item['image_id'])):
            raise ValueError('DSH role identity does not match its captured image')
    if shared_image_id is not None:
        role_ids = {roles[role]['image_id'] for role in DSH_ROLE_SERVICES}
        if role_ids != {shared_image_id}:
            raise ValueError('single-image ACP topology must bind one shared image id')
    return identity


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def checksum(path):
    with Path(path).open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def _strict_json(raw, description):
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'{description} contains duplicate JSON keys')
            value[key] = item
        return value

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{description} is invalid JSON') from exc


def _safe_archive_path(name):
    if (not isinstance(name, str) or not name or '\\' in name or name.startswith('/')
            or any(part in ('', '.', '..') for part in name.rstrip('/').split('/'))):
        raise ValueError('release image archive contains an unsafe path')
    return name.rstrip('/')


def _archive_files(archive):
    files = {}
    directories = set()
    members = archive.getmembers()
    if len(members) > 100_000:
        raise ValueError('release image archive contains too many members')
    for member in members:
        if member.isdir() and member.name in ('.', './'):
            directories.add('.')
            continue
        name = _safe_archive_path(member.name)
        if member.isdir():
            directories.add(name)
            continue
        if (not member.isfile() or member.issparse()
                or name in files or member.size < 0 or member.size > 16 * 1024**3):
            raise ValueError('release image archive contains a duplicate or unsupported member')
        files[name] = member
    return files, directories


def _archive_read(archive, member, *, limit=32 * 1024**2):
    if member.size > limit:
        raise ValueError('release image archive metadata exceeds its size limit')
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError('release image archive member is unreadable')
    with stream:
        data = stream.read(limit + 1)
    if len(data) != member.size or len(data) > limit:
        raise ValueError('release image archive member size is inconsistent')
    return data


def _archive_digest(archive, member):
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError('release image archive payload is unreadable')
    digest = hashlib.sha256()
    size = 0
    with stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    if size != member.size:
        raise ValueError('release image archive payload size is inconsistent')
    return 'sha256:' + digest.hexdigest(), size


def _archive_uncompressed_digest(archive, member, *, compressed):
    raw = archive.extractfile(member)
    if raw is None:
        raise ValueError('release image layer is unreadable')
    digest = hashlib.sha256()
    size = 0
    try:
        stream = gzip.GzipFile(fileobj=raw, mode='rb') if compressed else raw
        with stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
                if size > 16 * 1024**3:
                    raise ValueError('release image layer exceeds its uncompressed size limit')
    except (OSError, EOFError) as exc:
        raise ValueError('release image layer compression is invalid') from exc
    finally:
        raw.close()
    if not compressed and size != member.size:
        raise ValueError('release image layer size is inconsistent')
    return 'sha256:' + digest.hexdigest(), size


def _config_binding(config_bytes, *, description):
    config_digest = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
    config = _strict_json(config_bytes, description)
    rootfs = config.get('rootfs') if isinstance(config, dict) else None
    diff_ids = rootfs.get('diff_ids') if isinstance(rootfs, dict) else None
    if (not isinstance(config, dict) or config.get('architecture') != 'amd64'
            or config.get('os') != 'linux' or not isinstance(rootfs, dict)
            or rootfs.get('type') != 'layers' or not isinstance(diff_ids, list)
            or any(not isinstance(item, str) or not DIGEST.fullmatch(item) for item in diff_ids)):
        raise ValueError('release image config has an invalid platform or rootfs')
    return config_digest, config, diff_ids


def _descriptor_digest(descriptor, media_types, description):
    if (not isinstance(descriptor, dict)
            or not isinstance(descriptor.get('digest'), str)
            or not DIGEST.fullmatch(descriptor['digest'])
            or type(descriptor.get('size')) is not int or descriptor['size'] < 0
            or descriptor.get('mediaType') not in media_types):
        raise ValueError(f'{description} descriptor is invalid')
    return descriptor['digest'], descriptor['size']


def _blob_member(files, digest):
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError('release image archive has an invalid payload digest')
    name = 'blobs/sha256/' + digest.removeprefix('sha256:')
    member = files.get(name)
    if member is None:
        raise ValueError('release image archive payload is missing')
    return name, member


def _normalize_docker_tag(tag):
    """Normalize Docker's default-registry spelling to the local tag form."""
    if tag.startswith('docker.io/library/'):
        return tag.removeprefix('docker.io/library/')
    if tag.startswith('docker.io/'):
        return tag.removeprefix('docker.io/')
    return tag


def _verify_moby_v1_metadata(archive, files, payloads):
    """Allow only hash-named, bounded Moby v1 config metadata blobs."""
    metadata_ids = {}
    legacy_keys = {
        'id', 'parent', 'created', 'container', 'container_config', 'author',
        'comment', 'os', 'architecture', 'variant', 'Size', 'config', 'docker_version',
    }
    for name, member in files.items():
        if name in payloads:
            continue
        parts = name.split('/')
        if len(parts) != 3 or parts[:2] != ['blobs', 'sha256'] or not re.fullmatch(r'[0-9a-f]{64}', parts[2]):
            raise ValueError('OCI archive contains an unreferenced non-Moby payload')
        digest = 'sha256:' + parts[2]
        if member.size > 4 * 1024**2:
            raise ValueError('Moby compatibility metadata exceeds its size limit')
        actual_digest, _size = _archive_digest(archive, member)
        if actual_digest != digest:
            raise ValueError('Moby compatibility metadata filename differs from its content digest')
        data = _archive_read(archive, member, limit=4 * 1024**2)
        item = _strict_json(data, 'Moby v1 config metadata')
        if (not isinstance(item, dict) or set(item) - legacy_keys
                or not isinstance(item.get('id'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', item['id'])
                or item.get('os') != 'linux'
                or ('parent' in item and (not isinstance(item['parent'], str)
                                          or not re.fullmatch(r'[0-9a-f]{64}', item['parent'])))
                or ('container_config' in item and not isinstance(item['container_config'], dict))
                or ('config' in item and not isinstance(item['config'], dict))
                or ('created' in item and item['created'] is not None
                    and not isinstance(item['created'], str))
                or ('Size' in item and type(item['Size']) is not int)
                or any(key in item and not isinstance(item[key], str)
                       for key in ('container', 'author', 'comment', 'architecture',
                                   'variant', 'docker_version'))):
            raise ValueError('Moby v1 config metadata has an unsupported structure')
        if item['id'] in metadata_ids:
            raise ValueError('Moby v1 config metadata repeats an id')
        if len(metadata_ids) >= 4096:
            raise ValueError('Moby v1 config metadata contains too many entries')
        metadata_ids[item['id']] = item.get('parent', '')
        payloads.add(name)
    for start in metadata_ids:
        seen = set()
        node = start
        while node:
            if node in seen:
                raise ValueError('Moby v1 config metadata parent chain contains a cycle')
            seen.add(node)
            parent = metadata_ids.get(node, '')
            if parent and parent not in metadata_ids:
                raise ValueError('Moby v1 config metadata references a missing parent')
            node = parent
    return metadata_ids


def _verify_moby_repositories(archive, files, payloads, bindings_by_config):
    member = files.get('repositories')
    if member is None:
        return set()
    document = _strict_json(_archive_read(archive, member, limit=4 * 1024**2), 'Docker repositories')
    if not isinstance(document, dict):
        raise ValueError('Docker repositories metadata is invalid')
    mapped = {}
    for repository, tags in document.items():
        if not isinstance(repository, str) or not repository or not isinstance(tags, dict):
            raise ValueError('Docker repositories metadata is invalid')
        for tag, legacy_id in tags.items():
            full_tag = _normalize_docker_tag(f'{repository}:{tag}')
            if (not isinstance(tag, str) or not tag or not isinstance(legacy_id, str)
                    or not re.fullmatch(r'[0-9a-f]{64}', legacy_id) or full_tag in mapped):
                raise ValueError('Docker repositories tag mapping is invalid')
            mapped[full_tag] = legacy_id
    expected = {}
    for config_digest, binding in bindings_by_config.items():
        for tag in binding['tags']:
            expected[tag] = binding['rootfs_diff_ids'][-1].removeprefix('sha256:')
    if mapped != expected:
        raise ValueError('Docker repositories metadata differs from compatibility tags and final layers')
    payloads.add('repositories')
    return {'repositories'}


def _verify_oci_archive(archive, files, expected_tags, allow_untagged):
    layout_name, index_name = 'oci-layout', 'index.json'
    if layout_name not in files or index_name not in files:
        raise ValueError('OCI release image archive is incomplete')
    layout = _strict_json(_archive_read(archive, files[layout_name]), 'OCI layout')
    index = _strict_json(_archive_read(archive, files[index_name]), 'OCI index')
    if (layout != {'imageLayoutVersion': '1.0.0'} or not isinstance(index, dict)
            or index.get('schemaVersion') != 2 or index.get('mediaType') != 'application/vnd.oci.image.index.v1+json'
            or not isinstance(index.get('manifests'), list) or not index['manifests']):
        raise ValueError('OCI release image archive layout is invalid')
    payloads = {layout_name, index_name}
    bindings = {}
    seen_tags = set()
    seen_manifests = {}
    verified_configs = {}
    verified_layers = {}
    for descriptor in index['manifests']:
        manifest_digest, manifest_size = _descriptor_digest(
            descriptor, {'application/vnd.oci.image.manifest.v1+json'}, 'OCI manifest')
        manifest_path, manifest_member = _blob_member(files, manifest_digest)
        manifest_bytes = _archive_read(archive, manifest_member, limit=16 * 1024**2)
        if ('sha256:' + hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest
                or len(manifest_bytes) != manifest_size):
            raise ValueError('OCI manifest payload digest or size differs from its descriptor')
        payloads.add(manifest_path)
        manifest = _strict_json(manifest_bytes, 'OCI image manifest')
        if (not isinstance(manifest, dict) or manifest.get('schemaVersion') != 2
                or manifest.get('mediaType') != 'application/vnd.oci.image.manifest.v1+json'
                or not isinstance(manifest.get('layers'), list)):
            raise ValueError('OCI image manifest is invalid')
        config_digest, config_size = _descriptor_digest(
            manifest.get('config'), {'application/vnd.oci.image.config.v1+json'}, 'OCI config')
        config_path, config_member = _blob_member(files, config_digest)
        cached_config = verified_configs.get(config_digest)
        if cached_config is None:
            config_bytes = _archive_read(archive, config_member)
            actual_config, config, diff_ids = _config_binding(config_bytes, description='OCI image config')
            if actual_config != config_digest or len(config_bytes) != config_size:
                raise ValueError('OCI config payload digest or size differs from its descriptor')
            cached_config = (config, diff_ids, config_size)
            verified_configs[config_digest] = cached_config
        config, diff_ids, verified_config_size = cached_config
        if verified_config_size != config_size:
            raise ValueError('OCI config aliases disagree on descriptor size')
        actual_config = config_digest
        payloads.add(config_path)
        layers = manifest['layers']
        if len(layers) != len(diff_ids):
            raise ValueError('OCI layer count differs from config rootfs diff IDs')
        layer_bindings = []
        for layer, diff_id in zip(layers, diff_ids):
            media_type = layer.get('mediaType') if isinstance(layer, dict) else None
            layer_media_types = {
                'application/vnd.oci.image.layer.v1.tar': False,
                'application/vnd.oci.image.layer.v1.tar+gzip': True,
            }
            layer_digest, layer_size = _descriptor_digest(
                layer, set(layer_media_types), 'OCI layer')
            if layer.get('urls') not in (None, []):
                raise ValueError('OCI layer descriptor external URLs are unsupported')
            compressed = layer_media_types[media_type]
            layer_path, layer_member = _blob_member(files, layer_digest)
            cached_layer = verified_layers.get(layer_digest)
            if cached_layer is None:
                actual_digest, actual_size = _archive_digest(archive, layer_member)
                actual_diff_id, _uncompressed_size = _archive_uncompressed_digest(
                    archive, layer_member, compressed=compressed)
                cached_layer = (actual_digest, actual_size, actual_diff_id, compressed)
                verified_layers[layer_digest] = cached_layer
            actual_digest, actual_size, actual_diff_id, cached_compressed = cached_layer
            if actual_digest != layer_digest or actual_size != layer_size or actual_diff_id != diff_id:
                raise ValueError('OCI layer payload digest, size, or diff ID differs')
            if cached_compressed != compressed:
                raise ValueError('OCI layer descriptor media types conflict for a shared payload')
            payloads.add(layer_path)
            layer_bindings.append({'digest': layer_digest, 'size': layer_size,
                                   'diff_id': diff_id, 'media_type': media_type})
        annotations = descriptor.get('annotations', {})
        if not isinstance(annotations, dict):
            raise ValueError('OCI image descriptor annotations are invalid')
        ref_name = annotations.get('org.opencontainers.image.ref.name')
        image_name = annotations.get('io.containerd.image.name')
        tag = _normalize_docker_tag(image_name) if isinstance(image_name, str) else ref_name
        if (ref_name is not None and image_name is not None
                and isinstance(ref_name, str)
                and ref_name != image_name.rsplit(':', 1)[-1]):
            raise ValueError('OCI Docker tag annotations disagree')
        binding = {
            'format': 'oci', 'captured_image_id': manifest_digest,
            'image_id': actual_config, 'manifest_digest': manifest_digest,
            'layer_digests': [item['digest'] for item in layer_bindings],
            'layer_sizes': [item['size'] for item in layer_bindings],
            'layer_media_types': [item['media_type'] for item in layer_bindings],
            'rootfs_diff_ids': [item['diff_id'] for item in layer_bindings],
            'os': config['os'], 'architecture': config['architecture'],
        }
        previous = seen_manifests.get(manifest_digest)
        if previous is not None and previous != binding:
            raise ValueError('OCI image aliases disagree on image payload')
        seen_manifests[manifest_digest] = binding
        if tag is not None:
            if not isinstance(tag, str) or not tag or tag in seen_tags:
                raise ValueError('OCI image archive contains an invalid or duplicate tag')
            seen_tags.add(tag)
            bindings[tag] = binding
        elif not allow_untagged:
            raise ValueError('OCI release image archive descriptor has no release tag')
        else:
            bindings['@untagged:' + manifest_digest] = {
                'format': 'oci', 'captured_image_id': manifest_digest,
                'image_id': actual_config, 'manifest_digest': manifest_digest,
                'layer_digests': [item['digest'] for item in layer_bindings],
                'layer_sizes': [item['size'] for item in layer_bindings],
                'rootfs_diff_ids': [item['diff_id'] for item in layer_bindings],
                'os': config['os'], 'architecture': config['architecture'],
            }
    # Docker's containerd-backed `docker save` emits an OCI layout plus a
    # Docker-compatibility manifest.json. Validate that second view against the
    # same config/layer payloads and release tags; never ignore conflicting
    # compatibility metadata that the loader may consume.
    if 'manifest.json' in files:
        compatibility = _strict_json(
            _archive_read(archive, files['manifest.json']), 'Docker compatibility manifest')
        if not isinstance(compatibility, list) or len(compatibility) != len(seen_manifests):
            raise ValueError('OCI Docker compatibility manifest does not match payload count')
        compatibility_tags = set()
        seen_compat_configs = set()
        compat_bindings_by_config = {}
        parent_by_config = {}
        for entry in compatibility:
            if (not isinstance(entry, dict)
                    or set(entry) - {'Config', 'RepoTags', 'Layers', 'LayerSources', 'Parent'}
                    or not {'Config', 'RepoTags', 'Layers'} <= set(entry)
                    or not isinstance(entry.get('Config'), str)
                    or not isinstance(entry.get('Layers'), list)):
                raise ValueError('OCI Docker compatibility entry is invalid')
            config_path = _safe_archive_path(entry['Config'])
            config_member = files.get(config_path)
            if config_member is None:
                raise ValueError('OCI Docker compatibility config is missing')
            config_digest, config_bytes = _archive_digest(archive, config_member)
            if config_digest not in verified_configs or config_path != _blob_member(files, config_digest)[0]:
                raise ValueError('OCI Docker compatibility config is not an indexed OCI payload')
            if config_digest in seen_compat_configs:
                raise ValueError('OCI Docker compatibility config is duplicated')
            seen_compat_configs.add(config_digest)
            config, diff_ids, _size = verified_configs[config_digest]
            if len(entry['Layers']) != len(diff_ids):
                raise ValueError('OCI Docker compatibility layer count differs from config')
            compatibility_layer_digests = []
            compatibility_layer_sizes = []
            for layer_name, diff_id in zip(entry['Layers'], diff_ids):
                safe_layer = _safe_archive_path(layer_name)
                layer_member = files.get(safe_layer)
                if layer_member is None:
                    raise ValueError('OCI Docker compatibility layer is missing')
                layer_digest, layer_size = _archive_digest(archive, layer_member)
                if layer_digest not in verified_layers or verified_layers[layer_digest][2] != diff_id:
                    raise ValueError('OCI Docker compatibility layer is not an indexed OCI payload')
                compatibility_layer_digests.append(layer_digest)
                compatibility_layer_sizes.append(layer_size)
            layer_sources = entry.get('LayerSources', {})
            if not isinstance(layer_sources, dict):
                raise ValueError('Moby LayerSources metadata is invalid')
            for diff_id, source in layer_sources.items():
                if diff_id not in diff_ids or not isinstance(source, dict):
                    raise ValueError('Moby LayerSources references an unknown layer')
                if (set(source) - {'mediaType', 'digest', 'size', 'urls', 'annotations', 'platform'}
                        or not isinstance(source.get('mediaType'), str)
                        or not isinstance(source.get('digest'), str)
                        or not DIGEST.fullmatch(source['digest'])
                        or type(source.get('size')) is not int or source['size'] < 0
                        or source.get('urls', []) not in ([], None)
                        or ('annotations' in source and (not isinstance(source['annotations'], dict)
                            or any(not isinstance(k, str) or not isinstance(v, str)
                                   for k, v in source['annotations'].items())))
                        or ('platform' in source and not isinstance(source['platform'], dict))):
                    raise ValueError('Moby LayerSources descriptor is invalid or external')
            tags = entry.get('RepoTags')
            if tags is None:
                tags = []
            if (not isinstance(tags, list) or len(tags) != len(set(tags))
                    or any(not isinstance(tag, str) or not tag for tag in tags)):
                raise ValueError('OCI Docker compatibility tags are invalid')
            normalized_tags = [_normalize_docker_tag(tag) for tag in tags]
            if len(normalized_tags) != len(set(normalized_tags)) or compatibility_tags.intersection(normalized_tags):
                raise ValueError('OCI Docker compatibility tags are duplicated')
            if normalized_tags:
                for tag in normalized_tags:
                    indexed_binding = bindings.get(tag)
                    if (indexed_binding is None or indexed_binding['image_id'] != config_digest
                            or indexed_binding['layer_digests'] != compatibility_layer_digests
                            or indexed_binding['layer_sizes'] != compatibility_layer_sizes):
                        raise ValueError('OCI Docker compatibility tag resolves to different indexed payload')
                    layer_indices = [i for i, value in enumerate(diff_ids) if value in layer_sources]
                    for index in layer_indices:
                        source = layer_sources[diff_ids[index]]
                        if (source['digest'] != indexed_binding['layer_digests'][index]
                                or source['size'] != indexed_binding['layer_sizes'][index]
                                or source['mediaType'] != indexed_binding['layer_media_types'][index]):
                            raise ValueError('Moby LayerSources differs from indexed layer descriptors')
            else:
                matches = [binding for binding in seen_manifests.values()
                           if binding['image_id'] == config_digest
                           and binding['layer_digests'] == compatibility_layer_digests
                           and binding['layer_sizes'] == compatibility_layer_sizes]
                if len(matches) != 1:
                    raise ValueError('untagged Docker compatibility payload is ambiguous')
            parent = entry.get('Parent', '')
            if (not isinstance(parent, str)
                    or (parent and (not DIGEST.fullmatch(parent) or parent == config_digest))):
                raise ValueError('Moby image Parent metadata is invalid')
            parent_by_config[config_digest] = parent
            compat_bindings_by_config[config_digest] = {
                'tags': normalized_tags, 'rootfs_diff_ids': list(diff_ids),
            }
            compatibility_tags.update(normalized_tags)
            payloads.add(config_path)
            payloads.update(_safe_archive_path(name) for name in entry['Layers'])
        if seen_compat_configs != set(verified_configs):
            raise ValueError('OCI Docker compatibility config set differs from indexed payloads')
        if expected_tags is not None and compatibility_tags != set(expected_tags):
            raise ValueError('OCI Docker compatibility tags differ from the exact handoff tag set')
        if compatibility_tags and compatibility_tags != seen_tags:
            raise ValueError('OCI descriptor and Docker compatibility tags disagree')
        for start in parent_by_config:
            seen = set()
            node = start
            while node:
                if node in seen:
                    raise ValueError('Moby image Parent chain contains a cycle')
                seen.add(node)
                if node != start and node not in parent_by_config:
                    raise ValueError('Moby image Parent references a missing config')
                node = parent_by_config.get(node, '')
        if parent_by_config and set(parent_by_config) != set(verified_configs):
            raise ValueError('Moby image Parent metadata omits an indexed config')
        payloads.add('manifest.json')
        _verify_moby_repositories(archive, files, payloads, compat_bindings_by_config)
        _verify_moby_v1_metadata(archive, files, payloads)
    if set(files) != payloads:
        raise ValueError('OCI release image archive contains unreferenced payload files')
    if expected_tags is not None and set(bindings) != set(expected_tags):
        raise ValueError('OCI release image archive tags differ from the exact handoff tag set')
    for tag, captured_id in (expected_tags or {}).items():
        binding = bindings[tag]
        if captured_id not in (binding['captured_image_id'], binding['image_id']):
            raise ValueError(f'OCI archive manifest differs from captured image identity: {tag}')
    return bindings


def _verify_docker_save_archive(archive, files, expected_tags, allow_untagged):
    if 'manifest.json' not in files:
        raise ValueError('Docker save release image archive has no manifest.json')
    document = _strict_json(_archive_read(archive, files['manifest.json']), 'Docker save manifest')
    if not isinstance(document, list) or not document:
        raise ValueError('Docker save manifest is invalid')
    payloads = {'manifest.json'}
    bindings = {}
    for entry in document:
        if (not isinstance(entry, dict) or set(entry) != {'Config', 'RepoTags', 'Layers'}
                or not isinstance(entry.get('Config'), str) or not isinstance(entry.get('Layers'), list)):
            raise ValueError('Docker save image entry is invalid')
        config_name = _safe_archive_path(entry['Config'])
        config_member = files.get(config_name)
        if config_member is None or config_name in payloads:
            raise ValueError('Docker save config payload is missing or duplicated')
        config_bytes = _archive_read(archive, config_member)
        config_digest, config, diff_ids = _config_binding(config_bytes, description='Docker save image config')
        if config_name != config_digest.removeprefix('sha256:') + '.json':
            raise ValueError('Docker save config path does not match its content digest')
        payloads.add(config_name)
        layers = entry['Layers']
        if len(layers) != len(diff_ids):
            raise ValueError('Docker save layer count differs from config rootfs diff IDs')
        layer_digests, layer_sizes = [], []
        for layer_name, diff_id in zip(layers, diff_ids):
            safe_name = _safe_archive_path(layer_name)
            layer_member = files.get(safe_name)
            if layer_member is None:
                raise ValueError('Docker save layer payload is missing')
            actual_digest, actual_size = _archive_digest(archive, layer_member)
            if actual_digest != diff_id:
                raise ValueError('Docker save layer digest differs from config rootfs diff ID')
            payloads.add(safe_name)
            layer_digests.append(actual_digest)
            layer_sizes.append(actual_size)
        tags = entry.get('RepoTags')
        if tags is None:
            tags = []
        if (not isinstance(tags, list) or any(not isinstance(tag, str) or not tag for tag in tags)
                or len(tags) != len(set(tags))):
            raise ValueError('Docker save image tags are invalid')
        if not tags and not allow_untagged:
            raise ValueError('Docker save release image entry has no release tags')
        binding = {
            'format': 'docker-save', 'captured_image_id': config_digest,
            'image_id': config_digest, 'manifest_digest': None,
            'layer_digests': layer_digests, 'layer_sizes': layer_sizes,
            'rootfs_diff_ids': list(diff_ids), 'os': config['os'],
            'architecture': config['architecture'],
        }
        for tag in tags:
            if tag in bindings:
                raise ValueError('Docker save archive contains a duplicate tag')
            bindings[tag] = binding
        if not tags:
            bindings['@untagged:' + config_digest] = binding
    if set(files) != payloads:
        raise ValueError('Docker save release image archive contains unreferenced payload files')
    if expected_tags is not None and set(bindings) != set(expected_tags):
        raise ValueError('Docker save release image tags differ from the exact handoff tag set')
    for tag, captured_id in (expected_tags or {}).items():
        if bindings[tag]['captured_image_id'] != captured_id:
            raise ValueError(f'Docker save config differs from captured image identity: {tag}')
    return bindings


def inspect_image_archive(path, expected_tags=None, *, allow_untagged=False):
    """Verify image config/layers and return per-tag store-independent bindings.

    This parser never extracts archive members. With ``expected_tags=None`` it
    can inspect an untagged captured image for offline diagnostics; export and
    publish always pass the complete exact release tag map.
    """
    if expected_tags is not None and (not isinstance(expected_tags, dict)
            or any(not isinstance(tag, str) or not tag or not isinstance(image_id, str)
                   or not DIGEST.fullmatch(image_id) for tag, image_id in expected_tags.items())):
        raise ValueError('release image archive expected tag map is invalid')
    try:
        with tarfile.open(path, mode='r:*') as archive:
            files, _directories = _archive_files(archive)
            is_oci = 'oci-layout' in files or 'index.json' in files
            is_docker = 'manifest.json' in files
            if is_oci:
                return _verify_oci_archive(archive, files, expected_tags, allow_untagged)
            if is_docker:
                return _verify_docker_save_archive(archive, files, expected_tags, allow_untagged)
            raise ValueError('release image archive format is unsupported')
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise ValueError('release image archive is unreadable') from exc


def _inspect_local_image(ref):
    try:
        data = json.loads(command('docker', 'image', 'inspect', ref))
    except (ValueError, TypeError) as exc:
        raise ValueError('local image inspection is invalid') from exc
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError('local image inspection is ambiguous')
    inspection = data[0]
    image_id = inspection.get('Id')
    descriptor = inspection.get('Descriptor')
    descriptor_digest = descriptor.get('digest') if isinstance(descriptor, dict) else None
    rootfs = inspection.get('RootFS')
    layers = rootfs.get('Layers') if isinstance(rootfs, dict) else None
    if (not isinstance(image_id, str) or not DIGEST.fullmatch(image_id)
            or not isinstance(layers, list)
            or any(not isinstance(value, str) or not DIGEST.fullmatch(value) for value in layers)
            or inspection.get('Os') != 'linux' or inspection.get('Architecture') != 'amd64'):
        raise ValueError('local image inspection has an invalid identity or platform')
    if descriptor_digest is not None and (not isinstance(descriptor_digest, str)
            or not DIGEST.fullmatch(descriptor_digest)):
        raise ValueError('local image descriptor digest is invalid')
    return {'id': image_id, 'descriptor_digest': descriptor_digest,
            'rootfs_diff_ids': layers, 'os': inspection['Os'],
            'architecture': inspection['Architecture']}


def _verify_local_image_binding(inspection, binding, *, captured_id, source):
    if (inspection['rootfs_diff_ids'] != binding['rootfs_diff_ids']
            or inspection['os'] != binding['os']
            or inspection['architecture'] != binding['architecture']):
        raise ValueError('local image config platform or rootfs differs from verified archive')
    if source:
        if inspection['id'] != captured_id:
            raise ValueError('source image differs from captured tested image identity')
        if binding['format'] == 'oci':
            if captured_id == binding['manifest_digest']:
                if inspection['descriptor_digest'] != captured_id:
                    raise ValueError('source OCI descriptor differs from captured tested image identity')
            elif captured_id == binding['image_id']:
                if inspection['descriptor_digest'] not in (None, binding['manifest_digest']):
                    raise ValueError('classic source descriptor conflicts with verified OCI archive')
            else:
                raise ValueError('source identity is not bound to OCI manifest or config')
        elif binding['image_id'] != captured_id:
            raise ValueError('source classic image config differs from captured tested image identity')
        return
    # OCI archives carry the exact manifest bytes and digest. A classic store
    # exposes its canonical config id; a containerd store exposes the manifest
    # descriptor. Classic archives have no manifest digest, so a generated
    # containerd id cannot be accepted from matching rootfs/platform alone.
    if inspection['id'] == binding['image_id']:
        return
    if (binding['format'] == 'oci' and inspection['id'] == binding['manifest_digest']
            and inspection['descriptor_digest'] == binding['manifest_digest']):
        return
    raise ValueError('loaded image identity is not bound to the verified archive')


def read_remote_manifest(tag, image_id):
    """Read the pushed candidate tag back from the registry, fail closed.

    ADR-0110 release blocker: a local ``docker inspect`` ``RepoDigests`` entry
    only records what the local daemon learned during ``docker push``; it does
    NOT prove which digest the registry now serves for the candidate tag. The
    registry read-back is authoritative. ``docker manifest inspect --verbose``
    returns one ImageManifest with ``Ref``, an OCI descriptor, and exactly one
    schema2 or OCI payload. The Docker CLI v29 JSON uses ``Descriptor.digest``
    and lower-case ``Descriptor.platform`` fields. Missing, ambiguous or
    divergent fields fail closed before a manifest is written.
    """
    raw = command('docker', 'manifest', 'inspect', '--verbose', tag)
    try:
        remote = json.loads(raw)
    except ValueError as exc:
        raise ValueError('registry manifest read-back is not valid JSON') from exc
    if not isinstance(remote, dict):
        raise ValueError('registry returned a manifest list for a single-image candidate tag')
    if remote.get('Ref') != tag:
        raise ValueError('registry manifest Ref does not match the pushed candidate tag')
    descriptor = remote.get('Descriptor')
    digest = descriptor.get('digest') if isinstance(descriptor, dict) else None
    media_type = descriptor.get('mediaType') if isinstance(descriptor, dict) else None
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError('registry manifest descriptor digest is missing or invalid')
    schema_payload = remote.get('SchemaV2Manifest')
    oci_payload = remote.get('OCIManifest')
    if (isinstance(schema_payload, dict) == isinstance(oci_payload, dict)):
        raise ValueError('registry manifest must contain exactly one supported payload')
    payload = schema_payload if isinstance(schema_payload, dict) else oci_payload
    expected_media = ('application/vnd.docker.distribution.manifest.v2+json'
                      if payload is schema_payload else 'application/vnd.oci.image.manifest.v1+json')
    if (media_type != expected_media or payload.get('mediaType') != expected_media
            or payload.get('schemaVersion') != 2):
        raise ValueError('registry manifest descriptor and payload media types differ')
    config = payload.get('config')
    if not isinstance(config, dict) or config.get('digest') != image_id:
        raise ValueError('registry manifest config digest differs from the qualified image')
    platform = descriptor.get('platform') if isinstance(descriptor, dict) else None
    if (not isinstance(platform, dict) or platform.get('os') != 'linux'
            or platform.get('architecture') != 'amd64'):
        raise ValueError('registry manifest descriptor platform is not linux/amd64')
    if ('Digest' in remote and remote['Digest'] != digest):
        raise ValueError('registry manifest has a conflicting top-level digest')
    if ('Platform' in remote and remote['Platform'] != platform):
        raise ValueError('registry manifest has a conflicting top-level platform')
    raw_manifest = remote.get('Raw')
    if raw_manifest is not None:
        import base64
        if not isinstance(raw_manifest, str):
            raise ValueError('registry manifest raw payload is invalid')
        try:
            raw_bytes = base64.b64decode(raw_manifest, validate=True)
        except ValueError as exc:
            raise ValueError('registry manifest raw payload is invalid') from exc
        if ('sha256:' + hashlib.sha256(raw_bytes).hexdigest() != digest
                or _strict_json(raw_bytes, 'registry raw manifest') != payload):
            raise ValueError('registry raw manifest differs from its descriptor or payload')
    return digest


def trusted_main():
    if (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_REPOSITORY') != 'jefison-x/BeyondQuant'):
        raise ValueError('release publication requires official trusted-main manual dispatch')
    sha = os.environ['GITHUB_SHA']
    if not re.fullmatch('[0-9a-f]{40}', sha) or command('git', 'rev-parse', 'HEAD') != sha:
        raise ValueError('checkout differs from dispatch source')
    return sha


def validate(receipt, sha, run):
    receipt_images = receipt.get('images') if isinstance(receipt, dict) else None
    schema = receipt.get('schema') if isinstance(receipt, dict) else None
    if (not isinstance(receipt, dict)
            or set(receipt) != {'schema', 'source_sha', 'run_id', 'profile', 'images',
                                'archive_sha256', 'dsh_identity', 'acp_image_topology'}
            or schema not in (HANDOFF_V1, HANDOFF_V2) or receipt.get('source_sha') != sha
            or receipt.get('run_id') != run or receipt.get('profile') != 'full'
            or not isinstance(receipt_images, dict) or set(receipt_images) != set(SERVICES)
            or not DIGEST.fullmatch(receipt.get('archive_sha256', ''))):
        raise ValueError('release receipt does not match trusted source/run/full service set')
    topology = validate_acp_topology(receipt.get('acp_image_topology'))
    for service, item in receipt_images.items():
        if not isinstance(item, dict):
            raise ValueError('invalid release image identity')
        if schema == HANDOFF_V1:
            if (set(item) != {'tag', 'image_id'}
                    or not isinstance(item.get('image_id'), str)
                    or not DIGEST.fullmatch(item['image_id'])):
                raise ValueError('invalid classic v1 release image identity')
        else:
            binding = item.get('archive_binding')
            if (set(item) != {'tag', 'captured_image_id', 'image_id', 'archive_binding'}
                    or not isinstance(item.get('captured_image_id'), str)
                    or not DIGEST.fullmatch(item['captured_image_id'])
                    or not isinstance(item.get('image_id'), str)
                    or not DIGEST.fullmatch(item['image_id'])
                    or not isinstance(binding, dict)
                    or set(binding) != {'format', 'manifest_digest', 'layer_digests',
                                        'layer_sizes', 'rootfs_diff_ids', 'os', 'architecture'}
                    or binding.get('format') not in {'oci', 'docker-save'}
                    or (binding.get('format') == 'oci'
                        and item['captured_image_id'] not in
                        (binding.get('manifest_digest'), item['image_id']))
                    or (binding.get('format') == 'docker-save'
                        and (binding.get('manifest_digest') is not None
                             or item['captured_image_id'] != item['image_id']))
                    or not isinstance(binding.get('manifest_digest'), (str, type(None)))
                    or (isinstance(binding.get('manifest_digest'), str)
                        and not DIGEST.fullmatch(binding['manifest_digest']))
                    or binding.get('os') != 'linux' or binding.get('architecture') != 'amd64'):
                raise ValueError('invalid v2 release image/archive identity')
            layers = binding.get('layer_digests')
            sizes = binding.get('layer_sizes')
            diff_ids = binding.get('rootfs_diff_ids')
            if (not isinstance(layers, list) or not isinstance(sizes, list)
                    or not isinstance(diff_ids, list) or len(layers) != len(sizes)
                    or len(layers) != len(diff_ids)
                    or any(not isinstance(value, str) or not DIGEST.fullmatch(value)
                           for value in layers + diff_ids)
                    or any(type(value) is not int or value < 0 for value in sizes)):
                raise ValueError('invalid v2 release image layer binding')
        if item['tag'] != f'byq-release-{run}-{service}:tested':
            raise ValueError('invalid release image tag')
    validate_dsh_identity(receipt['dsh_identity'], {
        service: item['image_id'] for service, item in receipt_images.items()
    }, topology)


def export(directory, compose_files=None):
    sha = trusted_main()
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    scope = os.environ['BYQ_CI_SCOPE']
    captured = read_captured_image_ids(capture_manifest_path(scope))
    images = {}
    source_inspections = {}
    for service in SERVICES:
        source = f'byq-ci-stack-{scope}-{service}'
        inspection = _inspect_local_image(source)
        if inspection['id'] != captured[service]:
            raise ValueError(f'captured/tested image id differs from current tag: {service}')
        source_inspections[service] = inspection
        images[service] = {
            'tag': f'byq-release-{run}-{service}:tested',
            'captured_image_id': captured[service],
        }
    topology = acp_image_topology_from_compose(compose_files)
    acp_image_binding(captured, topology)
    directory.mkdir(parents=True, exist_ok=False)
    tagged = []
    try:
        for service, item in images.items():
            subprocess.run(['docker', 'tag', item['captured_image_id'], item['tag']], check=True)
            tagged.append(item['tag'])
        archive = directory / 'images.tar'
        subprocess.run(['docker', 'save', '-o', str(archive), *tagged], check=True)
        archived = inspect_image_archive(
            archive, {item['tag']: item['captured_image_id'] for item in images.values()},
        )
        for service, item in images.items():
            binding = archived[item['tag']]
            _verify_local_image_binding(
                source_inspections[service], binding,
                captured_id=item['captured_image_id'], source=True,
            )
            item['image_id'] = binding['image_id']
            item['archive_binding'] = {key: binding[key] for key in (
                'format', 'manifest_digest', 'layer_digests', 'layer_sizes',
                'rootfs_diff_ids', 'os', 'architecture')}
        canonical_ids = {service: item['image_id'] for service, item in images.items()}
        dsh_identity = make_dsh_identity(load_authoritative_version(ROOT), canonical_ids, topology)
        receipt = {'schema': HANDOFF_V2, 'source_sha': sha, 'run_id': run,
                   'profile': 'full', 'images': images, 'archive_sha256': checksum(archive),
                   'acp_image_topology': topology, 'dsh_identity': dsh_identity}
        validate(receipt, sha, run)
        (directory / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    finally:
        if tagged:
            subprocess.run(['docker', 'image', 'rm', *tagged], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def publish(directory, migration):
    sha = trusted_main()
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    receipt = json.loads((directory / 'receipt.json').read_text())
    # A failed publish job may be retried without rebuilding the successful
    # qualification job. Accept only an earlier attempt of this exact run.
    produced_run = receipt.get('run_id', '')
    match = re.fullmatch(re.escape(os.environ['GITHUB_RUN_ID']) + r'-([1-9][0-9]*)', produced_run)
    if not match or int(match[1]) > int(os.environ['GITHUB_RUN_ATTEMPT']):
        raise ValueError('handoff belongs to a different run or future attempt')
    validate(receipt, sha, produced_run)
    if checksum(directory / 'images.tar') != receipt['archive_sha256']:
        raise ValueError('archive checksum mismatch')
    handoff_schema = receipt['schema']
    expected_tags = {
        item['tag']: item['captured_image_id'] if handoff_schema == HANDOFF_V2 else item['image_id']
        for item in receipt['images'].values()
    }
    archived = inspect_image_archive(directory / 'images.tar', expected_tags)
    for service, item in receipt['images'].items():
        binding = archived[item['tag']]
        if handoff_schema == HANDOFF_V1:
            if binding['image_id'] != item['image_id']:
                raise ValueError('v1 handoff is not bound to its recorded canonical config digest')
        else:
            expected_binding = {
                'format': item['archive_binding']['format'],
                'manifest_digest': item['archive_binding']['manifest_digest'],
                'layer_digests': item['archive_binding']['layer_digests'],
                'layer_sizes': item['archive_binding']['layer_sizes'],
                'rootfs_diff_ids': item['archive_binding']['rootfs_diff_ids'],
                'os': item['archive_binding']['os'],
                'architecture': item['archive_binding']['architecture'],
            }
            actual_binding = {key: binding[key] for key in expected_binding}
            if (actual_binding != expected_binding or binding['image_id'] != item['image_id']
                    or item['captured_image_id'] not in
                    (binding['captured_image_id'], binding['image_id'])):
                raise ValueError('release archive differs from its v2 captured/config identity')
    # ADR-0110: the recorded topology must be the one the checked-in
    # ACP_COMPOSE_ROUTE actually declares. An ambient selector or a hand-edited
    # receipt can never select a different publish shape, so this is bound at the
    # actual publish step (before load or any registry write), not in a helper.
    topology = validate_acp_topology(receipt['acp_image_topology'])
    if topology != acp_image_topology_from_compose():
        raise ValueError('receipt ACP image topology does not match the checked-in Compose route')
    subprocess.run(['docker', 'load', '-i', str(directory / 'images.tar')], check=True)
    # Resolve every expected tag and store-specific ID before any public write.
    for item in receipt['images'].values():
        inspection = _inspect_local_image(item['tag'])
        _verify_local_image_binding(
            inspection, archived[item['tag']],
            captured_id=(item['captured_image_id'] if handoff_schema == HANDOFF_V2
                         else item['image_id']),
            source=False,
        )
    output = Path('release-manifest')
    output.mkdir(exist_ok=False)
    manifest = {'schema': PUBLIC_MANIFEST_V2, 'source_sha': sha, 'profile': 'full',
                'ci_url': f'https://github.com/jefison-x/BeyondQuant/actions/runs/{os.environ["GITHUB_RUN_ID"]}',
                'migration': migration, 'acp_image_topology': topology, 'images': {}, 'sbom': {},
                'dsh_identity': receipt['dsh_identity']}
    # ADR-0110: one published artifact per distinct repository+image. Under the
    # single-image topology the three ACP roles share one repository and one
    # image id, so syft and the registry push run exactly once and all three
    # manifest entries bind the identical digest-pinned ref and SBOM receipt.
    published = {}
    for service, item in receipt['images'].items():
        repository = release_repository(service, topology)
        key = (repository, item['image_id'])
        if key in published:
            ref, sbom_receipt = published[key]
            manifest['images'][service] = {'ref': ref, 'image_id': item['image_id']}
            manifest['sbom'][service] = {'file': sbom_receipt['file'],
                                         'sha256': sbom_receipt['sha256']}
            continue
        sbom = output / release_sbom_filename(service, topology)
        subprocess.run(['syft', 'docker:' + item['tag'], '-o', f'spdx-json={sbom}'], check=True)
        sbom_receipt = {'file': sbom.name, 'sha256': checksum(sbom)}
        tag = repository + f':candidate-{sha[:12]}-{run}'
        subprocess.run(['docker', 'tag', item['tag'], tag], check=True)
        subprocess.run(['docker', 'push', tag], check=True)
        # The registry digest is read back from the pushed candidate tag through
        # the remote ``docker manifest inspect --verbose`` read-back; it is
        # never derived from a build arg, the local image id or the local
        # daemon's RepoDigests.
        digest = read_remote_manifest(tag, item['image_id'])
        ref = repository + '@' + digest
        published[key] = (ref, sbom_receipt)
        manifest['images'][service] = {'ref': ref, 'image_id': item['image_id']}
        manifest['sbom'][service] = sbom_receipt
    validate_acp_release_binding(
        {service: item['image_id'] for service, item in receipt['images'].items()},
        {service: item['ref'] for service, item in manifest['images'].items()},
        {service: (item['file'], item['sha256']) for service, item in manifest['sbom'].items()},
        topology,
    )
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('route', 'export', 'publish'))
    parser.add_argument('--directory', type=Path, default=Path('.ci-artifacts/release-images'))
    parser.add_argument('--migration', choices=('none', 'forward-compatible', 'operator-required'), default='operator-required')
    args = parser.parse_args()
    if args.action == 'route':
        try:
            print('\n'.join(acp_compose_route_files()))
        except ValueError as exc:
            print(f'ACP Compose route selection failed: {exc}', file=sys.stderr)
            raise SystemExit(2)
    elif args.action == 'export':
        export(args.directory)
    else:
        publish(args.directory, args.migration)
