"""Focused tests for the unactivated task-ready.v2 DSH tool guard journal."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.continuation_budget import read_task_ready_v2_guard
from packages.contracts.agent_execution_options import default_agent_execution_options
from packages.contracts.continuation_request import (
    continuation_reservation_v3,
)


_ROOT_RUN_ID = 'a' * 32
_TOOL = 'mcp__byq__byq_research_get'
def _reservation(*, options=None, revision=7, event_digest='b' * 64):
    execution_options = default_agent_execution_options() if options is None else options
    return continuation_reservation_v3(
        owner_principal='owner-a',
        workspace_id='workspace-a',
        conversation_id='conversation-a',
        task_id='task_' + 'c' * 32,
        event_key='ready-v1:' + event_digest,
        signal_job_id='signaljob_' + 'd' * 32,
        result_artifact_id='artifact_' + 'e' * 32,
        result_artifact_content_sha256='f' * 64,
        options=execution_options,
        options_revision=revision,
    )


def _header(reservation, root_run_id=_ROOT_RUN_ID):
    return {
        'schema_version': 'task-ready-tool-guard.v2',
        'root_run_id': root_run_id,
        'idempotency_key': reservation['idempotency_key'],
        'source_fact_sha256': reservation['source_fact_sha256'],
        'execution_profile': reservation['execution_profile'],
        'request_limits': reservation['request_limits'],
        'ready': True,
    }


def _tool_row(reservation, call, *, root_run_id=_ROOT_RUN_ID, tool_name=_TOOL):
    profile = reservation['execution_profile']
    return {
        'phase': 'tool',
        'root_run_id': root_run_id,
        'idempotency_key': reservation['idempotency_key'],
        'source_fact_sha256': reservation['source_fact_sha256'],
        'profile_sha256': profile['profile_sha256'],
        'options_revision': profile['options_revision'],
        'call': call,
        'tool_name': tool_name,
    }


def _blocked_row(reservation, reason='BYQ_CONTINUATION_TOOL_LIMIT', *, root_run_id=_ROOT_RUN_ID):
    profile = reservation['execution_profile']
    return {
        'phase': 'blocked',
        'root_run_id': root_run_id,
        'idempotency_key': reservation['idempotency_key'],
        'source_fact_sha256': reservation['source_fact_sha256'],
        'profile_sha256': profile['profile_sha256'],
        'options_revision': profile['options_revision'],
        'blocked_reason': reason,
        'tool_name': _TOOL,
    }


def _write_rows(path: Path, rows):
    path.write_bytes(b''.join(
        json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode('utf-8') + b'\n'
        for row in rows
    ))


def test_task_ready_v2_guard_reader_streams_past_v1_file_and_row_caps(tmp_path):
    reservation = _reservation()
    path = tmp_path / 'large-guard.jsonl'
    rows = [_header(reservation)]
    rows.extend(_tool_row(reservation, index) for index in range(1, 701))
    _write_rows(path, rows)

    assert path.stat().st_size > 128 * 1024
    receipt = read_task_ready_v2_guard(path, reservation, _ROOT_RUN_ID)
    assert receipt == {
        'root_run_id': _ROOT_RUN_ID,
        'idempotency_key': reservation['idempotency_key'],
        'source_fact_sha256': reservation['source_fact_sha256'],
        'profile_sha256': reservation['execution_profile']['profile_sha256'],
        'options_revision': 7,
        'tool_calls': 700,
        'blocked_reason': None,
        'observed_status': 'nonterminal_observed',
    }


def test_task_ready_v2_guard_reader_binds_root_event_facts_profile_and_terminal_observation(tmp_path):
    reservation = _reservation()
    path = tmp_path / 'bound-guard.jsonl'
    _write_rows(path, [_header(reservation), _tool_row(reservation, 1)])
    nonterminal = read_task_ready_v2_guard(path, reservation, _ROOT_RUN_ID)
    terminal = read_task_ready_v2_guard(path, reservation, _ROOT_RUN_ID, terminal=True)
    assert nonterminal['observed_status'] == 'nonterminal_observed'
    assert terminal['observed_status'] == 'terminal_observed'
    assert terminal['tool_calls'] == 1

    with pytest.raises(ValueError, match='identity or classification'):
        read_task_ready_v2_guard(path, reservation, 'not-a-root')
    with pytest.raises(ValueError, match='identity or classification'):
        read_task_ready_v2_guard(path, reservation, _ROOT_RUN_ID, terminal=1)

    changed_event = _reservation(event_digest='9' * 64)
    assert changed_event['idempotency_key'] == reservation['idempotency_key']
    assert changed_event['source_fact_sha256'] != reservation['source_fact_sha256']
    with pytest.raises(ValueError, match='not ready or bound'):
        read_task_ready_v2_guard(path, changed_event, _ROOT_RUN_ID)

    changed_revision = _reservation(revision=8)
    assert changed_revision['idempotency_key'] == reservation['idempotency_key']
    with pytest.raises(ValueError, match='not ready or bound'):
        read_task_ready_v2_guard(path, changed_revision, _ROOT_RUN_ID)


def test_task_ready_v2_guard_reader_rejects_tampered_closed_shapes_and_order(tmp_path):
    reservation = _reservation()
    valid_header = _header(reservation)
    valid_tool = _tool_row(reservation, 1)
    invalid_cases = []

    ready_as_int = dict(valid_header)
    ready_as_int['ready'] = 1
    invalid_cases.append([ready_as_int])
    extra_header_field = dict(valid_header, reservation_id='forbidden')
    invalid_cases.append([extra_header_field])
    wrong_idempotency = dict(valid_header, idempotency_key=f"task-ready-event:{'0' * 64}")
    invalid_cases.append([wrong_idempotency])
    bool_ordinal = dict(valid_tool, call=True)
    invalid_cases.append([valid_header, bool_ordinal])
    wrong_profile = dict(valid_tool, profile_sha256='0' * 64)
    invalid_cases.append([valid_header, wrong_profile])
    wrong_tool = dict(valid_tool, tool_name='mcp__byq__byq_artifact_create')
    invalid_cases.append([valid_header, wrong_tool])
    skipped_ordinal = _tool_row(reservation, 2)
    invalid_cases.append([valid_header, skipped_ordinal])
    invalid_block_reason = dict(_blocked_row(reservation), blocked_reason=['not', 'a', 'string'])
    invalid_cases.append([valid_header, invalid_block_reason])
    trailing_after_block = [valid_header, _blocked_row(reservation), valid_tool]
    invalid_cases.append(trailing_after_block)

    for index, rows in enumerate(invalid_cases):
        path = tmp_path / f'invalid-{index}.jsonl'
        _write_rows(path, rows)
        with pytest.raises(ValueError):
            read_task_ready_v2_guard(path, reservation, _ROOT_RUN_ID)

    bounded_options = default_agent_execution_options()
    bounded_options['max_tool_calls'] = 1
    bounded = _reservation(options=bounded_options)
    accepted_then_blocked = tmp_path / 'explicit-limit.jsonl'
    _write_rows(accepted_then_blocked, [
        _header(bounded), _tool_row(bounded, 1), _blocked_row(bounded),
    ])
    receipt = read_task_ready_v2_guard(accepted_then_blocked, bounded, _ROOT_RUN_ID)
    assert receipt['tool_calls'] == 1
    assert receipt['blocked_reason'] == 'BYQ_CONTINUATION_TOOL_LIMIT'

    over_limit = tmp_path / 'over-limit.jsonl'
    _write_rows(over_limit, [_header(bounded), _tool_row(bounded, 1), _tool_row(bounded, 2)])
    with pytest.raises(ValueError, match='invalid admitted'):
        read_task_ready_v2_guard(over_limit, bounded, _ROOT_RUN_ID)


def test_task_ready_v2_guard_reader_rejects_oversized_incomplete_and_duplicate_rows(tmp_path):
    reservation = _reservation()
    header = json.dumps(_header(reservation), separators=(',', ':')).encode('utf-8') + b'\n'
    oversized = tmp_path / 'oversized.jsonl'
    oversized.write_bytes(header + b'{"padding":"' + b'x' * (128 * 1024) + b'"}\n')
    with pytest.raises(ValueError, match='oversized or incomplete'):
        read_task_ready_v2_guard(oversized, reservation, _ROOT_RUN_ID)

    incomplete = tmp_path / 'incomplete.jsonl'
    incomplete.write_bytes(header + b'{"phase":"tool"}')
    with pytest.raises(ValueError, match='oversized or incomplete'):
        read_task_ready_v2_guard(incomplete, reservation, _ROOT_RUN_ID)

    duplicate_key = tmp_path / 'duplicate.jsonl'
    duplicate_key.write_bytes(
        b'{"schema_version":"task-ready-tool-guard.v2",'
        b'"schema_version":"task-ready-tool-guard.v2"}\n'
    )
    with pytest.raises(ValueError, match='duplicate key'):
        read_task_ready_v2_guard(duplicate_key, reservation, _ROOT_RUN_ID)

    non_finite = tmp_path / 'non-finite.jsonl'
    non_finite.write_bytes(header + b'{"value":NaN}\n')
    with pytest.raises(ValueError, match='non-finite'):
        read_task_ready_v2_guard(non_finite, reservation, _ROOT_RUN_ID)

    deeply_nested = tmp_path / 'deeply-nested.jsonl'
    deeply_nested.write_bytes(header + b'[' * 1200 + b'0' + b']' * 1200 + b'\n')
    with pytest.raises(ValueError):
        read_task_ready_v2_guard(deeply_nested, reservation, _ROOT_RUN_ID)


def test_task_ready_v2_guard_cross_language_apply_writes_python_readable_fsynced_journal(tmp_path):
    reservation = _reservation()
    journal = tmp_path / 'native-apply.jsonl'
    config = {
        'guardMode': 'task-ready-options',
        'journalPath': str(journal),
        'executionProfile': reservation['execution_profile'],
        'requestLimits': reservation['request_limits'],
        'rootRunId': _ROOT_RUN_ID,
        'idempotencyKey': reservation['idempotency_key'],
        'sourceFactSha256': reservation['source_fact_sha256'],
    }
    repository_root = Path(__file__).resolve().parents[3]
    plugin_path = repository_root / 'plugins/dsh-byq/runtime/byq-continuation-budget.js'
    node = shutil.which('node')
    assert node is not None, 'the pinned test image must provide Node for the cross-language contract test'
    script = r"""
import { pathToFileURL } from 'node:url';
const { apply } = await import(pathToFileURL(process.env.BYQ_PLUGIN_PATH).href);
const hooks = new Map();
const effects = [];
const ctx = {
  on: (event, hook) => hooks.set(event, hook),
  effect: effect => effects.push(effect),
};
apply(ctx, JSON.parse(process.env.BYQ_GUARD_CONFIG));
const agent = { cancel() {} };
agent.ctx = { tools: { restrict: () => () => {} } };
hooks.get('agent/created')({ agent });
const result = await hooks.get('tools/pre-execute')(
  { name: 'mcp__byq__byq_research_get', agent },
  async () => ({ kind: 'dispatched' }),
);
if (result?.kind !== 'dispatched') throw new Error('plugin did not admit the synthetic F6 tool');
for (const effect of effects) effect()();
"""
    completed = subprocess.run(
        [node, '--input-type=module', '-e', script],
        cwd=repository_root,
        env={
            'BYQ_PLUGIN_PATH': str(plugin_path),
            'BYQ_GUARD_CONFIG': json.dumps(config, separators=(',', ':')),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert journal.exists()
    receipt = read_task_ready_v2_guard(journal, reservation, _ROOT_RUN_ID)
    assert receipt['tool_calls'] == 1
    assert receipt['idempotency_key'] == reservation['idempotency_key']
    assert receipt['source_fact_sha256'] == reservation['source_fact_sha256']
    assert receipt['profile_sha256'] == reservation['execution_profile']['profile_sha256']
    assert receipt['options_revision'] == reservation['execution_profile']['options_revision']
    assert receipt['blocked_reason'] is None
