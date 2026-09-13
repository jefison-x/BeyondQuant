import {beforeEach,expect,it,vi} from 'vitest';
import {beginCredentialWrite,readCredentialWrite,finishCredentialWrite} from './credentialSubmission';
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
