import {afterEach,it,expect,vi} from 'vitest';
import {readPendingText,writePendingText} from './pendingStorage';
afterEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('rejects oversized text before parsing or replacing an existing pending record',()=>{
  localStorage.setItem('slot','original');
  expect(()=>writePendingText('slot','x'.repeat(17),16,'too large')).toThrow('too large');
  expect(localStorage.getItem('slot')).toBe('original');
  expect(()=>readPendingText('slot',4,'too large')).toThrow('too large');
  expect(localStorage.getItem('slot')).toBe('original');
});
it('keeps storage namespaces and original serialized text intact',()=>{
  writePendingText('owner-a','{"key":"original"}',64,'too large');
  expect(readPendingText('owner-a',64,'too large')).toBe('{"key":"original"}');
  expect(readPendingText('owner-b',64,'too large')).toBeNull();
});
it('propagates a storage failure before any caller can proceed to network submission',()=>{
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('quota','QuotaExceededError');});
  const network=vi.fn();
  expect(()=>{writePendingText('slot','{}',64,'too large');network();}).toThrow();
  expect(network).not.toHaveBeenCalled();
});
it('bounds research recovery before parsing an oversized stored object',async()=>{
  const {readTaskSubmission}=await import('./taskSubmission');
  localStorage.setItem('byq.research-submission.v1:owner-a','x'.repeat(32769));
  const parse=vi.spyOn(JSON,'parse');
  expect(()=>readTaskSubmission('owner-a')).toThrow('超出范围');
  expect(parse).not.toHaveBeenCalled();
});
