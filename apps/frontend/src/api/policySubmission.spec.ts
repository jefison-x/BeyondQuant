import {beforeEach,expect,it,vi} from 'vitest';
import {beginPolicySubmission,readPolicySubmission,finishPolicySubmission,confirmPolicyReceipt} from './policySubmission';
beforeEach(()=>localStorage.clear());
it('freezes the original policy choice and rejects a different key or result',()=>{
 const command=beginPolicySubmission('alice','settings',{paused:true});
 expect(beginPolicySubmission('alice','settings',{paused:true}).key).toBe(command.key);
 expect(readPolicySubmission('bob')).toBeNull();expect(()=>beginPolicySubmission('alice','settings',{paused:false})).toThrow();
 const receipt={state:'confirmed',request_id:command.key,operation:'settings',resource_id:null,result:{paused:true}};
 expect(confirmPolicyReceipt(receipt,command)).toBe(true);
 for(const wrong of [{request_id:'other'},{operation:'preset'},{result:{paused:false}},{resource_id:'wrong'}])expect(()=>confirmPolicyReceipt({...receipt,...wrong},command)).toThrow();
 finishPolicySubmission('alice','wrong');expect(readPolicySubmission('alice')).toEqual(command);
 finishPolicySubmission('alice',command.key);expect(readPolicySubmission('alice')).toBeNull();
});
it('never dispatches an unrecorded or unexpected payload',()=>{
 expect(()=>beginPolicySubmission('alice','settings',{secret:'x'})).toThrow();
 expect(()=>beginPolicySubmission('alice','settings',{max_auto_executions_per_hour:NaN})).toThrow();
 expect(localStorage.length).toBe(0);
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage denied');});
 try{expect(()=>beginPolicySubmission('alice','settings',{paused:true})).toThrow('storage denied');}finally{spy.mockRestore();}
});
it('requires the exact rule and prior version for an update receipt',()=>{
 const id='policy_rule_'+'a'.repeat(32),command=beginPolicySubmission('alice','rule_update',{name:'Original',expected_version:2},id);
 const receipt={state:'confirmed',operation:'rule_update',request_id:command.key,resource_id:id,result:{rule_id:id,version:3,name:'Original'}};
 expect(confirmPolicyReceipt(receipt,command)).toBe(true);
 expect(()=>confirmPolicyReceipt({...receipt,result:{...receipt.result,rule_id:'policy_rule_'+'b'.repeat(32)}},command)).toThrow();
 expect(()=>confirmPolicyReceipt({...receipt,result:{...receipt.result,version:4}},command)).toThrow();
});
