import { afterEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import Panel from './ResearchReceiptPanel.vue';
import { getResearchReceipts } from '@/api/research';
vi.mock('@/api/research', () => ({ getResearchReceipts: vi.fn() }));
const reply = (conversation: string, id: string) => ({schema_version:'research-receipt-list.v1' as const,
  conversation_id:conversation, receipts:[{schema_version:'research-receipt-watch.v1' as const,
    watch_id:id,entity_type:'research_task' as const,task_id:null,idempotency_key:'original',
    status:'needs_attention' as const,reason:'attempts_exhausted',entity_id:null,attempts:8,max_attempts:8,
    deadline_at:'2026-09-10T12:00:00Z',next_check_at:null,outcome:'outcome_unknown' as const}]});
afterEach(() => {vi.clearAllMocks();vi.useRealTimers();});
it('discards late replies from a previous conversation and stops after unmount', async () => {
  vi.useFakeTimers();
  let resolve!: (value: ReturnType<typeof reply>) => void;
  vi.mocked(getResearchReceipts).mockImplementationOnce(() => new Promise(r => {resolve=r;}))
    .mockResolvedValueOnce(reply('second','second-watch'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});
  await wrapper.setProps({conversationId:'second'});await flushPromises();
  resolve(reply('first','foreign-watch'));await flushPromises();
  expect(wrapper.text()).toContain('second-watch');expect(wrapper.text()).not.toContain('foreign-watch');
  expect(wrapper.text()).toContain('结果仍未确认');
  wrapper.unmount();await vi.advanceTimersByTimeAsync(20000);
  expect(getResearchReceipts).toHaveBeenCalledTimes(2);
});
it('retains known state during transport failure without offering write retry', async () => {
  vi.useFakeTimers();
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','original-watch'))
    .mockRejectedValueOnce(new Error('private transport detail'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  await wrapper.get('button').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('original-watch');expect(wrapper.text()).toContain('暂时无法读取');
  expect(wrapper.text()).not.toContain('private transport');expect(wrapper.findAll('button')).toHaveLength(1);
  wrapper.unmount();
});
