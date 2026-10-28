import { afterEach, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import Panel from './ResearchReceiptPanel.vue';
import { getResearchReceipts, ResearchRequestError } from '@/api/research';
vi.mock('@/api/research', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/research')>(),
  getResearchReceipts: vi.fn(),
}));
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
  const secondRefreshTime = wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime');
  resolve(reply('first','foreign-watch'));await flushPromises();
  expect(wrapper.text()).toContain('second-watch');expect(wrapper.text()).not.toContain('foreign-watch');
  expect(wrapper.text()).toContain('结果仍未确认');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime')).toBe(secondRefreshTime);
  wrapper.unmount();await vi.advanceTimersByTimeAsync(20000);
  expect(getResearchReceipts).toHaveBeenCalledTimes(2);
});

it('ignores a late login failure from the previous conversation', async () => {
  vi.useFakeTimers();
  let rejectFirst!: (error: Error) => void;
  vi.mocked(getResearchReceipts).mockImplementationOnce(() => new Promise((_, reject) => { rejectFirst = reject; }))
    .mockResolvedValueOnce(reply('second','current-watch'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});
  await wrapper.setProps({conversationId:'second'});await flushPromises();
  const lastSuccess = wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime');
  rejectFirst(new ResearchRequestError('session is not valid', 403, 'session_invalid'));
  await flushPromises();
  expect(wrapper.text()).toContain('current-watch');
  expect(wrapper.text()).not.toContain('登录已失效');
  expect(wrapper.text()).not.toContain('暂时无法读取');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime')).toBe(lastSuccess);
  wrapper.unmount();
});

it('retains known state during transport failure without offering write retry', async () => {
  vi.useFakeTimers();
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','original-watch'))
    .mockRejectedValueOnce(new Error('private transport detail'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  const lastSuccess = wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime');
  await wrapper.get('button').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('original-watch');expect(wrapper.text()).toContain('暂时无法读取');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime')).toBe(lastSuccess);
  expect(wrapper.text()).not.toContain('private transport');expect(wrapper.findAll('button')).toHaveLength(1);
  wrapper.unmount();
});

it.each([
  [401, 'session_invalid'],
  [403, 'product_authentication_required'],
] as const)('preserves receipts and stops polling after an explicit login failure (%s %s)', async (status, code) => {
  vi.useFakeTimers();
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','original-watch'))
    .mockRejectedValueOnce(new ResearchRequestError('session is not valid', status, code));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  const lastSuccess = wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime');
  await wrapper.get('button').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('original-watch');
  expect(wrapper.text()).toContain('登录已失效');
  expect(wrapper.text()).not.toContain('暂时无法读取');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime')).toBe(lastSuccess);
  expect(wrapper.get('a').attributes('href')).toBe(`/login?redirect=${encodeURIComponent('/agent?session=first')}`);
  await vi.advanceTimersByTimeAsync(20000);
  expect(getResearchReceipts).toHaveBeenCalledTimes(2);
  wrapper.unmount();
});

it('does not classify an unrelated 403 as an expired login and keeps retrying', async () => {
  vi.useFakeTimers();
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','original-watch'))
    .mockRejectedValueOnce(new ResearchRequestError('forbidden', 403, 'product_forbidden'))
    .mockRejectedValueOnce(new Error('temporary failure'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  await wrapper.get('button').trigger('click');await flushPromises();
  expect(wrapper.text()).toContain('original-watch');
  expect(wrapper.text()).toContain('暂时无法读取');
  expect(wrapper.text()).not.toContain('登录已失效');
  await vi.advanceTimersByTimeAsync(10000);await flushPromises();
  expect(getResearchReceipts).toHaveBeenCalledTimes(3);
  wrapper.unmount();
});

it('manual refresh fetches changed receipts and reports a successful refresh time', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-14T00:00:00.000Z'));
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','before-watch'))
    .mockResolvedValueOnce(reply('first','after-watch'));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  vi.setSystemTime(new Date('2026-10-14T00:01:00.000Z'));
  await wrapper.get('button').trigger('click');
  expect(getResearchReceipts).toHaveBeenCalledTimes(2);
  await flushPromises();
  expect(wrapper.text()).toContain('after-watch');expect(wrapper.text()).not.toContain('before-watch');
  expect(wrapper.text()).toContain('核对记录已刷新');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime'))
    .toBe('2026-10-14T00:01:00.000Z');
  wrapper.unmount();
});

it('reports completion when a manual refresh returns unchanged receipts', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-14T00:02:00.000Z'));
  const unchanged = reply('first','same-watch');
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(unchanged).mockResolvedValueOnce(unchanged);
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  vi.setSystemTime(new Date('2026-10-14T00:03:00.000Z'));
  await wrapper.get('button').trigger('click');await flushPromises();
  expect(getResearchReceipts).toHaveBeenCalledTimes(2);
  expect(wrapper.text()).toContain('same-watch');expect(wrapper.text()).toContain('核对记录已刷新');
  expect(wrapper.get('[data-test="last-successful-refresh"]').attributes('datetime'))
    .toBe('2026-10-14T00:03:00.000Z');
  wrapper.unmount();
});

it('shows loading feedback while the manual refresh request is pending', async () => {
  vi.useFakeTimers();
  let resolve!: (value: ReturnType<typeof reply>) => void;
  vi.mocked(getResearchReceipts).mockResolvedValueOnce(reply('first','known-watch'))
    .mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const wrapper=mount(Panel,{props:{conversationId:'first'}});await flushPromises();
  await wrapper.get('button').trigger('click');
  expect(wrapper.text()).toContain('正在刷新核对记录');
  expect((wrapper.get('button').element as HTMLButtonElement).disabled).toBe(true);
  resolve(reply('first','known-watch'));await flushPromises();
  expect(wrapper.text()).toContain('核对记录已刷新');
  wrapper.unmount();
});
