"""Negative gate tests, not a claim of model or real-domain H5 completion."""
from copy import deepcopy
import unittest
from tests.dsh_upgrade.h5_research_contract import SCENARIO, verify_completion


def fixture():
    context={'scenario':SCENARIO,'synthetic':True,'owner':'h5-research-user','task_id':'task_'+'a'*32,
        'workspace_id':'workspace_'+'a'*32,'pool_id':'stock_pool_'+'b'*32,'snapshot_id':'stock_pool_snapshot_'+'c'*64,
        'symbols':['000001.SZ','600000.SH']}
    task={'task_id':context['task_id'],'owner_principal':context['owner'],'status':'completed','progress':{'completion_evidence':['artifact_'+'a'*32]}}
    jobs=[{'job_id':'backtest_'+char*32,'task_id':context['task_id'],'owner_principal':context['owner'],'status':'completed',
        'strategy_version_artifact_id':'artifact_'+char*32,'stock_pool_snapshot_id':context['snapshot_id'],'summary':{'total_return':value}}
        for char,value in [('b',0.1),('c',0.2),('d',0.15)]]
    report={'artifact_id':'artifact_'+'a'*32,'task_id':context['task_id'],'owner_principal':context['owner'],'kind':'research_report','status':'validated',
        'content':{'synthetic':True,'selected_job_id':jobs[1]['job_id'],'candidates':[{'job_id':j['job_id'],'strategy_version_artifact_id':j['strategy_version_artifact_id'],'total_return':j['summary']['total_return']} for j in jobs]}}
    account={'account_id':'paper_account_'+'e'*32,'owner_principal':context['owner'],'workspace_id':context['workspace_id'],
        'status':'active','bound_snapshot_id':context['snapshot_id'],'bound_pool_id':context['pool_id']}
    return context,task,jobs,report,account


class H5CompletionGateTest(unittest.TestCase):
    def test_internal_consistency_gate_accepts_matching_facts(self):
        self.assertEqual(verify_completion(*fixture())['selected_job_id'],'backtest_'+'c'*32)

    def test_neither_task_label_nor_report_text_can_replace_domain_facts(self):
        for failure in ('pending_job','two_jobs','wrong_task','wrong_pool','wrong_account_workspace','fake_return','wrong_winner','missing_report_link','wrong_candidate_version','wrong_account_pool'):
            with self.subTest(failure=failure):
                values=list(deepcopy(fixture()));context,task,jobs,report,account=values
                if failure=='pending_job':jobs[2]['status']='queued'
                if failure=='two_jobs':jobs.pop()
                if failure=='wrong_task':jobs[1]['task_id']='task_'+'f'*32
                if failure=='wrong_pool':jobs[1]['stock_pool_snapshot_id']='stock_pool_snapshot_'+'f'*64
                if failure=='wrong_account_workspace':account['workspace_id']='workspace_'+'f'*32
                if failure=='fake_return':report['content']['candidates'][0]['total_return']=0.99
                if failure=='wrong_winner':report['content']['selected_job_id']=jobs[0]['job_id']
                if failure=='wrong_candidate_version':report['content']['candidates'][0]['strategy_version_artifact_id']='artifact_'+'f'*32
                if failure=='wrong_account_pool':account['bound_pool_id']='stock_pool_'+'f'*32
                if failure=='missing_report_link':task['progress']['completion_evidence']=[]
                with self.assertRaises(AssertionError):verify_completion(*values)
