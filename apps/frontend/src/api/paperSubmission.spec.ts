import {beforeEach,expect,it,vi} from 'vitest';
import {beginPaperSubmission,readPaperSubmission,finishPaperSubmission} from './paperSubmission';
beforeEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('retains exact order inputs and one key across page reload and isolates accounts',()=>{
  const input={operation:'order' as const,account_id:'paper_account_'+'a'.repeat(32),payload:{quantity:100,price:10}};
  const first=beginPaperSubmission('alice',input);
  expect(readPaperSubmission('alice')).toEqual(first);expect(readPaperSubmission('bob')).toBeNull();
  expect(beginPaperSubmission('alice',input).key).toBe(first.key);
  expect(()=>beginPaperSubmission('alice',{...input,payload:{quantity:200,price:10}})).toThrow();
  finishPaperSubmission('alice','wrong');expect(readPaperSubmission('alice')).toEqual(first);
  finishPaperSubmission('alice',first.key);expect(readPaperSubmission('alice')).toBeNull();
});
it('stops before network write when persistence fails',()=>{
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage unavailable')});
  expect(()=>beginPaperSubmission('alice',{operation:'create',payload:{name:'test'}})).toThrow('storage unavailable');
});
