import {beforeEach,expect,it,vi} from 'vitest';
import {beginProfileSubmission,readProfileSubmission,finishProfileSubmission,confirmProfileReceipt} from './profileSubmission';
const input={credential_id:'cred_'+'a'.repeat(32),key_name:'original',display_name:'Original',provider:'deepseek',model:'deepseek-v4-flash',temperature:0.2,reasoning_enabled:false};
beforeEach(()=>localStorage.clear());
it('freezes the original configuration and rejects an unrelated same-key receipt',()=>{
 const original=beginProfileSubmission('alice',input);expect(readProfileSubmission('bob')).toBeNull();
 expect(beginProfileSubmission('alice',input)).toEqual(original);
 expect(()=>beginProfileSubmission('alice',{...input,key_name:'replacement'})).toThrow();
 const receipt={state:'confirmed',profile_id:'profile_'+'b'.repeat(32),committed_version:1,input};
 expect(confirmProfileReceipt(receipt,original)).toBe(receipt.profile_id);
 expect(()=>confirmProfileReceipt({...receipt,input:{...input,model:'other'}},original)).toThrow();
 expect(()=>confirmProfileReceipt({...receipt,profile_id:'wrong'},original)).toThrow();
 finishProfileSubmission('alice',{...input,key_name:'wrong'});expect(readProfileSubmission('alice')).toEqual(original);
 finishProfileSubmission('alice',original);expect(readProfileSubmission('alice')).toBeNull();
});
it('fails before sending when storage fails or an unexpected secret field is present',()=>{
 expect(()=>beginProfileSubmission('alice',{...input,secret:'not-allowed'})).toThrow();
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage denied');});
 try{expect(()=>beginProfileSubmission('alice',input)).toThrow('storage denied');}finally{spy.mockRestore();}
});
