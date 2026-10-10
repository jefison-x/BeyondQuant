import copy
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/release'))
import images
import manifest

# ADR-0110: the additive single-image candidate overlay shares one Dockerfile
# and one image reference across the three ACP roles. It is not auto-loaded by
# the checked-in route; a caller selects it explicitly, as Compose would.
ACP_UNIFIED_COMPOSE_ROUTE = (
    ROOT / 'compose.yml',
    ROOT / 'compose.dsh-acp-single-image-candidate.yml',
)


def synthetic_layer():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        payload = b'byq release identity fixture\n'
        member = tarfile.TarInfo('fixture.txt')
        member.size = len(payload)
        member.mtime = 0
        member.uid = member.gid = 0
        member.uname = member.gname = ''
        archive.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def synthetic_config(service):
    layer = synthetic_layer()
    diff_id = 'sha256:' + hashlib.sha256(layer).hexdigest()
    config = {
        'architecture': 'amd64', 'os': 'linux',
        'created': '2026-01-01T00:00:00Z',
        'config': {'Labels': {'byq.release.identity.fixture': service}},
        'rootfs': {'type': 'layers', 'diff_ids': [diff_id]},
        'history': [{'created_by': 'BYQ offline release identity fixture'}],
    }
    raw = json.dumps(config, sort_keys=True, separators=(',', ':')).encode()
    return raw, diff_id, layer


def image_ids():
    ids = {service: 'sha256:' + hashlib.sha256(synthetic_config(service)[0]).hexdigest()
           for service in images.SERVICES}
    # ADR-0110 single-image topology: the three ACP role services are one build
    # and one image, so they share one verified image id (read back from the
    # built image). The other release services keep distinct identities.
    shared = ids['runtime-adapter']
    for service in images.ACP_ROLE_SERVICES:
        ids[service] = shared
    return ids


def distinct_image_ids():
    # ADR-0110 operative per-role topology: one distinct built image per role.
    return {service: 'sha256:' + hashlib.sha256(synthetic_config(service)[0]).hexdigest()
            for service in images.SERVICES}


def image_material_by_id():
    result = {}
    for service in images.SERVICES:
        raw, diff_id, layer = synthetic_config(service)
        config_id = 'sha256:' + hashlib.sha256(raw).hexdigest()
        result.setdefault(config_id, (raw, diff_id, layer))
    return result


def write_classic_archive(path, tags_to_ids):
    """Write a minimal Docker-save archive with real config/layer digests."""
    materials = image_material_by_id()
    grouped = {}
    for tag, image_id in tags_to_ids.items():
        grouped.setdefault(image_id, []).append(tag)
    entries, payloads = [], {}
    for image_id, tags in sorted(grouped.items()):
        config, diff_id, layer = materials[image_id]
        config_name = image_id.removeprefix('sha256:') + '.json'
        layer_name = 'layers/' + diff_id.removeprefix('sha256:') + '/layer.tar'
        payloads[config_name] = config
        payloads[layer_name] = layer
        entries.append({'Config': config_name, 'RepoTags': sorted(tags), 'Layers': [layer_name]})
    payloads['manifest.json'] = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    with tarfile.open(path, mode='w') as archive:
        for name, data in sorted(payloads.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = 0
            member.uid = member.gid = 0
            member.uname = member.gname = ''
            archive.addfile(member, io.BytesIO(data))


def write_receipt_archive(path, receipt):
    write_classic_archive(path, {
        item['tag']: item.get('captured_image_id', item['image_id'])
        for item in receipt['images'].values()
    })


def write_export_archive(path, run, ids):
    write_classic_archive(path, {
        f'byq-release-{run}-{service}:tested': image_id
        for service, image_id in ids.items()
    })


def write_oci_archive(path, tags_to_ids, *, corrupt_layer=False, duplicate_compat_tag=False,
                      swap_compat_tags=False, duplicate_tag_across_entries=False):
    """Write a genuine OCI layout with Docker save compatibility metadata."""
    materials = image_material_by_id()
    grouped = {}
    for tag, image_id in tags_to_ids.items():
        grouped.setdefault(image_id, []).append(tag)
    files = {
        'oci-layout': json.dumps({'imageLayoutVersion': '1.0.0'},
                                 separators=(',', ':')).encode(),
    }
    index_descriptors = []
    compat_entries = []
    manifest_ids = {}
    for image_id, tags in sorted(grouped.items()):
        config_bytes, diff_id, layer = materials[image_id]
        compressed_layer = gzip.compress(layer, mtime=0)
        config_digest = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
        layer_digest = 'sha256:' + hashlib.sha256(compressed_layer).hexdigest()
        config_path = 'blobs/sha256/' + config_digest.removeprefix('sha256:')
        layer_path = 'blobs/sha256/' + layer_digest.removeprefix('sha256:')
        files[config_path] = config_bytes
        files[layer_path] = compressed_layer
        if corrupt_layer and not index_descriptors:
            files[layer_path] = compressed_layer[:-1] + bytes([compressed_layer[-1] ^ 1])
        config_descriptor = {
            'mediaType': 'application/vnd.oci.image.config.v1+json',
            'digest': config_digest, 'size': len(config_bytes),
        }
        layer_descriptor = {
            'mediaType': 'application/vnd.oci.image.layer.v1.tar+gzip',
            'digest': layer_digest, 'size': len(compressed_layer),
        }
        manifest = {
            'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': config_descriptor, 'layers': [layer_descriptor],
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        manifest_digest = 'sha256:' + hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = 'blobs/sha256/' + manifest_digest.removeprefix('sha256:')
        files[manifest_path] = manifest_bytes
        manifest_ids[image_id] = manifest_digest
        for tag in tags:
            index_descriptors.append({
                'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'digest': manifest_digest, 'size': len(manifest_bytes),
                'annotations': {
                    'io.containerd.image.name': 'docker.io/library/' + tag,
                    'org.opencontainers.image.ref.name': tag.rsplit(':', 1)[-1],
                },
            })
        compat_tags = sorted(tags)
        if duplicate_compat_tag and compat_tags:
            compat_tags.append(compat_tags[0])
        compat_entries.append({'Config': config_path, 'RepoTags': compat_tags,
                               'Layers': [layer_path]})
    if swap_compat_tags and len(compat_entries) >= 2:
        first_tags, second_tags = compat_entries[0]['RepoTags'], compat_entries[1]['RepoTags']
        compat_entries[0]['RepoTags'], compat_entries[1]['RepoTags'] = second_tags, first_tags
    if duplicate_tag_across_entries and len(compat_entries) >= 2:
        compat_entries[1]['RepoTags'] = list(compat_entries[0]['RepoTags'])
    files['index.json'] = json.dumps({
        'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
        'manifests': index_descriptors,
    }, sort_keys=True, separators=(',', ':')).encode()
    files['manifest.json'] = json.dumps(
        compat_entries, sort_keys=True, separators=(',', ':')).encode()
    with tarfile.open(path, mode='w') as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = 0
            member.uid = member.gid = 0
            member.uname = member.gname = ''
            archive.addfile(member, io.BytesIO(data))
    return manifest_ids


def write_moby_classic_oci_archive(path, tags_to_ids, *, bad_layer_source=False,
                                   extra_unreferenced=False, missing_metadata_parent=False):
    """Model Moby v28 classic-source `docker save` dual OCI/compat layout."""
    materials = image_material_by_id()
    grouped = {}
    for tag, image_id in tags_to_ids.items():
        grouped.setdefault(image_id, []).append(tag)
    files = {'oci-layout': b'{"imageLayoutVersion":"1.0.0"}'}
    index_descriptors, compat_entries, manifest_ids = [], [], {}
    repositories = {}
    for image_id, tags in sorted(grouped.items()):
        config_bytes, diff_id, layer = materials[image_id]
        config_digest = 'sha256:' + hashlib.sha256(config_bytes).hexdigest()
        layer_digest = 'sha256:' + hashlib.sha256(layer).hexdigest()
        config_path = 'blobs/sha256/' + config_digest.removeprefix('sha256:')
        layer_path = 'blobs/sha256/' + diff_id.removeprefix('sha256:')
        files[config_path] = config_bytes
        files[layer_path] = layer
        layer_descriptor = {
            'mediaType': 'application/vnd.oci.image.layer.v1.tar',
            'digest': layer_digest, 'size': len(layer),
        }
        manifest = {
            'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {'mediaType': 'application/vnd.oci.image.config.v1+json',
                       'digest': config_digest, 'size': len(config_bytes)},
            'layers': [layer_descriptor],
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
        manifest_digest = 'sha256:' + hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = 'blobs/sha256/' + manifest_digest.removeprefix('sha256:')
        files[manifest_path] = manifest_bytes
        manifest_ids[image_id] = manifest_digest
        for tag in tags:
            index_descriptors.append({
                'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                'digest': manifest_digest, 'size': len(manifest_bytes),
                'annotations': {
                    'io.containerd.image.name': 'docker.io/library/' + tag,
                    'org.opencontainers.image.ref.name': tag.rsplit(':', 1)[-1],
                },
            })
            repository, tag_name = tag.rsplit(':', 1)
            repositories.setdefault(repository, {})[tag_name] = diff_id.removeprefix('sha256:')
        source_digest = ('sha256:' + 'f' * 64) if bad_layer_source else layer_digest
        compat_entries.append({
            'Config': config_path, 'RepoTags': sorted(tags), 'Layers': [layer_path],
            'LayerSources': {diff_id: {
                'mediaType': layer_descriptor['mediaType'],
                'digest': source_digest, 'size': len(layer),
            }},
            'Parent': '',
        })
        legacy = json.dumps({
            'id': hashlib.sha256((image_id + ':legacy').encode()).hexdigest(),
            **({'parent': 'b' * 64} if missing_metadata_parent else {}),
            'created': '2026-01-01T00:00:00Z', 'os': 'linux',
            'container_config': {}, 'config': {},
        }, sort_keys=True, separators=(',', ':')).encode()
        legacy_digest = hashlib.sha256(legacy).hexdigest()
        files['blobs/sha256/' + legacy_digest] = legacy
    files['index.json'] = json.dumps({
        'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
        'manifests': index_descriptors,
    }, sort_keys=True, separators=(',', ':')).encode()
    files['manifest.json'] = json.dumps(
        compat_entries, sort_keys=True, separators=(',', ':')).encode()
    files['repositories'] = json.dumps(
        repositories, sort_keys=True, separators=(',', ':')).encode()
    if extra_unreferenced:
        files['untrusted.bin'] = b'not Moby metadata'
    with tarfile.open(path, mode='w') as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = 0
            member.uid = member.gid = 0
            member.uname = member.gname = ''
            archive.addfile(member, io.BytesIO(data))
    return manifest_ids


def local_inspection(image_id, *, descriptor_digest=None):
    material = image_material_by_id()[image_id]
    data = {
        'Id': image_id, 'Architecture': 'amd64', 'Os': 'linux',
        'RootFS': {'Type': 'layers', 'Layers': [material[1]]},
    }
    if descriptor_digest is not None:
        data['Descriptor'] = {'digest': descriptor_digest}
    return json.dumps([data])


def manifest_fixture(ids, topology):
    images_by_service = {}
    sboms = {}
    for service in images.SERVICES:
        repository = images.release_repository(service, topology)
        images_by_service[service] = {
            'ref': repository + '@sha256:' + 'b' * 64, 'image_id': ids[service]}
        sboms[service] = {
            'file': images.release_sbom_filename(service, topology),
            'sha256': 'sha256:' + 'd' * 64}
    return {'schema': 'byq-release.v2', 'source_sha': 'a' * 40, 'profile': 'full',
            'ci_url': 'https://github.com/jefison-x/BeyondQuant/actions/runs/123', 'migration': 'none',
            'acp_image_topology': topology,
            'images': images_by_service, 'sbom': sboms,
            'dsh_identity': images.make_dsh_identity(
                images.load_authoritative_version(ROOT), ids, topology)}


def fixture():
    return manifest_fixture(image_ids(), images.ACP_SINGLE_IMAGE)


def per_role_fixture():
    return manifest_fixture(distinct_image_ids(), images.ACP_PER_ROLE_IMAGE)


def receipt_fixture(run='123-1', topology=images.ACP_SINGLE_IMAGE, ids=None):
    if ids is None:
        ids = image_ids() if topology == images.ACP_SINGLE_IMAGE else distinct_image_ids()
    return {'schema': 'byq-release-images.v1', 'source_sha': 'a' * 40, 'run_id': run,
            'profile': 'full', 'archive_sha256': 'sha256:' + 'b' * 64,
            'acp_image_topology': topology,
            'images': {s: {'tag': f'byq-release-{run}-{s}:tested', 'image_id': ids[s]}
                       for s in images.SERVICES},
            'dsh_identity': images.make_dsh_identity(
                images.load_authoritative_version(ROOT), ids, topology)}


def remote_manifest(tag, image_id, digest):
    """Model Docker CLI v29's verbose ImageManifest JSON for schema2."""
    payload = {
        'schemaVersion': 2,
        'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
        'config': {
            'mediaType': 'application/vnd.docker.container.image.v1+json',
            'size': 1520,
            'digest': image_id,
        },
        'layers': [],
    }
    return {
        'Ref': tag,
        'Descriptor': {
            'mediaType': payload['mediaType'], 'digest': digest, 'size': 1234,
            'platform': {'architecture': 'amd64', 'os': 'linux'},
        },
        'SchemaV2Manifest': payload,
    }


def repository_image_ids(receipt):
    topology = receipt['acp_image_topology']
    return {
        images.release_repository(service, topology): item['image_id']
        for service, item in receipt['images'].items()
    }


class ReleasePipelineTests(unittest.TestCase):
    def test_oci_handoff_binds_store_ids_config_layers_and_all_role_aliases(self):
        import tempfile
        ids = image_ids()
        tags = {f'byq-release-123-1-{service}:tested': ids[service]
                for service in images.ACP_ROLE_SERVICES}
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'images.tar'
            manifest_ids = write_oci_archive(archive, tags)
            expected = {tag: manifest_ids[image_id] for tag, image_id in tags.items()}
            bindings = images.inspect_image_archive(archive, expected)
            self.assertEqual(set(bindings), set(tags))
            binding = bindings[next(iter(tags))]
            self.assertEqual(binding['format'], 'oci')
            self.assertEqual(binding['image_id'], ids['runtime-adapter'])
            self.assertEqual(binding['captured_image_id'], expected[next(iter(tags))])

            # Containerd source identity binds both Docker's Id and Descriptor;
            # a classic store after OCI load exposes the canonical config ID.
            source = {
                'id': binding['manifest_digest'],
                'descriptor_digest': binding['manifest_digest'],
                'rootfs_diff_ids': binding['rootfs_diff_ids'],
                'os': 'linux', 'architecture': 'amd64',
            }
            images._verify_local_image_binding(
                source, binding, captured_id=binding['captured_image_id'], source=True)
            classic_loaded = dict(source, id=binding['image_id'], descriptor_digest=None)
            images._verify_local_image_binding(
                classic_loaded, binding, captured_id=binding['captured_image_id'], source=False)

            classic = Path(temp) / 'classic.tar'
            write_classic_archive(classic, {next(iter(tags)): ids['runtime-adapter']})
            classic_binding = images.inspect_image_archive(
                classic, {next(iter(tags)): ids['runtime-adapter']})[next(iter(tags))]
            unproven_containerd = dict(
                source, id='sha256:' + 'f' * 64, descriptor_digest='sha256:' + 'f' * 64)
            with self.assertRaisesRegex(ValueError, 'not bound'):
                images._verify_local_image_binding(
                    unproven_containerd, classic_binding,
                    captured_id=classic_binding['captured_image_id'], source=False)

    def test_oci_handoff_rejects_layer_tamper_duplicate_compat_tag_and_tag_substitution(self):
        import tempfile
        image_id = image_ids()['runtime-adapter']
        tag = 'byq-release-123-1-runtime-adapter:tested'
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'images.tar'
            captured = write_oci_archive(archive, {tag: image_id})[image_id]
            expected = {tag: captured}
            with self.assertRaises(ValueError):
                images.inspect_image_archive(archive, {tag: 'sha256:' + 'f' * 64})

            write_oci_archive(archive, {tag: image_id}, corrupt_layer=True)
            with self.assertRaisesRegex(ValueError, 'layer (payload|compression)'):
                images.inspect_image_archive(archive, expected)

            write_oci_archive(archive, {tag: image_id}, duplicate_compat_tag=True)
            with self.assertRaisesRegex(ValueError, 'tags are invalid'):
                images.inspect_image_archive(archive, expected)

    def test_oci_compatibility_view_rejects_cross_payload_and_duplicate_tag_bindings(self):
        import tempfile
        ids = distinct_image_ids()
        tags = {
            'byq-release-123-1-backend:tested': ids['backend'],
            'byq-release-123-1-gateway:tested': ids['gateway'],
        }
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'images.tar'
            captured = write_oci_archive(archive, tags)
            expected = {tag: captured[image_id] for tag, image_id in tags.items()}
            write_oci_archive(archive, tags, swap_compat_tags=True)
            with self.assertRaisesRegex(ValueError, 'different indexed payload'):
                images.inspect_image_archive(archive, expected)
            write_oci_archive(archive, tags, duplicate_tag_across_entries=True)
            with self.assertRaisesRegex(ValueError, 'duplicated'):
                images.inspect_image_archive(archive, expected)

    def test_moby_classic_archive_binds_layersource_and_rejects_unknown_payload(self):
        import tempfile
        image_id = image_ids()['backend']
        tag = 'byq-release-123-1-backend:tested'
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / 'images.tar'
            write_moby_classic_oci_archive(archive, {tag: image_id})
            self.assertEqual(images.inspect_image_archive(archive, {tag: image_id})[tag]['image_id'],
                             image_id)
            write_moby_classic_oci_archive(
                archive, {tag: image_id}, bad_layer_source=True)
            with self.assertRaisesRegex(ValueError, 'LayerSources differs'):
                images.inspect_image_archive(archive, {tag: image_id})
            write_moby_classic_oci_archive(
                archive, {tag: image_id}, extra_unreferenced=True)
            with self.assertRaisesRegex(ValueError, 'unreferenced non-Moby payload'):
                images.inspect_image_archive(archive, {tag: image_id})
            write_moby_classic_oci_archive(
                archive, {tag: image_id}, missing_metadata_parent=True)
            with self.assertRaisesRegex(ValueError, 'missing parent'):
                images.inspect_image_archive(archive, {tag: image_id})

    def test_v2_oci_export_handoff_and_publish_bind_all_17_tags_across_store_ids(self):
        import tempfile
        scope = 'release-v2-oci-e2e'
        tags_to_config = {
            f'byq-release-123-1-{service}:tested': image_ids()[service]
            for service in images.SERVICES
        }
        with tempfile.TemporaryDirectory() as temp:
            source_archive = Path(temp) / 'source.tar'
            write_moby_classic_oci_archive(source_archive, tags_to_config)
            expected_tags = dict(tags_to_config)
            self.assertEqual(len(expected_tags), 17)
            self.assertEqual(len(set(expected_tags.values())), 15)
            captured_relative = images.capture_manifest_path(scope)
            export_dir = Path(temp) / 'exported'
            original_cwd = os.getcwd()
            os.chdir(temp)
            try:
                captured_path = Path(temp) / captured_relative
                captured_path.parent.mkdir(parents=True)
                captured_path.write_text(''.join(
                    f'{service}={expected_tags[f"byq-release-123-1-{service}:tested"]}\n'
                    for service in images.SERVICES))
                def export_command(*args):
                    if args[:3] == ('docker', 'image', 'inspect'):
                        service = args[3].removeprefix(f'byq-ci-stack-{scope}-')
                        source_id = expected_tags[f'byq-release-123-1-{service}:tested']
                        binding = images.inspect_image_archive(source_archive, expected_tags)[
                            f'byq-release-123-1-{service}:tested']
                        return json.dumps([{
                            'Id': source_id,
                            'Architecture': 'amd64', 'Os': 'linux',
                            'RootFS': {'Type': 'layers', 'Layers': binding['rootfs_diff_ids']},
                        }])
                    raise AssertionError(f'unexpected export command: {args}')

                def export_run(args, **kwargs):
                    if args[1] == 'save':
                        write_moby_classic_oci_archive(
                            Path(args[args.index('-o') + 1]), tags_to_config)

                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose',
                                  return_value=images.ACP_SINGLE_IMAGE), \
                     patch.object(images, 'command', side_effect=export_command), \
                     patch.object(images.subprocess, 'run', side_effect=export_run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_CI_SCOPE': scope}):
                    images.export(export_dir, compose_files=ACP_UNIFIED_COMPOSE_ROUTE)
                receipt = json.loads((export_dir / 'receipt.json').read_text())
            finally:
                os.chdir(original_cwd)
            self.assertEqual(receipt['schema'], images.HANDOFF_V2)
            self.assertEqual(receipt['dsh_identity']['roles']['adapter']['image_id'],
                             image_ids()['runtime-adapter'])
            bindings = images.inspect_image_archive(source_archive, expected_tags)
            self.assertEqual(len(bindings), 17)
            self.assertEqual(len({b['captured_image_id'] for b in bindings.values()}), 15)
            images.validate(receipt, 'a' * 40, '123-1')
            topology = receipt['acp_image_topology']
            image_by_tag = {item['tag']: item for item in receipt['images'].values()}
            image_by_repository = repository_image_ids(receipt)

            for store in ('classic', 'containerd'):
                with self.subTest(store=store):
                    calls = []
                    def run(args, **kwargs):
                        calls.append(args)
                        if args[0] == 'syft':
                            output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                            Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

                    def command(*args):
                        if args[:3] == ('docker', 'image', 'inspect'):
                            item = image_by_tag[args[3]]
                            binding = bindings[item['tag']]
                            local_id = (binding['image_id'] if store == 'classic'
                                        else binding['captured_image_id'])
                            inspection = {
                                'Id': local_id, 'Architecture': binding['architecture'],
                                'Os': binding['os'],
                                'RootFS': {'Type': 'layers', 'Layers': binding['rootfs_diff_ids']},
                            }
                            if store == 'containerd':
                                inspection['Descriptor'] = {'digest': binding['manifest_digest']}
                            return json.dumps([inspection])
                        if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                            tag = args[4]
                            repository = tag.split(':candidate-', 1)[0]
                            return json.dumps(remote_manifest(
                                tag, image_by_repository[repository], 'sha256:' + 'e' * 64))
                        raise AssertionError(f'unexpected command: {args}')

                    previous = os.getcwd()
                    publish_cwd = Path(temp) / ('publish-' + store)
                    publish_cwd.mkdir()
                    os.chdir(publish_cwd)
                    try:
                        handoff = export_dir
                        with patch.object(images, 'trusted_main', return_value='a' * 40), \
                             patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                             patch.object(images, 'command', side_effect=command), \
                             patch.object(images.subprocess, 'run', side_effect=run), \
                             patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                            images.publish(handoff, 'none')
                        pushes = [call for call in calls if call[:2] == ['docker', 'push']]
                        syfts = [call for call in calls if call[0] == 'syft']
                        self.assertEqual(len(pushes), len(images.SERVICES) - len(images.ACP_ROLE_SERVICES) + 1)
                        self.assertEqual(len(syfts), len(pushes))
                        self.assertEqual(sum(images.ACP_UNIFIED_REPOSITORY in call[2] for call in pushes), 1)
                        published = json.loads(Path('release-manifest/manifest.json').read_text())
                        self.assertEqual({
                            item['image_id'] for item in published['dsh_identity']['roles'].values()
                        }, {bindings[image_by_tag[receipt['images']['runtime-adapter']['tag']]['tag']]['image_id']})
                    finally:
                        os.chdir(previous)

            # Store identity, descriptor identity, and runtime filesystem proof
            # are all checked after `docker load` but before SBOM or registry
            # writes. A defect in any one must leave no publish output.
            for fault in ('id', 'descriptor', 'rootfs'):
                with self.subTest(loaded_image_fault=fault):
                    calls = []
                    def run_bad(args, **kwargs):
                        calls.append(args)

                    inspected = 0
                    def command_bad(*args):
                        nonlocal inspected
                        if args[:3] == ('docker', 'image', 'inspect'):
                            item = image_by_tag[args[3]]
                            binding = bindings[item['tag']]
                            inspection = {
                                'Id': binding['captured_image_id'],
                                'Descriptor': {'digest': binding['manifest_digest']},
                                'Architecture': binding['architecture'], 'Os': binding['os'],
                                'RootFS': {'Type': 'layers', 'Layers': binding['rootfs_diff_ids']},
                            }
                            if inspected == 0:
                                if fault == 'id':
                                    inspection['Id'] = 'sha256:' + 'f' * 64
                                elif fault == 'descriptor':
                                    inspection['Descriptor']['digest'] = 'sha256:' + 'f' * 64
                                elif fault == 'rootfs':
                                    inspection['RootFS']['Layers'] = ['sha256:' + 'f' * 64]
                            inspected += 1
                            return json.dumps([inspection])
                        raise AssertionError(f'unexpected command before publication: {args}')

                    fault_cwd = Path(temp) / ('fault-' + fault)
                    fault_cwd.mkdir()
                    previous = os.getcwd()
                    os.chdir(fault_cwd)
                    try:
                        with patch.object(images, 'trusted_main', return_value='a' * 40), \
                             patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                             patch.object(images, 'command', side_effect=command_bad), \
                             patch.object(images.subprocess, 'run', side_effect=run_bad), \
                             patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                            with self.assertRaises(ValueError):
                                images.publish(export_dir, 'none')
                        self.assertTrue(any(call[:2] == ['docker', 'load'] for call in calls))
                        self.assertFalse(any(call[0] == 'syft' or call[:2] == ['docker', 'push']
                                             for call in calls))
                        self.assertFalse(Path('release-manifest').exists())
                    finally:
                        os.chdir(previous)

            # A substituted archive with a self-consistent checksum but the
            # wrong captured manifest identity is rejected before even loading.
            substitution_cwd = Path(temp) / 'archive-substitution'
            substitution_cwd.mkdir()
            bad_handoff = substitution_cwd / 'handoff'
            shutil.copytree(export_dir, bad_handoff)
            wrong_ids = distinct_image_ids()
            write_oci_archive(bad_handoff / 'images.tar', {
                item['tag']: wrong_ids[service]
                for service, item in receipt['images'].items()
            })
            bad_receipt = json.loads((bad_handoff / 'receipt.json').read_text())
            bad_receipt['archive_sha256'] = images.checksum(bad_handoff / 'images.tar')
            (bad_handoff / 'receipt.json').write_text(json.dumps(bad_receipt))
            calls = []
            previous = os.getcwd()
            os.chdir(substitution_cwd)
            try:
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images.subprocess, 'run', side_effect=lambda args, **kwargs: calls.append(args)), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    with self.assertRaises(ValueError):
                        images.publish(bad_handoff, 'none')
                self.assertFalse(any(call[0] == 'syft' or call[:2] in (
                    ['docker', 'load'], ['docker', 'push']) for call in calls))
            finally:
                os.chdir(previous)

    def test_v1_receipt_accepts_moby_archive_only_by_canonical_config_digest(self):
        import tempfile
        receipt = receipt_fixture()
        with tempfile.TemporaryDirectory() as temp:
            handoff = Path(temp) / 'handoff'
            handoff.mkdir()
            tags_to_config = {item['tag']: item['image_id']
                              for item in receipt['images'].values()}
            manifest_by_config = write_moby_classic_oci_archive(
                handoff / 'images.tar', tags_to_config)
            receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
            (handoff / 'receipt.json').write_text(json.dumps(receipt))
            topology = receipt['acp_image_topology']
            image_by_tag = {item['tag']: item['image_id'] for item in receipt['images'].values()}
            image_by_repository = repository_image_ids(receipt)

            def run(args, **kwargs):
                if args[0] == 'syft':
                    output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                    Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

            def command(*args):
                if args[:3] == ('docker', 'image', 'inspect'):
                    return local_inspection(image_by_tag[args[3]])
                if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                    tag = args[4]
                    repository = tag.split(':candidate-', 1)[0]
                    return json.dumps(remote_manifest(
                        tag, image_by_repository[repository], 'sha256:' + 'e' * 64))
                raise AssertionError(f'unexpected command: {args}')

            previous = os.getcwd()
            os.chdir(temp)
            try:
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    images.publish(handoff, 'none')
                self.assertTrue(Path('release-manifest/manifest.json').is_file())
            finally:
                os.chdir(previous)

            # A v1 receipt that substitutes the archive manifest digest for the
            # canonical config ID is rejected before Docker load.
            forged = copy.deepcopy(receipt)
            forged['images']['backend']['image_id'] = manifest_by_config[
                tags_to_config[forged['images']['backend']['tag']]]
            (handoff / 'receipt.json').write_text(json.dumps(forged))
            calls = []
            rejected_cwd = Path(temp) / 'rejected'
            rejected_cwd.mkdir()
            previous = os.getcwd()
            os.chdir(rejected_cwd)
            try:
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images.subprocess, 'run', side_effect=lambda args, **kwargs: calls.append(args)), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    with self.assertRaisesRegex(ValueError, 'canonical config digest'):
                        images.publish(handoff, 'none')
                self.assertFalse(any(call[:2] == ['docker', 'load'] or call[0] == 'syft'
                                     for call in calls))
            finally:
                os.chdir(previous)

    def test_release_covers_every_compose_application_image(self):
        required_acp = {
            'acp-product-runner', 'acp-judgment-runner',
            'mcp-acp-judgment', 'judgment-consumer',
        }
        self.assertEqual(len(images.SERVICES), 17)
        self.assertEqual(len(images.SERVICES), len(set(images.SERVICES)))
        self.assertTrue(required_acp <= set(images.SERVICES))
        self.assertNotIn('postgres', images.SERVICES)
        self.assertNotIn('feedback-publisher', images.SERVICES)
        self.assertIn('feedback-hub-relay', images.SERVICES)

    def test_release_batch_matches_default_acp_compose_config(self):
        docker = shutil.which('docker')
        if not docker:
            self.skipTest('Docker Compose is unavailable for config-only inspection')
        env = dict(os.environ)
        for key in ('BYQ_DSH_RUNTIME_DOCKERFILE', 'BYQ_DSH_COMPATIBILITY_RELEASE',
                    'BYQ_DSH_SESSION_ROOT', 'DSH_SESSION_ROOT'):
            env.pop(key, None)
        env.update({
            'COMPOSE_DISABLE_ENV_FILE': '1', 'COMPOSE_ENV_FILES': '/dev/null',
            'COMPOSE_PROFILES': '', 'COMPOSE_PROJECT_NAME': 'release-config-contract',
            'BYQ_MCP_TOKEN': 'test-only-mcp-token', 'BYQ_PRODUCT_TOKEN': 'test-only-product-token',
            'BYQ_RUNTIME_AUTHORITY_TOKEN': 'test-only-runtime-token',
            'BYQ_RUNTIME_JUDGMENT_TOKEN': 'test-only-judgment-token',
            'BYQ_ACP_PRODUCT_WORKSPACE_ID': 'workspace_test000000000000000000000000000',
            'BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET': 'test-only-product-runner-secret-000000000000000000',
            'BYQ_ACP_JUDGMENT_RUNNER_CONTROL_SECRET': 'test-only-judgment-runner-secret-000000000000000000',
            'BYQ_MCP_ACP_DISCOVERY_TOKEN': 'test-only-discovery-token-000000000000000000000000000',
            'BYQ_MCP_ACP_SIGNING_KEY': 'test-only-signing-key-000000000000000000000000000000',
            'BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY': 'test-only-judgment-signing-key-00000000000000000000',
            'BYQ_MCP_ACP_JUDGMENT_PROOF_TOKEN': 'test-only-judgment-proof-token-00000000000000000000',
            'BYQ_MCP_BACKEND_PROOF_TOKEN': 'test-only-backend-proof-token-000000000000000000000000',
            'BYQ_GATEWAY_SERVICE_TOKEN': 'test-only-gateway-token-00000000000000000000000000000',
            'BYQ_DSH_PROVIDER': 'opencode-go-chat', 'BYQ_DSH_MODEL': 'deepseek-v4.1-flash',
            'OPENCODE_API_KEY': '', 'DEEPSEEK_API_KEY': '',
        })
        command = [sys.executable, str(ROOT / 'scripts/dsh/acp_build.py'), '--', docker, 'compose',
                   '-f', str(ROOT / 'compose.yml'),
                   '-f', str(ROOT / 'compose.override.yml'),
                   'config', '--format', 'json']
        config = json.loads(subprocess.check_output(command, cwd=ROOT, env=env, text=True))
        services = config['services']
        build_services = {name for name, service in services.items() if 'build' in service}
        self.assertEqual(len(services), 18)
        self.assertEqual(set(services) - build_services, {'postgres'})
        self.assertEqual(build_services, set(images.SERVICES))

    def test_missing_durable_worker_image_or_sbom_is_rejected(self):
        for worker in ('backtest-worker', 'factor-worker', 'optimization-worker',
                       'acp-product-runner', 'acp-judgment-runner', 'mcp-acp-judgment',
                       'judgment-consumer'):
            with self.subTest(worker=worker):
                for section in ('images', 'sbom'):
                    data = fixture()
                    del data[section][worker]
                    with self.assertRaises(ValueError):
                        manifest.validate(data)
                receipt = receipt_fixture()
                del receipt['images'][worker]
                with self.assertRaises(ValueError):
                    images.validate(receipt, 'a' * 40, '123-1')

    def test_dsh_identity_binds_exactly_three_role_images_and_disallows_sdk_fallback(self):
        data = fixture()
        roles = data['dsh_identity']['roles']
        self.assertEqual(set(roles), {'adapter', 'ordinary_runner', 'judgment_runner'})
        self.assertEqual({item['service'] for item in roles.values()},
                         set(images.DSH_ROLE_SERVICES.values()))
        self.assertNotIn('dsh_identity', data['images']['backend'])
        # ADR-0110: the three roles bind the one verified ACP image id, read
        # back from the built images (not from build args).
        shared = image_ids()['runtime-adapter']
        self.assertEqual({item['image_id'] for item in roles.values()}, {shared})
        self.assertEqual(data['dsh_identity']['roles']['judgment_runner']['image_id'], shared)
        changed = copy.deepcopy(data)
        changed['dsh_identity']['roles']['adapter']['image_id'] = 'sha256:' + 'f' * 64
        with self.assertRaises(ValueError):
            manifest.validate(changed)
        changed = copy.deepcopy(data)
        changed['dsh_identity']['roles']['backend'] = {
            'service': 'backend', 'release_id': changed['dsh_identity']['release_id'],
            'image_id': changed['images']['backend']['image_id'],
        }
        with self.assertRaises(ValueError):
            manifest.validate(changed)
        changed = copy.deepcopy(data)
        changed['dsh_identity']['sdk_online_fallback'] = True
        with self.assertRaises(ValueError):
            manifest.validate(changed)

    def test_acp_image_binding_is_single_image_or_per_role_never_partial(self):
        distinct = distinct_image_ids()
        self.assertEqual(
            images.observe_acp_image_binding(distinct),
            (images.ACP_PER_ROLE_IMAGE, None))
        self.assertEqual(
            images.acp_image_binding(distinct, images.ACP_PER_ROLE_IMAGE),
            (images.ACP_PER_ROLE_IMAGE, None))
        # A per-role capture binds each role to its own service image id.
        per_role = images.make_dsh_identity(
            images.load_authoritative_version(ROOT), distinct, images.ACP_PER_ROLE_IMAGE)
        self.assertEqual(
            {role: item['image_id'] for role, item in per_role['roles'].items()},
            {role: distinct[service] for role, service in images.DSH_ROLE_SERVICES.items()},
        )
        # One shared build yields one image id bound to all three roles.
        shared = dict(distinct)
        for service in images.ACP_ROLE_SERVICES:
            shared[service] = distinct['runtime-adapter']
        self.assertEqual(
            images.observe_acp_image_binding(shared),
            (images.ACP_SINGLE_IMAGE, distinct['runtime-adapter']),
        )
        self.assertEqual(
            images.acp_image_binding(shared, images.ACP_SINGLE_IMAGE),
            (images.ACP_SINGLE_IMAGE, distinct['runtime-adapter']),
        )
        single = images.make_dsh_identity(
            images.load_authoritative_version(ROOT), shared, images.ACP_SINGLE_IMAGE)
        self.assertEqual(
            {item['image_id'] for item in single['roles'].values()},
            {distinct['runtime-adapter']},
        )
        # A triple tag alias must NOT be authorized by the equal ids alone: it
        # is only valid under an explicitly selected single-image route.
        with self.assertRaises(ValueError):
            images.acp_image_binding(shared, images.ACP_PER_ROLE_IMAGE)
        with self.assertRaises(ValueError):
            images.make_dsh_identity(
                images.load_authoritative_version(ROOT), shared, images.ACP_PER_ROLE_IMAGE)
        with self.assertRaises(ValueError):
            images.acp_image_binding(distinct, images.ACP_SINGLE_IMAGE)
        # A partial share is neither topology and must fail closed.
        partial = dict(shared)
        partial['acp-judgment-runner'] = 'sha256:' + '9' * 64
        with self.assertRaises(ValueError):
            images.observe_acp_image_binding(partial)
        with self.assertRaises(ValueError):
            images.acp_image_binding(partial, images.ACP_SINGLE_IMAGE)
        with self.assertRaises(ValueError):
            images.make_dsh_identity(
                images.load_authoritative_version(ROOT), partial)

    def test_acp_topology_is_derived_from_the_checked_in_compose_route(self):
        # The operative checked-in route declares three distinct per-role builds.
        self.assertEqual(
            images.acp_image_topology_from_compose(), images.ACP_PER_ROLE_IMAGE)
        self.assertIn('compose.dsh-acp-rc2-candidate.yml',
                      (ROOT / 'compose.override.yml').read_text())
        # The additive candidate overlay shares one Dockerfile and one image
        # reference, so deriving from that Compose declaration selects the
        # future single-image route.
        self.assertEqual(
            images.acp_image_topology_from_compose(ACP_UNIFIED_COMPOSE_ROUTE),
            images.ACP_SINGLE_IMAGE)
        # No ambient topology selector remains in the CI lane; the route is the
        # Compose declaration, not an environment variable.
        source = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertNotIn('BYQ_ACP_IMAGE_TOPOLOGY', source)

    def test_compose_route_derivation_fails_closed_on_partial_or_mismatched_build(self):
        import tempfile
        import yaml
        roles = images.ACP_ROLE_SERVICES
        shared = {
            service: {
                'build': {'context': '.', 'dockerfile': 'services/acp_unified/Dockerfile'},
                'image': 'byq-acp-unified:candidate',
            }
            for service in roles
        }
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            partial = copy.deepcopy(shared)
            partial['acp-judgment-runner']['build']['dockerfile'] = (
                'services/acp_judgment_runner/Dockerfile')
            route = temp / 'partial.yml'
            route.write_text(yaml.safe_dump({'services': partial}))
            with self.assertRaises(ValueError):
                images.acp_image_topology_from_compose([route])

            mismatched = copy.deepcopy(shared)
            mismatched['acp-product-runner']['image'] = 'byq-acp-unified:other'
            route = temp / 'mismatched.yml'
            route.write_text(yaml.safe_dump({'services': mismatched}))
            with self.assertRaises(ValueError):
                images.acp_image_topology_from_compose([route])

            route = temp / 'unified.yml'
            route.write_text(yaml.safe_dump({'services': shared}))
            self.assertEqual(
                images.acp_image_topology_from_compose([route]),
                images.ACP_SINGLE_IMAGE)

    def test_compose_route_cli_is_the_single_checked_in_selection(self):
        # ADR-0110: CI Compose commands and the release export must consume one
        # checked-in route selection. images.py owns the constant; the CLI emits
        # the ordered files; local-ci.sh must not hard-code a second copy.
        expected = [str(ROOT / 'compose.yml'), str(ROOT / 'compose.override.yml')]
        self.assertEqual(images.acp_compose_route_files(), expected)
        emitted = subprocess.check_output(
            [sys.executable, str(ROOT / 'scripts/release/images.py'), 'route'],
            cwd=ROOT, text=True).splitlines()
        self.assertEqual(emitted, expected)
        # The emitted route is exactly the route the topology derivation reads,
        # so the shared selection and the static qualification cannot drift.
        self.assertEqual(
            images.acp_image_topology_from_compose(images.acp_compose_route_files()),
            images.ACP_PER_ROLE_IMAGE)
        source = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertIn('scripts/release/images.py" route', source)
        self.assertNotIn(
            'CI_COMPOSE_FILES=("$REPO_ROOT/compose.yml" "$REPO_ROOT/compose.override.yml")',
            source,
        )

    def test_compose_route_selection_fails_closed_without_fallback(self):
        # A missing or empty checked-in route fails closed; it never silently
        # returns a fallback pair, and no ambient selector can rewrite it.
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'does-not-exist.yml'
            with self.assertRaises(ValueError):
                images.acp_compose_route_files([missing])
        with self.assertRaises(ValueError):
            images.acp_compose_route_files(())
        with patch.dict(os.environ, {'BYQ_ACP_IMAGE_TOPOLOGY': images.ACP_SINGLE_IMAGE,
                                     'COMPOSE_FILE': '/tmp/elsewhere.yml'}):
            self.assertEqual(
                images.acp_compose_route_files(),
                [str(ROOT / 'compose.yml'), str(ROOT / 'compose.override.yml')],
            )

    def test_future_unified_route_requires_explicit_selection_and_qualification(self):
        # The unified single-image route is never the default: it is selectable
        # only by naming the checked-in candidate overlay explicitly, and only
        # when that declaration statically qualifies (one shared Dockerfile and
        # one shared image reference across the three roles).
        files = images.acp_compose_route_files(ACP_UNIFIED_COMPOSE_ROUTE)
        self.assertEqual(
            files,
            [str(ROOT / 'compose.yml'),
             str(ROOT / 'compose.dsh-acp-single-image-candidate.yml')],
        )
        self.assertEqual(
            images.acp_image_topology_from_compose(files), images.ACP_SINGLE_IMAGE)
        # The default route stays per-role: no default unified promotion.
        self.assertEqual(
            images.acp_image_topology_from_compose(), images.ACP_PER_ROLE_IMAGE)

    def test_public_release_manifest_v2_rejects_v1_and_unknown_before_external_actions(self):
        import tempfile
        for topology in (images.ACP_SINGLE_IMAGE, images.ACP_PER_ROLE_IMAGE):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as temp:
                valid = manifest_fixture(
                    image_ids() if topology == images.ACP_SINGLE_IMAGE else distinct_image_ids(),
                    topology)
                self.assertEqual(valid['schema'], 'byq-release.v2')
                manifest.validate(valid)
                old_17_service_v1 = copy.deepcopy(valid)
                old_17_service_v1['schema'] = 'byq-release.v1'
                old_13_service_v1 = copy.deepcopy(old_17_service_v1)
                for service in images.SERVICES[-4:]:
                    del old_13_service_v1['images'][service]
                    del old_13_service_v1['sbom'][service]
                old_13_service_v1.pop('acp_image_topology')
                old_13_service_v1.pop('dsh_identity')
                self.assertEqual(set(old_13_service_v1), {
                    'schema', 'source_sha', 'profile', 'ci_url', 'migration', 'images', 'sbom'})
                self.assertEqual(len(old_13_service_v1['images']), 13)
                for rejected in (old_13_service_v1, old_17_service_v1,
                                 {**copy.deepcopy(valid), 'schema': 'byq-release.v99'}):
                    path = Path(temp) / 'manifest.json'
                    path.write_text(json.dumps(rejected))
                    with patch.object(manifest, 'verify_sbom_receipts') as sbom_check, \
                         patch.object(manifest.subprocess, 'run') as gh_run, \
                         patch.object(manifest.subprocess, 'check_output') as gh_api, \
                         patch.object(sys, 'argv', ['manifest.py', 'overlay', '--manifest',
                                                    str(path), '--output', str(Path(temp) / 'overlay.yml'),
                                                    '--services', 'backend']):
                        with self.assertRaisesRegex(ValueError, 'invalid release manifest'):
                            manifest.main()
                        sbom_check.assert_not_called()
                        gh_run.assert_not_called()
                        gh_api.assert_not_called()
                        self.assertFalse((Path(temp) / 'overlay.yml').exists())

    def test_digest_manifest_rejects_registry_escape_mutable_tags_and_missing_service(self):
        manifest.validate(fixture())
        for value in ('ghcr.io/attacker/backend@sha256:' + 'b' * 64,
                      'ghcr.io/jefison-x/beyondquant/backend:latest',
                      'ghcr.io/jefison-x/beyondquant/backend@sha256:short'):
            data = fixture()
            data['images']['backend']['ref'] = value
            with self.assertRaises(ValueError):
                manifest.validate(data)
        data = fixture()
        del data['images']['backend']
        with self.assertRaises(ValueError):
            manifest.validate(data)

    def test_unqualified_or_cross_repository_run_rejected(self):
        for key, value in (('profile', 'selective'), ('source_sha', 'main'),
                           ('ci_url', 'https://github.com/other/repo/actions/runs/123'),
                           ('migration', 'unknown')):
            data = fixture()
            data[key] = value
            with self.assertRaises(ValueError):
                manifest.validate(data)

    def test_untrusted_dispatch_cannot_export_or_publish(self):
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_REF': 'refs/heads/main',
                                     'GITHUB_REPOSITORY': 'jefison-x/BeyondQuant'}, clear=True):
            with self.assertRaises(ValueError):
                images.trusted_main()
        with patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/feature',
                                     'GITHUB_REPOSITORY': 'jefison-x/BeyondQuant'}, clear=True):
            with self.assertRaises(ValueError):
                images.trusted_main()

    def test_handoff_binds_source_attempt_service_and_config_digest(self):
        receipt = receipt_fixture()
        images.validate(receipt, 'a' * 40, '123-1')
        for sha, run in [('d' * 40, '123-1'), ('a' * 40, '123-2')]:
            with self.assertRaises(ValueError):
                images.validate(receipt, sha, run)
            data = copy.deepcopy(receipt)
            data['images']['backend']['tag'] = 'production-backend:latest'
            with self.assertRaises(ValueError):
                images.validate(data, 'a' * 40, '123-1')

    def test_export_binds_every_captured_immutable_id_before_archive(self):
        # The unified single-image route is selected only because the Compose
        # declaration shares one Dockerfile/image for all three ACP roles.
        import tempfile
        sha = 'a' * 40
        scope = 'release-export-contract'
        ids = image_ids()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                manifest_path = images.capture_manifest_path(scope)
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(''.join(f'{service}={ids[service]}\n' for service in images.SERVICES))
                directory = Path(temp) / 'release-images'
                calls = []

                def inspect(*args):
                    self.assertEqual(args[:3], ('docker', 'image', 'inspect'))
                    prefix = f'byq-ci-stack-{scope}-'
                    self.assertTrue(args[3].startswith(prefix))
                    return local_inspection(ids[args[3][len(prefix):]])

                def run(args, **kwargs):
                    calls.append(args)
                    if args[1] == 'save':
                        write_export_archive(
                            Path(args[args.index('-o') + 1]), '123-1', ids)

                with patch.object(images, 'trusted_main', return_value=sha), \
                     patch.object(images, 'command', side_effect=inspect), \
                     patch.object(images, 'load_authoritative_version',
                                  return_value=images.load_authoritative_version(ROOT)), \
                     patch.object(images, 'checksum', return_value='sha256:' + 'e' * 64), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_CI_SCOPE': scope,
                                             'COMPOSE_PROJECT_NAME': f'byq-ci-stack-{scope}'}):
                    images.export(directory, compose_files=ACP_UNIFIED_COMPOSE_ROUTE)
                receipt = json.loads((directory / 'receipt.json').read_text())
                images.validate(receipt, sha, '123-1')
                self.assertEqual(set(receipt['images']), set(images.SERVICES))
                self.assertTrue(all(item['captured_image_id'] == ids[name]
                                    for name, item in receipt['images'].items()))
                self.assertEqual(receipt['schema'], images.HANDOFF_V2)
                self.assertEqual(receipt['dsh_identity']['roles']['adapter']['image_id'],
                                 ids['runtime-adapter'])
                self.assertEqual(
                    {item['image_id'] for item in receipt['dsh_identity']['roles'].values()},
                    {ids['runtime-adapter']},
                    'single-image topology must bind one verified id to all three roles',
                )
                self.assertTrue(any(call[:2] == ['docker', 'save'] for call in calls))
                self.assertFalse(any('build' in call or 'bake' in call for call in calls))
            finally:
                os.chdir(previous)

    def test_export_rejects_rebuilt_tag_before_tagging_or_saving(self):
        import tempfile
        scope = 'release-export-mismatch'
        ids = image_ids()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                manifest_path = images.capture_manifest_path(scope)
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(''.join(f'{service}={ids[service]}\n' for service in images.SERVICES))
                directory = Path(temp) / 'release-images'
                calls = []
                mismatched = 'sha256:' + 'f' * 64

                def inspect(*args):
                    prefix = f'byq-ci-stack-{scope}-'
                    service = args[3][len(prefix):]
                    data = json.loads(local_inspection(ids[service]))
                    if service == 'judgment-consumer':
                        data[0]['Id'] = mismatched
                    return json.dumps(data)

                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'command', side_effect=inspect), \
                     patch.object(images.subprocess, 'run', side_effect=lambda args, **kwargs: calls.append(args)), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_CI_SCOPE': scope}):
                     with self.assertRaisesRegex(ValueError, 'differs from current tag'):
                        images.export(directory)
                self.assertFalse(directory.exists())
                self.assertEqual(calls, [])
            finally:
                os.chdir(previous)

    def test_export_rejects_aliased_ids_under_per_role_route_ignoring_ambient_selector(self):
        # ADR-0110: the operative checked-in Compose route is three per-role
        # images. An ambient BYQ_ACP_IMAGE_TOPOLOGY=single-image must NOT select
        # the topology. If a triple tag alias makes all three role ids equal
        # while the per-role route is declared, export must fail closed before
        # any tag or save, never silently promoting the release.
        import tempfile
        scope = 'release-export-triple-alias'
        ids = image_ids()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                manifest_path = images.capture_manifest_path(scope)
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(
                    ''.join(f'{service}={ids[service]}\n' for service in images.SERVICES))
                directory = Path(temp) / 'release-images'
                calls = []
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'command', side_effect=lambda *args: local_inspection(
                         ids[args[3][len(f'byq-ci-stack-{scope}-'):]])), \
                     patch.object(images.subprocess, 'run', side_effect=lambda args, **kwargs: calls.append(args)), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_CI_SCOPE': scope,
                                             'BYQ_ACP_IMAGE_TOPOLOGY': images.ACP_SINGLE_IMAGE}):
                    with self.assertRaisesRegex(ValueError, 'selected.*release topology'):
                        images.export(directory)
                self.assertFalse(directory.exists())
                self.assertEqual(calls, [])
            finally:
                os.chdir(previous)

    def test_export_accepts_all_distinct_per_role_rollback_route(self):
        # The operative three-image rollback route stays valid: three distinct
        # per-role ids under the checked-in per-role Compose route export.
        import tempfile
        sha = 'a' * 40
        scope = 'release-export-per-role'
        ids = distinct_image_ids()
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                manifest_path = images.capture_manifest_path(scope)
                manifest_path.parent.mkdir(parents=True)
                manifest_path.write_text(
                    ''.join(f'{service}={ids[service]}\n' for service in images.SERVICES))
                directory = Path(temp) / 'release-images'
                calls = []

                def inspect(*args):
                    prefix = f'byq-ci-stack-{scope}-'
                    return local_inspection(ids[args[3][len(prefix):]])

                def run(args, **kwargs):
                    calls.append(args)
                    if args[1] == 'save':
                        write_export_archive(
                            Path(args[args.index('-o') + 1]), '123-1', ids)

                with patch.object(images, 'trusted_main', return_value=sha), \
                     patch.object(images, 'command', side_effect=inspect), \
                     patch.object(images, 'checksum', return_value='sha256:' + 'e' * 64), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_CI_SCOPE': scope}):
                    images.export(directory)
                receipt = json.loads((directory / 'receipt.json').read_text())
                images.validate(receipt, sha, '123-1')
                self.assertEqual(
                    {role: item['image_id'] for role, item in receipt['dsh_identity']['roles'].items()},
                    {role: ids[service] for role, service in images.DSH_ROLE_SERVICES.items()},
                )
                self.assertTrue(any(call[:2] == ['docker', 'save'] for call in calls))
            finally:
                os.chdir(previous)

    def test_single_image_publish_loads_handoff_and_never_rebuilds(self):
        import tempfile
        receipt = receipt_fixture()
        topology = receipt['acp_image_topology']
        image_id_by_tag = {item['tag']: item['image_id'] for item in receipt['images'].values()}
        image_id_by_repository = repository_image_ids(receipt)
        digest = 'sha256:' + 'e' * 64
        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                handoff = Path(temp) / 'handoff'
                handoff.mkdir()
                write_receipt_archive(handoff / 'images.tar', receipt)
                receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
                (handoff / 'receipt.json').write_text(json.dumps(receipt))
                calls = []

                def run(args, **kwargs):
                    calls.append(args)
                    if args[0] == 'syft':
                        output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                        Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

                def command(*args):
                    if args[:3] == ('docker', 'image', 'inspect'):
                        return local_inspection(image_id_by_tag[args[3]])
                    if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                        tag = args[4]
                        repository = tag.split(':candidate-', 1)[0]
                        return json.dumps(remote_manifest(
                            tag, image_id_by_repository[repository], digest))
                    raise AssertionError(f'unexpected command: {args}')

                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    images.publish(handoff, 'none')
                output = json.loads(Path('release-manifest/manifest.json').read_text())
                manifest.validate(output)
                self.assertEqual(output['schema'], 'byq-release.v2')
                self.assertEqual(set(output['images']), set(images.SERVICES))
                self.assertEqual(set(output['sbom']), set(images.SERVICES))
                self.assertEqual(set(output['dsh_identity']['roles']),
                                 {'adapter', 'ordinary_runner', 'judgment_runner'})
                self.assertEqual(output['images']['judgment-consumer']['image_id'],
                                 receipt['images']['judgment-consumer']['image_id'])
                self.assertTrue(any(call[:2] == ['docker', 'load'] for call in calls))
                self.assertFalse(any('build' in call or 'bake' in call for call in calls))
            finally:
                os.chdir(previous)

    def _run_publish(self, receipt, digest_for, calls):
        import tempfile
        image_id_by_tag = {item['tag']: item['image_id'] for item in receipt['images'].values()}
        topology = receipt['acp_image_topology']
        image_id_by_repository = repository_image_ids(receipt)

        def run(args, **kwargs):
            calls.append(args)
            if args[0] == 'syft':
                output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

        def command(*args):
            if args[:3] == ('docker', 'image', 'inspect'):
                return local_inspection(image_id_by_tag[args[3]])
            if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                tag = args[4]
                repository = tag.split(':candidate-', 1)[0]
                return json.dumps(remote_manifest(
                    tag, image_id_by_repository[repository], digest_for(repository)))
            raise AssertionError(f'unexpected command: {args}')

        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                handoff = Path(temp) / 'handoff'
                handoff.mkdir()
                write_receipt_archive(handoff / 'images.tar', receipt)
                receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
                (handoff / 'receipt.json').write_text(json.dumps(receipt))
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    images.publish(handoff, 'none')
                output = json.loads(Path('release-manifest/manifest.json').read_text())
                self.assertEqual(output['schema'], 'byq-release.v2')
                manifest.validate(output)
                return output
            finally:
                os.chdir(previous)

    def test_single_image_publish_pushes_one_unified_artifact_and_one_sbom(self):
        # ADR-0110: the single-image topology publishes one unified artifact and
        # one SBOM, and binds all three role manifest entries to the identical
        # digest-pinned ref and one SBOM receipt.
        digest = 'sha256:' + 'e' * 64
        calls = []
        output = self._run_publish(receipt_fixture(), lambda repository: digest, calls)
        pushes = [call for call in calls if call[:2] == ['docker', 'push']]
        syfts = [call for call in calls if call[0] == 'syft']
        # One unified ACP artifact replaces the three per-role ACP pushes; every
        # non-ACP service keeps its own repository.
        self.assertEqual(len(pushes), len(images.SERVICES) - len(images.ACP_ROLE_SERVICES) + 1)
        self.assertEqual(len(syfts), len(images.SERVICES) - len(images.ACP_ROLE_SERVICES) + 1)
        acp_pushes = [call for call in pushes if images.ACP_UNIFIED_SERVICE in call[2]]
        self.assertEqual(len(acp_pushes), 1, pushes)
        self.assertEqual(
            acp_pushes[0][2],
            images.ACP_UNIFIED_REPOSITORY + ':candidate-' + 'a' * 12 + '-123-1')
        for service in images.ACP_ROLE_SERVICES:
            self.assertFalse(any(f'/beyondquant/{service}:candidate-' in call[2] for call in pushes))
        refs = {name: output['images'][name]['ref'] for name in images.ACP_ROLE_SERVICES}
        self.assertEqual(set(refs.values()), {images.ACP_UNIFIED_REPOSITORY + '@' + digest})
        sboms = {name: (output['sbom'][name]['file'], output['sbom'][name]['sha256'])
                 for name in images.ACP_ROLE_SERVICES}
        self.assertEqual({name: value[0] for name, value in sboms.items()},
                         {name: 'acp-unified.spdx.json' for name in images.ACP_ROLE_SERVICES})
        self.assertEqual(len({value[1] for value in sboms.values()}), 1)

    def test_per_role_publish_keeps_each_service_repository_and_sbom(self):
        # The operative per-role route is unchanged: every service keeps its own
        # repository and SBOM, and every one is pushed and scanned.
        digest = 'sha256:' + 'e' * 64
        calls = []
        output = self._run_publish(
            receipt_fixture(topology=images.ACP_PER_ROLE_IMAGE), lambda repository: digest, calls)
        self.assertEqual(len([c for c in calls if c[:2] == ['docker', 'push']]), len(images.SERVICES))
        self.assertEqual(len([c for c in calls if c[0] == 'syft']), len(images.SERVICES))
        for service in images.SERVICES:
            self.assertEqual(output['images'][service]['ref'],
                             f'ghcr.io/jefison-x/beyondquant/{service}@{digest}')
            self.assertEqual(output['sbom'][service]['file'], service + '.spdx.json')

    def test_manifest_rejects_forged_shared_ref_sbom_or_missing_topology(self):
        # A single-image release that binds a role to its own per-role repo, or a
        # different SBOM, or has no/unknown topology is a forged shape and must
        # fail closed.
        forged_ref = copy.deepcopy(fixture())
        forged_ref['images']['acp-judgment-runner']['ref'] = (
            'ghcr.io/jefison-x/beyondquant/acp-judgment-runner@sha256:' + 'b' * 64)
        with self.assertRaises(ValueError):
            manifest.validate(forged_ref)
        forged_sbom = copy.deepcopy(fixture())
        forged_sbom['sbom']['acp-product-runner']['file'] = 'acp-product-runner.spdx.json'
        with self.assertRaises(ValueError):
            manifest.validate(forged_sbom)
        missing = copy.deepcopy(fixture())
        missing.pop('acp_image_topology')
        with self.assertRaises(ValueError):
            manifest.validate(missing)
        unknown = fixture()
        unknown['acp_image_topology'] = 'ambient-selector'
        with self.assertRaises(ValueError):
            manifest.validate(unknown)
        per_role_forged = per_role_fixture()
        per_role_forged['images']['runtime-adapter']['ref'] = (
            images.ACP_UNIFIED_REPOSITORY + '@sha256:' + 'b' * 64)
        with self.assertRaises(ValueError):
            manifest.validate(per_role_forged)

    def test_receipt_rejects_missing_or_unknown_topology(self):
        for mutate in (
            lambda data: data.pop('acp_image_topology'),
            lambda data: data.__setitem__('acp_image_topology', 'ambient-selector'),
        ):
            data = receipt_fixture()
            mutate(data)
            with self.assertRaises(ValueError):
                images.validate(data, 'a' * 40, '123-1')

    def _run_publish_expect_failure(self, remote_for):
        import tempfile
        receipt = receipt_fixture()
        topology = receipt['acp_image_topology']
        image_id_by_tag = {item['tag']: item['image_id'] for item in receipt['images'].values()}
        image_id_by_repository = repository_image_ids(receipt)

        def run(args, **kwargs):
            if args[0] == 'syft':
                output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

        def command(*args):
            if args[:3] == ('docker', 'image', 'inspect'):
                return local_inspection(image_id_by_tag[args[3]])
            if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                tag = args[4]
                repository = tag.split(':candidate-', 1)[0]
                payload = remote_for(tag, repository, image_id_by_repository[repository])
                return payload if isinstance(payload, str) else json.dumps(payload)
            raise AssertionError(f'unexpected command: {args}')

        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                handoff = Path(temp) / 'handoff'
                handoff.mkdir()
                write_receipt_archive(handoff / 'images.tar', receipt)
                receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
                (handoff / 'receipt.json').write_text(json.dumps(receipt))
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    with self.assertRaises(ValueError):
                        images.publish(handoff, 'none')
                self.assertFalse((Path('release-manifest') / 'manifest.json').exists())
            finally:
                os.chdir(previous)

    def test_publish_fails_closed_on_divergent_or_absent_remote_manifest(self):
        # The remote ``docker manifest inspect --verbose`` read-back must be a
        # single manifest whose Ref, Digest, config digest and platform all bind
        # the qualified image. Every missing/ambiguous/wrong field writes no
        # manifest.
        digest = 'sha256:' + 'e' * 64

        def remote_missing_digest(remote, tag, image_id):
            del remote['Descriptor']['digest']
            return remote

        def remote_malformed_digest(remote, tag, image_id):
            remote['Descriptor']['digest'] = 'sha256:short'
            return remote

        def remote_wrong_config(remote, tag, image_id):
            remote['SchemaV2Manifest']['config']['digest'] = 'sha256:' + '0' * 64
            return remote

        def remote_missing_config(remote, tag, image_id):
            del remote['SchemaV2Manifest']['config']
            return remote

        def remote_wrong_ref(remote, tag, image_id):
            remote['Ref'] = tag + '@' + digest
            return remote

        def remote_wrong_platform(remote, tag, image_id):
            remote['Descriptor']['platform']['architecture'] = 'arm64'
            return remote

        def remote_wrong_os(remote, tag, image_id):
            remote['Descriptor']['platform']['os'] = 'windows'
            return remote

        def remote_list_shape(remote, tag, image_id):
            return [remote]

        def remote_not_json(remote, tag, image_id):
            return 'not json'

        cases = {
            'missing_digest': remote_missing_digest,
            'malformed_digest': remote_malformed_digest,
            'wrong_config': remote_wrong_config,
            'missing_config': remote_missing_config,
            'wrong_ref': remote_wrong_ref,
            'wrong_platform': remote_wrong_platform,
            'wrong_os': remote_wrong_os,
            'list_shape': remote_list_shape,
            'not_json': remote_not_json,
        }
        for name, transform in cases.items():
            with self.subTest(case=name):
                self._run_publish_expect_failure(
                    lambda tag, repository, image_id, transform=transform:
                    transform(remote_manifest(tag, image_id, digest), tag, image_id))

    def test_publish_uses_remote_digest_and_never_local_repo_digests(self):
        # A stale local RepoDigests entry recorded by an earlier push must never
        # influence the published manifest: the remote registry read-back governs
        # and the local RepoDigests query is not even issued.
        import tempfile
        receipt = receipt_fixture()
        topology = receipt['acp_image_topology']
        image_id_by_tag = {item['tag']: item['image_id'] for item in receipt['images'].values()}
        image_id_by_repository = repository_image_ids(receipt)
        remote_digest = 'sha256:' + 'e' * 64
        stale_digest = 'sha256:' + 'd' * 64
        queried = []

        def run(args, **kwargs):
            if args[0] == 'syft':
                output = args[args.index('-o') + 1].removeprefix('spdx-json=')
                Path(output).write_text('{"spdxVersion":"SPDX-2.3"}')

        def command(*args):
            queried.append(args)
            if args[:3] == ('docker', 'image', 'inspect'):
                if '--format' in args and 'RepoDigests' in args[args.index('--format') + 1]:
                    return json.dumps(['ghcr.io/attacker/stale@' + stale_digest])
                return local_inspection(image_id_by_tag[args[3]])
            if args[:4] == ('docker', 'manifest', 'inspect', '--verbose'):
                tag = args[4]
                repository = tag.split(':candidate-', 1)[0]
                return json.dumps(remote_manifest(
                    tag, image_id_by_repository[repository], remote_digest))
            raise AssertionError(f'unexpected command: {args}')

        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                handoff = Path(temp) / 'handoff'
                handoff.mkdir()
                write_receipt_archive(handoff / 'images.tar', receipt)
                receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
                (handoff / 'receipt.json').write_text(json.dumps(receipt))
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'acp_image_topology_from_compose', return_value=topology), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}):
                    images.publish(handoff, 'none')
                output = json.loads(Path('release-manifest/manifest.json').read_text())
                manifest.validate(output)
                self.assertFalse(any('RepoDigests' in arg for call in queried for arg in call))
                for service in images.SERVICES:
                    self.assertTrue(output['images'][service]['ref'].endswith('@' + remote_digest))
                    self.assertNotIn(stale_digest, output['images'][service]['ref'])
            finally:
                os.chdir(previous)

    def test_publish_binds_receipt_topology_to_checked_in_route_without_ambient_selector(self):
        # The checked-in route is per-role; a receipt that records single-image
        # must fail closed before any image command, even if an ambient selector
        # claims single-image. The binding reads ACP_COMPOSE_ROUTE, not the env.
        import tempfile
        receipt = receipt_fixture(topology=images.ACP_SINGLE_IMAGE)
        calls = []

        def run(args, **kwargs):
            calls.append(args)

        def command(*args):
            raise AssertionError('no image command may run before topology binding')

        with tempfile.TemporaryDirectory() as temp:
            previous = os.getcwd()
            os.chdir(temp)
            try:
                handoff = Path(temp) / 'handoff'
                handoff.mkdir()
                write_receipt_archive(handoff / 'images.tar', receipt)
                receipt['archive_sha256'] = images.checksum(handoff / 'images.tar')
                (handoff / 'receipt.json').write_text(json.dumps(receipt))
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.object(images, 'command', side_effect=command), \
                     patch.object(images.subprocess, 'run', side_effect=run), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
                                             'BYQ_ACP_IMAGE_TOPOLOGY': images.ACP_SINGLE_IMAGE}):
                    with self.assertRaisesRegex(ValueError, 'checked-in Compose route'):
                        images.publish(handoff, 'none')
                self.assertFalse(Path('release-manifest').exists())
                self.assertEqual(calls, [])
            finally:
                os.chdir(previous)

    def test_release_permissions_and_no_automatic_main_publication(self):
        source = (ROOT / '.github/workflows/release-images.yml').read_text()
        qualify, publish = source.split('\n  publish:', 1)
        self.assertNotIn('packages: write', qualify)
        self.assertNotIn('secrets.', source)
        self.assertNotIn('pull_request_target', source)
        self.assertNotIn('\n  push:', source)
        self.assertIn('needs: qualify', publish)
        self.assertIn('packages: write', publish)
        self.assertNotIn('local-ci.sh', publish)
        self.assertIn('--release-artifacts', qualify)
        self.assertIn('cancel-in-progress: false', source)

    def test_release_runner_installs_pinned_offline_compose_parser_before_export(self):
        # A fresh ubuntu-24.04 runner supplies Python 3.13 but no PyYAML.
        # images.py export derives the ACP topology through the Compose route
        # parser, so the release workflow must install one pinned, hash-locked,
        # binary-only wheel BEFORE the local-ci run that triggers --release-artifacts.
        workflow = (ROOT / '.github/workflows/release-images.yml').read_text()
        lock = (ROOT / 'scripts/release/requirements.release-runner.lock').read_text()
        self.assertIn('PyYAML==6.0.3', lock)
        self.assertIn(
            '--hash=sha256:'
            '0f29edc409a6392443abf94b9cf89ce99889a1dd5376d94316ae5145dfedd5d6',
            lock,
        )
        install = workflow.index('requirements.release-runner.lock')
        export = workflow.index('--release-artifacts')
        self.assertLess(
            install, export,
            'the pinned Compose parser must be installed before the release export',
        )
        for option in ('--require-hashes', '--only-binary=:all:', '--no-deps'):
            self.assertIn(option, workflow)
        # The architecture lane in ci-selfhosted.yml also needs the parser (its
        # discovered tests import yaml at module top level). It must reuse this
        # one checked-in lock file rather than declare a second dependency.
        self.assertIn(
            'requirements.release-runner.lock',
            (ROOT / '.github/workflows/ci-selfhosted.yml').read_text())

    def test_release_publish_runner_installs_pinned_offline_compose_parser_before_publish(self):
        # images.publish derives the ACP topology from the checked-in Compose
        # route, so the separate, fresh ubuntu-24.04 publish runner must also set
        # up Python 3.13 and install the SAME pinned, hash-locked, binary-only
        # wheel BEFORE `images.py publish`. The qualify lane's install does not
        # reach this runner.
        import yaml
        workflow = yaml.safe_load(
            (ROOT / '.github/workflows/release-images.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['publish']['steps']
        names = [step.get('name', '') for step in steps]
        publish = names.index('Publish exact tested images and SBOMs')
        setups = [index for index, step in enumerate(steps)
                  if str(step.get('uses', '')).startswith('actions/setup-python@')]
        installs = [index for index, step in enumerate(steps)
                    if 'requirements.release-runner.lock' in step.get('run', '')]
        self.assertEqual(len(setups), 1, names)
        self.assertEqual(len(installs), 1, names)
        self.assertEqual(steps[setups[0]].get('with', {}).get('python-version'), '3.13')
        self.assertLess(setups[0], installs[0], names)
        self.assertLess(installs[0], publish, names)
        for option in ('--require-hashes', '--only-binary=:all:', '--no-deps'):
            self.assertIn(option, steps[installs[0]]['run'])
        self.assertIn(
            'scripts/release/requirements.release-runner.lock', steps[installs[0]]['run'])

    def test_ci_architecture_lane_installs_pinned_offline_compose_parser(self):
        # The ci-selfhosted architecture lane runs
        # `python3 -m unittest discover -s tests -p 'test_*.py'`, which imports
        # tests/architecture/test_dsh_authoritative_build.py and
        # test_acp_authoritative_version.py; both `import yaml` at module top
        # level. A fresh ubuntu-24.04 runner ships Python 3.13 but no PyYAML, so
        # the architecture lane must install the SAME pinned, hash-locked,
        # binary-only wheel AFTER setup-python and BEFORE the profile run.
        import yaml
        workflow = yaml.safe_load(
            (ROOT / '.github/workflows/ci-selfhosted.yml').read_text(encoding='utf-8'))
        steps = workflow['jobs']['checks']['steps']
        names = [step.get('name', '') for step in steps]
        installs = [index for index, step in enumerate(steps)
                    if 'requirements.release-runner.lock' in step.get('run', '')]
        self.assertEqual(len(installs), 1, names)
        install = installs[0]
        setup = names.index('Set up Python toolchain')
        profile = names.index('Run risk-selected or full CI profile')
        self.assertLess(setup, install, names)
        self.assertLess(install, profile, names)
        step = steps[install]
        # Only the architecture lane's discovered tests import yaml on the host,
        # so the install is precisely scoped to that lane.
        self.assertEqual(step.get('if'), "matrix.lane == 'architecture'", step)
        for option in ('--require-hashes', '--only-binary=:all:', '--no-deps'):
            self.assertIn(option, step['run'])
        self.assertIn(
            'scripts/release/requirements.release-runner.lock', step['run'])
        # Exactly the same lock file and pin as the release qualify lane.
        lock = (ROOT / 'scripts/release/requirements.release-runner.lock').read_text()
        self.assertIn('PyYAML==6.0.3', lock)
        self.assertIn(
            '--hash=sha256:'
            '0f29edc409a6392443abf94b9cf89ce99889a1dd5376d94316ae5145dfedd5d6',
            lock,
        )

    def test_only_architecture_lane_host_tests_import_yaml(self):
        # Audit guard for the conditional install above: the only tests under
        # tests/ with a top-level `import yaml` are the two architecture tests,
        # and the architecture lane is the only lane that discovers tests/ on
        # the host. Any new host-side YAML importer must widen the condition.
        import re
        top_level_importers = set()
        for path in (ROOT / 'tests').rglob('test_*.py'):
            if re.search(r'(?m)^import yaml\s*$', path.read_text(encoding='utf-8')):
                top_level_importers.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            top_level_importers,
            {
                'tests/architecture/test_acp_authoritative_version.py',
                'tests/architecture/test_dsh_authoritative_build.py',
            },
        )
        source = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertIn('check_architecture()', source)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_*.py'", source)

    def test_release_export_fails_closed_when_the_compose_parser_is_absent(self):
        # The release export parses the checked-in Compose route; without PyYAML
        # (a fresh runner) it must fail closed instead of deriving an absent
        # topology. The route action used by CI-selfhosted never imports it.
        with patch.dict(sys.modules, {'yaml': None}):
            with self.assertRaisesRegex(ValueError, 'parser is unavailable'):
                images._read_compose_document(ROOT / 'compose.yml')
        emitted = subprocess.check_output(
            [sys.executable, str(ROOT / 'scripts/release/images.py'), 'route'],
            cwd=ROOT, text=True).splitlines()
        self.assertEqual(emitted, images.acp_compose_route_files())

    def test_full_profile_runs_integration_even_with_documentation_diff(self):
        source = (ROOT / 'scripts/ci/local-ci.sh').read_text()
        self.assertIn('if [ "$ALL" -eq 1 ] || [ "$INTEGRATION_ONLY" -eq 1 ]; then integration=yes; fi', source)
        self.assertIn('check_f6_chain', source)
        self.assertIn('scripts/evidence/acp-f6-release-fixture.py', source)
        self.assertNotIn('check_dsh_candidate', source)
        self.assertNotIn('ci_image runtime-candidate', source)
        self.assertIn('scripts/dsh/release.py check --historical-inputs', source)
        self.assertIn('scripts/dsh/promotion.py check', source)
        self.assertNotIn('build_revision as b', source)
        self.assertIn('python3 "$REPO_ROOT/scripts/ci/build-images.py" "${services[@]}"', source)
        self.assertIn('acp_compose build', source)
        self.assertIn('release_image_services', source)
        self.assertIn('scripts/dsh/acp_build.py', source)
        self.assertNotIn('COMPOSE_PROJECT_NAME="$project"', source)
        compose_calls = [line for line in source.splitlines() if 'docker compose' in line]
        self.assertEqual(len(compose_calls), 1, compose_calls)
        self.assertIn('then check_f6_chain; fi', source)
        final_gate = source.rindex('if [ "$FAIL" -gt 0 ]; then')
        release_export = source.rindex('if [ "$RELEASE_ARTIFACTS" -eq 1 ]; then')
        self.assertLess(final_gate, release_export)

    def test_parallel_gate_requires_plan_and_all_lanes(self):
        source = (ROOT / '.github/workflows/ci-selfhosted.yml').read_text()
        self.assertIn('needs: [plan, checks]', source)
        self.assertIn('test "$PLAN_RESULT" = success', source)
        self.assertIn('test "$CHECKS_RESULT" = success', source)
        self.assertIn('fail-fast: false', source)
        self.assertIn('if: matrix.browser', source)

    def test_plan_full_and_docs_use_the_same_classifier(self):
        spec = importlib.util.spec_from_file_location('ci_plan', ROOT / 'scripts/ci/plan.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real = subprocess.check_output
        def fake(args, **kwargs):
            if args[:2] == ['git', 'merge-base']:
                return 'a' * 40
            if args[:2] == ['git', 'diff']:
                return 'docs/evidence/example.md\n'
            return real(args, **kwargs)
        with patch.object(module.subprocess, 'check_output', side_effect=fake):
            self.assertEqual([x['lane'] for x in module.plan('main')['include']], ['docs'])
            full = module.plan('main', True)['include']
            self.assertEqual({x['lane'] for x in full}, set(module.COMPONENTS) | {'integration'})
            self.assertEqual({x['lane'] for x in full if x['browser']}, {'frontend', 'integration'})

    def test_corrupt_archive_stops_before_docker_load_or_push(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / 'receipt.json').write_text('{}')
            (directory / 'images.tar').write_bytes(b'corrupt')
            with patch.object(images, 'trusted_main', return_value='a' * 40), \
                 patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}), \
                 patch.object(images, 'validate'), patch.object(images.subprocess, 'run') as docker:
                (directory / 'receipt.json').write_text(json.dumps({'archive_sha256': 'sha256:' + '0' * 64, 'run_id': '123-1'}))
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    images.publish(directory, 'none')
                docker.assert_not_called()

    def test_explicit_release_tag_accepts_stable_beta_and_rc_only(self):
        for tag in ('v0.9.0', 'v0.9.0-beta', 'v0.9.0-beta.1', 'v1.0.0-rc.1'):
            self.assertIsNotNone(manifest.VERSION_TAG.fullmatch(tag), tag)
        for tag in ('v0.9', 'v0.9.0-beta-x', 'v0.9.0-preview', 'latest', '0.9.0-beta', 'v0.9.0+build'):
            self.assertIsNone(manifest.VERSION_TAG.fullmatch(tag), tag)

    def test_promotion_rejects_existing_other_digest_before_any_mutation(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + '0' * 64}), '')
        with patch.object(manifest.subprocess, 'run', return_value=result) as run:
            with self.assertRaisesRegex(ValueError, 'different image'):
                manifest.promote(fixture(), 'v0.2.0')
            self.assertEqual(run.call_count, 1)
            self.assertIn('inspect', run.call_args.args[0])

    def test_promotion_is_idempotent_and_does_not_rebuild(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + 'b' * 64}), '')
        with patch.object(manifest.subprocess, 'run', return_value=result) as run:
            manifest.promote(fixture(), 'v0.2.0')
            # The single-image topology binds three roles to one repository+ref,
            # so each distinct promotion destination is inspected exactly once.
            destinations = {image['ref'].split('@', 1)[0] for image in fixture()['images'].values()}
            self.assertEqual(run.call_count, len(destinations))
            self.assertLess(run.call_count, len(images.SERVICES))
            self.assertTrue(all('inspect' in call.args[0] for call in run.call_args_list))

    def test_promotion_per_role_route_is_unchanged(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'digest': 'sha256:' + 'b' * 64}), '')
        with patch.object(manifest.subprocess, 'run', return_value=result) as run:
            manifest.promote(per_role_fixture(), 'v0.2.0')
            self.assertEqual(run.call_count, len(images.SERVICES))
            self.assertTrue(all('inspect' in call.args[0] for call in run.call_args_list))

    def test_overlay_pull_verifies_each_distinct_ref_once(self):
        # The single-image topology binds three services to one ref, so the
        # overlay preparation must pull and cross-check that ref once while the
        # per-role route still verifies every service ref.
        data = fixture()
        services = list(images.SERVICES)
        pulls = []

        def run(args, **kwargs):
            pulls.append(args)
            return subprocess.CompletedProcess(args, 0, '', '')

        def check_output(args, text=False):
            ref = args[3]
            image = next(item for item in data['images'].values() if item['ref'] == ref)
            if args[1] == 'image':
                return json.dumps([{'Id': image['image_id'], 'RepoDigests': [ref],
                                    'Os': 'linux', 'Architecture': 'amd64'}])
            return json.dumps({'config': {'digest': image['image_id']}})

        with patch.object(manifest.subprocess, 'run', side_effect=run), \
             patch.object(manifest.subprocess, 'check_output', side_effect=check_output):
            manifest.verify_registry_services(data, services)
        unique_refs = {data['images'][name]['ref'] for name in services}
        self.assertEqual(len([call for call in pulls if call[:2] == ['docker', 'pull']]),
                         len(unique_refs))
        self.assertLess(len(unique_refs), len(services))
        self.assertEqual(manifest.verify_registry_services(data, []), None)

    def test_failed_registry_lookup_cannot_be_treated_as_new_version(self):
        result = subprocess.CompletedProcess([], 1, '', 'unauthorized')
        with patch.object(manifest.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'absence'):
                manifest.promote(fixture(), 'v0.2.0')

    def test_retry_cannot_consume_other_run_or_future_attempt(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for produced in ('124-1', '123-3', '123-0'):
                (directory / 'receipt.json').write_text(json.dumps({'run_id': produced}))
                with patch.object(images, 'trusted_main', return_value='a' * 40), \
                     patch.dict(os.environ, {'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}), \
                     patch.object(images.subprocess, 'run') as docker:
                    with self.assertRaisesRegex(ValueError, 'different run or future attempt'):
                        images.publish(directory, 'none')
                    docker.assert_not_called()

    def test_pull_identity_supports_classic_and_containerd_with_exact_manifest_binding(self):
        image = fixture()['images']['frontend']
        remote = {'config': {'digest': image['image_id']}}
        local = {'Id': image['image_id'], 'RepoDigests': [image['ref']],
                 'Architecture': 'amd64', 'Os': 'linux'}
        manifest.verify_pulled_image(image, local, remote)
        local['Id'] = image['ref'].split('@')[1]
        local['Descriptor'] = {'digest': local['Id']}
        manifest.verify_pulled_image(image, local, remote)
        for key, value in [('Id', 'sha256:' + '0' * 64), ('RepoDigests', []),
                           ('Descriptor', {'digest': 'sha256:' + '0' * 64}),
                           ('Architecture', 'arm64')]:
            changed = copy.deepcopy(local)
            changed[key] = value
            with self.assertRaises(ValueError):
                manifest.verify_pulled_image(image, changed, remote)
        with self.assertRaises(ValueError):
            manifest.verify_pulled_image(image, local, {'config': {'digest': 'sha256:' + '0' * 64}})

    @staticmethod
    def _release_run_json(source_sha):
        return json.dumps({
            'conclusion': 'success', 'head_sha': source_sha,
            'event': 'workflow_dispatch', 'head_branch': 'main',
            'path': '.github/workflows/release-images.yml'})

    def test_verified_checksums_each_distinct_sbom_from_the_manifest_directory(self):
        # The attested manifest binds SBOM hashes; verified() must re-read each
        # distinct accompanying *.spdx.json from the manifest's own directory
        # exactly once (single-image lists one SBOM for all three roles).
        import tempfile
        data = fixture()
        distinct_files = sorted({sbom['file'] for sbom in data['sbom'].values()})
        seen = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            paths = {}
            for name in distinct_files:
                path = directory / name
                path.write_text('{"spdxVersion":"SPDX-2.3"}')
                paths[name] = path
            for service in images.SERVICES:
                name = data['sbom'][service]['file']
                data['sbom'][service]['sha256'] = images.checksum(paths[name])
            manifest_path = directory / 'manifest.json'
            manifest_path.write_text(json.dumps(data))
            real_checksum = manifest.checksum

            def counting_checksum(target):
                seen.append(Path(target).name)
                return real_checksum(target)

            with patch.object(manifest.subprocess, 'run'), \
                 patch.object(manifest.subprocess, 'check_output',
                              return_value=self._release_run_json(data['source_sha'])), \
                 patch.object(manifest, 'checksum', side_effect=counting_checksum):
                manifest.verified(manifest_path)
        self.assertEqual(sorted(seen), distinct_files)
        self.assertEqual(len(seen), len(distinct_files))
        self.assertLess(len(distinct_files), len(images.SERVICES))

    def test_verified_fails_closed_on_missing_or_mismatched_sbom(self):
        import tempfile
        data = fixture()
        distinct_files = sorted({sbom['file'] for sbom in data['sbom'].values()})
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name in distinct_files:
                (directory / name).write_text('{"spdxVersion":"SPDX-2.3"}')
            for service in images.SERVICES:
                name = data['sbom'][service]['file']
                data['sbom'][service]['sha256'] = images.checksum(directory / name)
            manifest_path = directory / 'manifest.json'
            manifest_path.write_text(json.dumps(data))
            victim = distinct_files[0]
            with patch.object(manifest.subprocess, 'run'), \
                 patch.object(manifest.subprocess, 'check_output',
                              return_value=self._release_run_json(data['source_sha'])):
                (directory / victim).write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    manifest.verified(manifest_path)
                (directory / victim).write_text('{"spdxVersion":"SPDX-2.3"}')
                (directory / victim).unlink()
                with self.assertRaisesRegex(ValueError, 'missing or unreadable'):
                    manifest.verified(manifest_path)
