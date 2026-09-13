import {beforeEach,it,expect,vi} from 'vitest';
import {beginModerationSubmission,readModerationSubmission,finishModerationSubmission} from './feedbackModerationSubmission';
import {reconcileFeedbackModerationCommand} from './feedback';
beforeEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('preserves the original scoped moderation and refuses replacement while unknown',()=>{
  const command=beginModerationSubmission('admin-A',{feedback_id:'feedback_'+'a'.repeat(32),action:'triage',payload:{expected_version:2,rationale:'已核实'}});
  expect(readModerationSubmission('admin-A')).toEqual(command);
  expect(readModerationSubmission('admin-B')).toBeNull();
  expect(()=>beginModerationSubmission('admin-A',{...command,action:'accept'})).toThrow();
  finishModerationSubmission('admin-A','different-key');expect(readModerationSubmission('admin-A')).toEqual(command);
  finishModerationSubmission('admin-A',command.key);expect(readModerationSubmission('admin-A')).toBeNull();
});
it('rejects a current or wrong-object result instead of confirming the original action',async()=>{
  const command=beginModerationSubmission('admin-A',{feedback_id:'feedback_'+'a'.repeat(32),action:'triage',payload:{expected_version:2,rationale:'已核实'}});
  for(const feedback of [{feedback_id:command.feedback_id,status:'accepted',version:4},{feedback_id:'feedback_'+'b'.repeat(32),status:'triaged',version:3}]) {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({state:'confirmed',feedback}))));
    await expect(reconcileFeedbackModerationCommand(command)).rejects.toThrow();
    expect(readModerationSubmission('admin-A')).toEqual(command);
  }
  vi.unstubAllGlobals();
});
it('explicit retry sends the identical original key and payload',async()=>{
  const {sendFeedbackModerationCommand}=await import('./feedback');
  const command=beginModerationSubmission('admin-A',{feedback_id:'feedback_'+'a'.repeat(32),action:'triage',payload:{expected_version:2,rationale:'已核实'}});
  const fetcher=vi.fn().mockRejectedValueOnce(new TypeError('connection lost')).mockResolvedValueOnce(new Response(JSON.stringify({feedback:{feedback_id:command.feedback_id,status:'triaged',version:3}})));
  vi.stubGlobal('fetch',fetcher);
  try {
    await expect(sendFeedbackModerationCommand(command)).rejects.toThrow();
    await sendFeedbackModerationCommand(readModerationSubmission('admin-A')!);
    expect(fetcher.mock.calls[0]![1].body).toBe(fetcher.mock.calls[1]![1].body);
    expect(JSON.parse(fetcher.mock.calls[1]![1].body).idempotency_key).toBe(command.key);
  } finally {vi.unstubAllGlobals();}
});
