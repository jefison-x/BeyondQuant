import { afterEach, expect, it, vi } from 'vitest';
import { beginPoolSubmission, readPoolSubmission, finishPoolSubmission } from './poolSubmission';
afterEach(() => {localStorage.clear(); vi.restoreAllMocks();});
it('retains exact kind and payload across reload and rejects changed input or wrong acknowledgement', () => {
  const payload = {name:'original', symbols:['000001.SZ']};
  const first = beginPoolSubmission('alice:workspace', 'custom', payload);
  expect(readPoolSubmission('alice:workspace')).toEqual(first);
  expect(beginPoolSubmission('alice:workspace','custom',payload)).toEqual(first);
  expect(readPoolSubmission('bob:workspace')).toBeNull();
  expect(() => beginPoolSubmission('alice:workspace','index',payload)).toThrow('原请求');
  finishPoolSubmission('alice:workspace','wrong-key');
  expect(readPoolSubmission('alice:workspace')).toEqual(first);
  finishPoolSubmission('alice:workspace',first.key);
  expect(readPoolSubmission('alice:workspace')).toBeNull();
});
it('fails before a write can start when durable storage cannot save', () => {
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(() => {throw new Error('storage unavailable');});
  expect(() => beginPoolSubmission('alice:workspace','custom',{name:'original'})).toThrow('storage unavailable');
});
