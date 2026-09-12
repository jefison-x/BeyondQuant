import { flushPromises, shallowMount } from '@vue/test-utils';
import { expect, it, vi } from 'vitest';
import TaskHandoffPanel from './TaskHandoffPanel.vue';
const read = vi.hoisted(() => vi.fn());
vi.mock('@/api/research', () => ({ getTaskHandoff: read }));
const options = { global: { stubs: { ElButton: true } }, props: { taskId: 'task-one' } };
const view = (id: string) => ({ schema_version: 'research-task-handoff.v1', task_id: id,
  objective: id, state: 'needs_permission', reason: 'permission_missing', progress: {}, references: [] });
it('ignores a late response for the previous task', async () => {
  let resolveOld!: (value: unknown) => void;
  read.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  read.mockResolvedValueOnce(view('task-two'));
  const wrapper = shallowMount(TaskHandoffPanel, options);
  await wrapper.setProps({ taskId: 'task-two' });
  await flushPromises();
  resolveOld(view('task-one'));
  await flushPromises();
  expect(wrapper.text()).toContain('task-two');
  expect(wrapper.text()).not.toContain('task-one');
  expect(wrapper.text()).toContain('尚未授权后台续接');
  wrapper.unmount();
});
it('rejects a mismatched task response instead of displaying its objective', async () => {
  read.mockResolvedValueOnce(view('foreign-task'));
  const wrapper = shallowMount(TaskHandoffPanel, options);
  await flushPromises();
  expect(wrapper.text()).toContain('交接记录与当前任务不一致');
  expect(wrapper.text()).not.toContain('foreign-task');
  wrapper.unmount();
});
