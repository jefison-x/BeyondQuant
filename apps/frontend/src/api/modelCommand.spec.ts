import {beforeEach,expect,it,vi} from 'vitest';
import {beginModelCommand,readModelCommand,finishModelCommand,confirmModelCommand} from './modelCommand';
const command={operation:'binding' as const,resource_id:'byq-product',expected_version:0,profile_id:'profile_'+'a'.repeat(32)};
beforeEach(()=>localStorage.clear());
it('keeps the original version and target and refuses unrelated receipt',()=>{
 const original=beginModelCommand('alice',command);expect(readModelCommand('bob')).toBeNull();
 expect(()=>beginModelCommand('alice',{...command,expected_version:1})).toThrow();
 const receipt={...command,state:'confirmed',committed_version:1};expect(confirmModelCommand(receipt,original)).toBe(true);
 for(const wrong of [{profile_id:null},{expected_version:1},{committed_version:2},{resource_id:'other'},{operation:'delete_profile'}])expect(()=>confirmModelCommand({...receipt,...wrong},original)).toThrow();
 finishModelCommand('alice',{...command,profile_id:null});expect(readModelCommand('alice')).toEqual(original);
 finishModelCommand('alice',original);expect(readModelCommand('alice')).toBeNull();
});
it('fails before dispatch on unavailable persistence',()=>{
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('storage denied');});
 try{expect(()=>beginModelCommand('alice',command)).toThrow('storage denied');}finally{spy.mockRestore();}
});
