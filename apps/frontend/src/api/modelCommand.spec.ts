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
it('accepts profile disable and enable commands with the same receipt contract',()=>{
 const profileId='profile_'+'b'.repeat(32);
 for(const operation of ['disable_profile','enable_profile'] as const){
  const statusCommand={operation,resource_id:profileId,expected_version:2,profile_id:profileId};
  const original=beginModelCommand('alice',statusCommand);
  expect(readModelCommand('alice')).toEqual(statusCommand);
  expect(()=>beginModelCommand('alice',{...statusCommand,expected_version:3})).toThrow();
  const receipt={...statusCommand,state:'confirmed',committed_version:3};
  expect(confirmModelCommand(receipt,original)).toBe(true);
  expect(()=>confirmModelCommand({...receipt,operation:operation==='disable_profile'?'enable_profile':'disable_profile'},original)).toThrow();
  finishModelCommand('alice',original);expect(readModelCommand('alice')).toBeNull();
 }
});
