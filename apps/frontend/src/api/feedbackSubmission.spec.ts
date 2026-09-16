import { beforeEach, expect, it, vi } from 'vitest';
import { beginFeedbackSubmission, readFeedbackSubmission, finishFeedbackSubmission } from './feedbackSubmission';
beforeEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('keeps the exact feedback command over reload and isolates workspace and acknowledgement',()=>{
  const input = {operation:'create' as const,payload:{title:'Original private draft'}};
  const first = beginFeedbackSubmission('alice',input);
  expect(readFeedbackSubmission('alice')).toEqual(first);
  expect(beginFeedbackSubmission('alice',input).key).toBe(first.key);
  expect(readFeedbackSubmission('bob')).toBeNull();
  expect(()=>beginFeedbackSubmission('alice',{...input,payload:{title:'changed'}})).toThrow();
  finishFeedbackSubmission('alice','wrong'); expect(readFeedbackSubmission('alice')).toEqual(first);
  finishFeedbackSubmission('alice',first.key); expect(readFeedbackSubmission('alice')).toBeNull();
});
it('fails before sending if durable browser storage is unavailable',()=>{
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage unavailable')});
  expect(()=>beginFeedbackSubmission('alice',{operation:'create',payload:{}})).toThrow('storage unavailable');
});
