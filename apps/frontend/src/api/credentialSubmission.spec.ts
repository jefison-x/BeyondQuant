import {beforeEach,expect,it,vi} from 'vitest';
import {beginCredentialWrite,credentialWriteScope,readCredentialWrite,finishCredentialWrite} from './credentialSubmission';
beforeEach(()=>{localStorage.clear();vi.restoreAllMocks();});
it('persists original metadata and key but never submitted secrets',()=>{
  const value=beginCredentialWrite('alice','create',{provider:'deepseek',label:'test',secret:'synthetic-api-key-1234',envelope_ciphertext:'must-not-save'});
  const raw=localStorage.getItem(localStorage.key(0)!);expect(raw).not.toContain('synthetic-api-key');expect(raw).not.toContain('envelope');
  expect(readCredentialWrite('alice')).toEqual(value);expect(readCredentialWrite('bob')).toBeNull();
  expect(beginCredentialWrite('alice','create',{provider:'deepseek',label:'test',secret:'reentered-memory-only'}).key).toBe(value.key);
  expect(()=>beginCredentialWrite('alice','create',{provider:'deepseek',label:'changed',secret:'memory-only'})).toThrow();
  finishCredentialWrite('alice','wrong');expect(readCredentialWrite('alice')).not.toBeNull();finishCredentialWrite('alice',value.key);expect(readCredentialWrite('alice')).toBeNull();
});
it('refuses before a write if original request identity cannot be saved',()=>{
  vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage unavailable')});
  expect(()=>beginCredentialWrite('alice','create',{provider:'deepseek',secret:'memory-only'})).toThrow();
});
it('keeps search credential receipts in a separate pending namespace',()=>{
  const ownerScope=JSON.stringify(['alice','workspace-a']);
  const modelScope=credentialWriteScope(ownerScope,'model_api_key');
  const searchScope=credentialWriteScope(ownerScope,'web_search_api_key');
  expect(modelScope).toBe(ownerScope);
  expect(searchScope).not.toBe(modelScope);
  const model=beginCredentialWrite(modelScope,'create',{provider:'deepseek',label:'model',secret:'synthetic-model-secret'});
  const search=beginCredentialWrite(searchScope,'create',{purpose:'web_search_api_key',provider:'deepseek',label:'search',secret:'synthetic-search-secret'});
  expect(readCredentialWrite(modelScope)).toEqual(model);
  expect(readCredentialWrite(searchScope)).toEqual(search);
  expect(localStorage.getItem(`byq.credential-write.v1:${searchScope}`)).not.toContain('synthetic-search-secret');
  finishCredentialWrite(searchScope,search.key);
  expect(readCredentialWrite(modelScope)).toEqual(model);
});
