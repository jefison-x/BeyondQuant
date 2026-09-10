import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import ContinuationPermissionPanel from './ContinuationPermissionPanel.vue';

const { read, confirm, revoke } = vi.hoisted(() => ({ read: vi.fn(), confirm: vi.fn(), revoke: vi.fn() }));
vi.mock('@/api/research', () => ({ getContinuationPermission: read,
  confirmContinuationPermission: confirm, revokeContinuationPermission: revoke }));
const missing = { task_id: 'task-one', permission: null, can_start: false, blocked_reason: 'permission_missing' };
const global = { renderStubDefaultSlot: true, directives: { loading: () => {} }, stubs: {
  ElAlert: true, ElButton: true, ElForm: true, ElFormItem: true, ElOption: true,
  ElSelect: true, ElCheckbox: true,
  ElInputNumber: { name: 'ElInputNumber', props: ['modelValue'], template: '<input />' },
} };
beforeEach(() => { vi.resetAllMocks(); read.mockResolvedValue(missing); });

it('does not create permission on load or invent a default allowance', async () => {
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await flushPromises();
  expect(confirm).not.toHaveBeenCalled();
  expect(wrapper.findComponent({ name: 'ElInputNumber' }).props('modelValue')).toBeUndefined();
  expect(wrapper.text()).toContain('尚未授权');
  wrapper.unmount();
});

it('displays unconfirmed liabilities without claiming automatic execution', async () => {
  read.mockResolvedValue({ ...missing, permission: { grant_version: 1, token_limit: 1000,
    expires_at: '2026-09-11T00:00:00Z', revoked_at: null }, blocked_reason: 'continuation_result_unconfirmed',
    budget: { available_tokens: 400, reserved_tokens: 600, charged_tokens: 0, turns_remaining: 7 } });
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await flushPromises();
  expect(wrapper.text()).toContain('上次执行结果尚未确认');
  expect(wrapper.text()).toContain('已预留：600');
  expect(wrapper.find('[role="status"]').text()).not.toContain('许可有效');
  wrapper.unmount();
});

it('late read for a previously selected task cannot overwrite the current task', async () => {
  let resolveOld: (value: unknown) => void = () => {};
  read.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  read.mockResolvedValueOnce({ ...missing, task_id: 'task-two', blocked_reason: 'permission_expired' });
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await wrapper.setProps({ taskId: 'task-two' });
  await flushPromises();
  resolveOld(missing);
  await flushPromises();
  expect(wrapper.text()).toContain('许可已到期');
  expect(wrapper.text()).not.toContain('尚未授权');
  wrapper.unmount();
});
