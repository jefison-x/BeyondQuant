"""Fixed H5 qualification scenario; no model calls or synthetic result generation.

The operator supplies only exact identities created in the isolated Product stack.
Completion is independently checked against the actual persisted domain objects.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

SCENARIO = 'h5-three-backtests.v1'
PROMPT = (
    'H5隔离合成研究验收：只使用随本请求提供的测试工作区、原研究任务、冻结股票池和合成行情。'
    '完成三轮规则策略研究：每轮先回读上一轮真实结果再提出一个有理由的修改，'
    '按当前BYQ合同校验、保存版本、申请所需审批并实际执行回测；三轮共用同一任务和相同数据窗口。'
    '每次审批或作业完成后，继续评估本原目标，不把获批、排队或回合结束当成目标完成。'
    '未知提交先按原键核对，不重复创建。等待审批时明确下一步；不自行越过审批。'
    '三轮完成后，逐个读取原回测摘要，保存研究报告，列出三个确切job_id、版本ID、真实总收益率及其差异，'
    '报告content使用synthetic=true、selected_job_id和candidates数组；每个候选包含job_id、strategy_version_artifact_id和total_return。'
    '以总收益率最高者选优，相同收益按job_id字典序选一个，明确这仅是合成数据验收。'
    '最后请求人工在Product页面创建一个模拟账户并绑定原冻结股票池；待账户事实核对后才完成原任务。'
    '不要训练模型、访问外部行情、创建反馈、发布信息或操作其他工作区。'
)
PROMPT_SHA256 = hashlib.sha256(PROMPT.encode()).hexdigest()


def validate_context(value):
    if not isinstance(value, dict) or value.get('scenario') != SCENARIO or value.get('synthetic') is not True:
        raise ValueError('fixed synthetic H5 context required')
    if value.get('owner') != 'h5-research-user':
        raise ValueError('isolated H5 user required')
    for key, prefix, count in [('task_id','task',32),('workspace_id','workspace',32),('pool_id','stock_pool',32),('snapshot_id','stock_pool_snapshot',64)]:
        if not re.fullmatch(prefix+'_[0-9a-f]{'+str(count)+'}',str(value.get(key,''))):
            raise ValueError('exact H5 identity required: '+key)
    if value.get('symbols') != ['000001.SZ','600000.SH']:
        raise ValueError('fixed synthetic universe required')
    return value


def verify_completion(context, task, jobs, report, account):
    """Use caller-fetched authoritative rows, never assistant prose, as evidence."""
    validate_context(context)
    if task.get('task_id') != context['task_id'] or task.get('owner_principal') != context['owner'] or task.get('status') != 'completed':
        raise AssertionError('original research task has not completed')
    if len(jobs) != 3 or len({row.get('job_id') for row in jobs}) != 3:
        raise AssertionError('exactly three distinct completed backtests required')
    versions = set()
    measured = {}
    job_versions = {}
    for job in jobs:
        if job.get('task_id') != context['task_id'] or job.get('owner_principal') != context['owner'] or job.get('status') != 'completed':
            raise AssertionError('backtest scope or state mismatch')
        if job.get('stock_pool_snapshot_id') != context['snapshot_id']:
            raise AssertionError('backtest must use original frozen snapshot')
        if not re.fullmatch(r'backtest_[0-9a-f]{32}', str(job.get('job_id',''))) or not re.fullmatch(r'artifact_[0-9a-f]{32}', str(job.get('strategy_version_artifact_id',''))):
            raise AssertionError('canonical backtest and strategy identities required')
        versions.add(job['strategy_version_artifact_id'])
        job_versions[job['job_id']] = job['strategy_version_artifact_id']
        measured[job['job_id']] = Decimal(str(job['summary']['total_return']))
        if not measured[job['job_id']].is_finite():
            raise AssertionError('non-finite performance is not completion')
    if len(versions) != 3:
        raise AssertionError('three evaluated strategy versions required')
    if report.get('kind') != 'research_report' or report.get('task_id') != context['task_id'] or report.get('status') != 'validated' or report.get('owner_principal') != context['owner']:
        raise AssertionError('validated report belonging to original task required')
    content = report['content']
    entries = content.get('candidates',[])
    if len(entries) != 3 or {row.get('job_id') for row in entries} != set(measured):
        raise AssertionError('report must compare the exact original jobs')
    for row in entries:
        if row.get('strategy_version_artifact_id') != job_versions[row['job_id']]:
            raise AssertionError('report strategy differs from original backtest')
        if Decimal(str(row['total_return'])) != measured[row['job_id']]:
            raise AssertionError('report performance differs from persisted result')
    selected = min(measured, key=lambda key:(-measured[key],key))
    if content.get('selected_job_id') != selected or content.get('synthetic') is not True:
        raise AssertionError('selection or synthetic disclosure is invalid')
    if account.get('owner_principal') != context['owner'] or account.get('workspace_id') != context['workspace_id'] or account.get('status') != 'active' or account.get('bound_snapshot_id') != context['snapshot_id'] or account.get('bound_pool_id') != context['pool_id']:
        raise AssertionError('actual owner-scoped paper account with original frozen snapshot required')
    evidence = task.get('progress',{}).get('completion_evidence',[])
    if report['artifact_id'] not in evidence:
        raise AssertionError('original task must retain its report evidence')
    return {'scenario':SCENARIO,'prompt_sha256':PROMPT_SHA256,'task_id':context['task_id'],
        'job_ids':sorted(measured),'selected_job_id':selected,'account_id':account['account_id']}


def collect_completion(context, *, job_ids, report_id, account_id, read):
    """Read-only operator adapter: `read` must GET the authenticated isolated Backend.

    No catalog search, latest-object fallback, retry, or writes. The caller owns
    HTTP isolation/authentication; this function never loads a credential.
    """
    validate_context(context)
    if (not isinstance(job_ids, list) or len(job_ids) != 3
            or any(not isinstance(value, str) or not re.fullmatch(r'backtest_[0-9a-f]{32}', value) for value in job_ids)
            or len(set(job_ids)) != 3):
        raise ValueError('three exact original backtest identities required')
    if not isinstance(report_id, str) or not re.fullmatch(r'artifact_[0-9a-f]{32}', report_id):
        raise ValueError('exact original report identity required')
    if not isinstance(account_id, str) or not re.fullmatch(r'paper_account_[0-9a-f]{32}', account_id):
        raise ValueError('exact original account identity required')

    def exact(path, field, identity, envelope=None):
        value = read(path)
        if envelope is not None:
            value = value.get(envelope) if isinstance(value, dict) else None
        if not isinstance(value, dict) or value.get(field) != identity:
            raise AssertionError('authoritative read returned a different or missing object')
        return value

    task = exact('/v1/research/tasks/' + context['task_id'], 'task_id', context['task_id'])
    jobs = [exact('/v1/research/backtests/' + identity + '/summary', 'job_id', identity, 'job')
            for identity in job_ids]
    report = exact('/v1/research/artifacts/' + report_id, 'artifact_id', report_id)
    account = exact('/v1/paper/accounts/' + account_id, 'account_id', account_id, 'account')
    return verify_completion(context, task, jobs, report, account)
