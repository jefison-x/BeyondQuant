import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import ContinuationPermissionPanel from './ContinuationPermissionPanel.vue';

const { read, confirm, revoke } = vi.hoisted(() => ({ read: vi.fn(), confirm: vi.fn(), revoke: vi.fn() }));
vi.mock('@/api/research', () => ({ getContinuationPermission: read,
  confirmContinuationPermission: confirm, revokeContinuationPermission: revoke }));

const binding = { profile_id: 'task-ready-read.v1', profile_version: 1, profile_sha256: 'a'.repeat(64) };
const limits = {
  max_provider_calls: 16, max_attempts: 16, max_concurrent: 1,
  max_input_bytes: 262144, max_total_input_bytes: 4194304,
  max_output_tokens: 8192, max_total_output_tokens: 131072,
  max_tool_payload_bytes: 65536, max_total_tool_payload_bytes: 1048576,
  max_tool_calls: 16, deadline_ms: 180000,
};
const missingV2 = {
  schema_version: 'task-continuation-permission.v2', task_id: 'task-one', can_start: false,
  blocked_reason: 'permission_missing',
  available_profile: { execution_profile: binding, request_limits: limits },
  permission: null,
  request_state: { requests_reserved: 0, requests_remaining: 1, unconfirmed_requests: 0, request_usage: null },
};
const activeV2 = {
  ...missingV2, blocked_reason: 'waiting_for_event', available_profile: null,
  permission: { schema_version: 'task-continuation-permission.v2', grant_version: 1,
    confirmation_id: 'confirm-key',
    execution_profile: binding, request_limits: limits, max_turns: 1, turn_timeout_seconds: 86400,
    confirmed_artifact_ids: ['artifact-strategy'], expires_at: '2026-10-02T00:00:00Z', revoked_at: null },
  request_state: { requests_reserved: 0, requests_remaining: 1, unconfirmed_requests: 0, request_usage: null },
};
const legacy = {
  schema_version: 'task-continuation-permission.v1', task_id: 'task-one', can_start: false,
  blocked_reason: 'legacy_continuation_read_only',
  permission: { grant_version: 4, token_limit: 1000, max_turns: 8,
    expires_at: '2026-09-11T00:00:00Z', revoked_at: null },
  budget: { available_tokens: 400, reserved_tokens: 600, charged_tokens: 0,
    turns_remaining: 7, unconfirmed_reservations: 1, reserved_token_ceiling: 600,
    actual_usage: { input_tokens: null, output_tokens: null } },
};

const global = { renderStubDefaultSlot: true, directives: { loading: () => {} }, stubs: {
  ElAlert: { props: ['title'], template: '<p role="alert">{{ title }}</p>' },
  ElButton: { props: ['disabled', 'nativeType', 'type'], template: '<button :disabled="disabled" :type="nativeType || \'button\'"><slot /></button>' },
  ElForm: { props: ['labelPosition'], template: '<form @submit="$emit(\'submit\', $event)"><slot /></form>' },
  ElFormItem: { props: ['label'], template: '<div><slot /></div>' },
  ElOption: true,
  ElSelect: { name: 'ElSelect', props: ['modelValue'], emits: ['update:modelValue'], template: '<div />' },
  ElCheckbox: { name: 'ElCheckbox', props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<div />' },
} };

const strategyArtifacts = [
  { artifact_id: 'artifact-strategy', task_id: 'task-one', kind: 'strategy_version', status: 'validated' },
  { artifact_id: 'artifact-ml-strategy', task_id: 'task-one', kind: 'ml_strategy_version', status: 'validated' },
  { artifact_id: 'artifact-code', task_id: 'task-one', kind: 'strategy_code', status: 'validated' },
  { artifact_id: 'artifact-other-task', task_id: 'task-two', kind: 'strategy_version', status: 'validated' },
];

beforeEach(() => { vi.resetAllMocks(); read.mockResolvedValue(missingV2); });

it('loads the trusted profile without creating a grant or inventing limits', async () => {
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await flushPromises();
  expect(read).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
  expect(wrapper.text()).toContain('task-ready-read.v1 v1');
  expect(wrapper.text()).toContain('模型请求次数：16');
  expect(wrapper.text()).toContain('总输入：4194304 字节');
  expect(wrapper.text()).toContain('总输出：131072 token');
  expect(wrapper.text()).not.toContain('任务累计 token 额度');
  expect(wrapper.text()).not.toContain('最多 8 个后台回合');
  expect(wrapper.find('input[type="number"]').exists()).toBe(false);
  wrapper.unmount();
});

it('does not show an authorization form when Backend has not supplied trusted limits', async () => {
  read.mockResolvedValue({ ...missingV2, available_profile: null });
  const wrapper = shallowMount(ContinuationPermissionPanel, {
    global, props: { taskId: 'task-one', artifacts: strategyArtifacts },
  });
  await flushPromises();
  expect(wrapper.text()).toContain('尚未提供可核对的可信请求档案');
  expect(wrapper.find('form').exists()).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
  wrapper.unmount();
});

it('submits only the selected validated strategy version and the closed profile payload', async () => {
  confirm.mockImplementation(async (_taskId, payload) => ({
    ...activeV2, permission: { ...activeV2.permission, confirmation_id: payload.idempotency_key },
  }));
  const wrapper = shallowMount(ContinuationPermissionPanel, {
    global, props: { taskId: 'task-one', artifacts: strategyArtifacts },
  });
  await flushPromises();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', ['artifact-code', 'artifact-other-task']);
  wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true);
  await flushPromises();
  expect(wrapper.find('form button[type="submit"]').attributes('disabled')).toBeDefined();
  expect(confirm).not.toHaveBeenCalled();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', ['artifact-strategy']);
  await flushPromises();
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  expect(confirm).toHaveBeenCalledOnce();
  const [taskId, payload] = confirm.mock.calls[0];
  expect(taskId).toBe('task-one');
  expect(payload).toMatchObject({
    confirmed_artifact_ids: ['artifact-strategy'],
    execution_profile_id: 'task-ready-read.v1',
  });
  expect(payload.idempotency_key).toEqual(expect.any(String));
  expect(payload).not.toHaveProperty('token_limit');
  expect(payload).not.toHaveProperty('max_turns');
  expect(payload.confirmed_artifact_ids).not.toContain('artifact-code');
  expect(payload.confirmed_artifact_ids).not.toContain('artifact-other-task');
  expect(wrapper.text()).toContain('许可到期');
  wrapper.unmount();
});

it('keeps an unknown grant locked after GET null and reconciles a later exact commit', async () => {
  confirm.mockRejectedValueOnce(new Error('connection closed'));
  read.mockResolvedValueOnce(missingV2).mockResolvedValueOnce(missingV2);
  const wrapper = shallowMount(ContinuationPermissionPanel, {
    global, props: { taskId: 'task-one', artifacts: strategyArtifacts },
  });
  await flushPromises();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', ['artifact-strategy']);
  wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true);
  await flushPromises();
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  expect(confirm).toHaveBeenCalledOnce();
  expect(wrapper.text()).toContain('不会自动重发');
  expect(wrapper.find('form button[type="submit"]').attributes('disabled')).toBeDefined();
  await wrapper.find('[data-test="refresh-permission"]').trigger('click');
  await flushPromises();
  expect(read).toHaveBeenCalledTimes(2);
  expect(wrapper.text()).toContain('不会自动重发');
  expect(wrapper.find('form button[type="submit"]').attributes('disabled')).toBeDefined();
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  expect(confirm).toHaveBeenCalledOnce();

  const confirmationId = confirm.mock.calls[0][1].idempotency_key;
  read.mockResolvedValueOnce({ ...activeV2, permission: { ...activeV2.permission, confirmation_id: confirmationId } });
  await wrapper.find('[data-test="refresh-permission"]').trigger('click');
  await flushPromises();
  expect(read).toHaveBeenCalledTimes(3);
  expect(wrapper.find('form').exists()).toBe(false);
  expect(wrapper.text()).toContain('请求档案：task-ready-read.v1');
  expect(confirm).toHaveBeenCalledOnce();
  wrapper.unmount();
});

it('keeps unknown revoke locked until readonly state confirms the exact version is revoked', async () => {
  read.mockResolvedValueOnce(legacy).mockResolvedValueOnce(legacy);
  revoke.mockRejectedValueOnce(new Error('connection closed'));
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await flushPromises();
  expect(wrapper.text()).toContain('旧版许可与预算记录仅供查看');
  expect(wrapper.text()).toContain('历史预算记录：可用 400；预留 600；记账 0 token');
  expect(wrapper.find('form').exists()).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
  await wrapper.findAll('button').find(button => button.text().includes('撤销旧版许可'))!.trigger('click');
  await flushPromises();
  expect(revoke).toHaveBeenCalledWith('task-one', 4);
  expect(wrapper.text()).toContain('不会自动重发');
  await wrapper.find('[data-test="refresh-permission"]').trigger('click');
  await flushPromises();
  expect(revoke).toHaveBeenCalledOnce();
  expect(wrapper.findAll('button').find(button => button.text().includes('撤销旧版许可'))!.attributes('disabled')).toBeDefined();
  expect(wrapper.text()).toContain('不会自动重发');

  read.mockResolvedValueOnce({ ...legacy, permission: { ...legacy.permission, revoked_at: '2026-10-01T00:00:00Z' } });
  await wrapper.find('[data-test="refresh-permission"]').trigger('click');
  await flushPromises();
  expect(wrapper.text()).not.toContain('不会自动重发');
  expect(wrapper.findAll('button').some(button => button.text().includes('撤销旧版许可'))).toBe(false);
  expect(revoke).toHaveBeenCalledOnce();
  wrapper.unmount();
});

it('shows unknown actual usage without substituting the request ceiling', async () => {
  read.mockResolvedValue({
    ...activeV2,
    request_state: { requests_reserved: 1, requests_remaining: 0, unconfirmed_requests: 0,
      request_usage: { schema_version: 'continuation-request-usage.v1', execution_profile: binding, request_limits: limits,
        admission_usage: { provider_calls: 2, provider_attempts: 2, input_bytes: 1200, declared_output_tokens: 200,
          tool_payload_bytes: 300, max_input_bytes: 600, max_declared_output_tokens: 100,
          max_tool_payload_bytes: 200, tool_calls: 1, max_concurrent: 1, elapsed_ms: 4500 },
        actual_usage: { input_tokens: 'unknown', cache_read_tokens: 'unknown', output_tokens: 'unknown',
          provider_attempts: 'unknown', usage_source: 'unknown', completeness: 'unknown' }, limit_violations: [] } },
  });
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await flushPromises();
  expect(wrapper.text()).toContain('实际用量：输入 未知 token，缓存读取 未知 token');
  expect(wrapper.text()).toContain('输出 未知 token；模型尝试 未知 次');
  expect(wrapper.text()).toContain('完整性：未知');
  expect(wrapper.text()).not.toContain('实际用量：输入 16');
  wrapper.unmount();
});

it('late read for a previously selected task cannot overwrite the current task', async () => {
  let resolveOld: (value: unknown) => void = () => {};
  read.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  read.mockResolvedValueOnce({ ...missingV2, task_id: 'task-two', blocked_reason: 'permission_expired' });
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: 'task-one', artifacts: [] } });
  await wrapper.setProps({ taskId: 'task-two' });
  await flushPromises();
  resolveOld(missingV2);
  await flushPromises();
  expect(wrapper.text()).toContain('许可已到期');
  expect(wrapper.text()).not.toContain('尚未授权后台续接');
  wrapper.unmount();
});
