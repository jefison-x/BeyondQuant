import { flushPromises, shallowMount } from '@vue/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from '@/stores/auth';
import ContinuationPermissionPanel from './ContinuationPermissionPanel.vue';

const { read, getEntity, revoke, submitRequest, confirmRevoke } = vi.hoisted(() => ({
  read: vi.fn(), getEntity: vi.fn(), revoke: vi.fn(), submitRequest: vi.fn(), confirmRevoke: vi.fn(),
}));
vi.mock('@/api/research', () => ({ getContinuationPermission: read, getResearchEntity: getEntity,
  revokeContinuationPermission: revoke }));
vi.mock('@/api/approvalRequestSubmissions', () => ({ submitProductApprovalRequestOnce: submitRequest }));
vi.mock('element-plus', () => ({ ElMessageBox: { confirm: (...args: unknown[]) => confirmRevoke(...args) } }));

const binding = { profile_id: 'task-ready-read.v1', profile_version: 1, profile_sha256: 'a'.repeat(64) };
const limits = {
  max_provider_calls: 16, max_attempts: 16, max_concurrent: 1,
  max_input_bytes: 262144, max_total_input_bytes: 4194304,
  max_output_tokens: 8192, max_total_output_tokens: 131072,
  max_tool_payload_bytes: 65536, max_total_tool_payload_bytes: 1048576,
  max_tool_calls: 16, deadline_ms: 180000,
};
const TASK_ONE = `task_${'1'.repeat(32)}`;
const TASK_TWO = `task_${'2'.repeat(32)}`;
const ARTIFACT_STRATEGY = `artifact_${'a'.repeat(32)}`;
const ARTIFACT_ML_STRATEGY = `artifact_${'b'.repeat(32)}`;
const ARTIFACT_CODE = `artifact_${'c'.repeat(32)}`;
const ARTIFACT_OTHER_TASK = `artifact_${'d'.repeat(32)}`;
const ARTIFACT_OTHER_SCOPE = `artifact_${'e'.repeat(32)}`;
const missingV2 = {
  schema_version: 'task-continuation-permission.v2', task_id: TASK_ONE, can_start: false,
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
    confirmed_artifact_ids: [ARTIFACT_STRATEGY], expires_at: '2026-10-02T00:00:00Z', revoked_at: null },
  request_state: { requests_reserved: 0, requests_remaining: 1, unconfirmed_requests: 0, request_usage: null },
};
const legacy = {
  schema_version: 'task-continuation-permission.v1', task_id: TASK_ONE, can_start: false,
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
  { artifact_id: ARTIFACT_STRATEGY, task_id: TASK_ONE, owner_principal: 'alice', workspace_id: 'workspace-alice', kind: 'strategy_version', status: 'validated' },
  { artifact_id: ARTIFACT_ML_STRATEGY, task_id: TASK_ONE, owner_principal: 'alice', workspace_id: 'workspace-alice', kind: 'ml_strategy_version', status: 'validated' },
  { artifact_id: ARTIFACT_CODE, task_id: TASK_ONE, owner_principal: 'alice', workspace_id: 'workspace-alice', kind: 'strategy_code', status: 'validated' },
  { artifact_id: ARTIFACT_OTHER_TASK, task_id: TASK_TWO, owner_principal: 'alice', workspace_id: 'workspace-alice', kind: 'strategy_version', status: 'validated' },
  { artifact_id: ARTIFACT_OTHER_SCOPE, task_id: TASK_ONE, owner_principal: 'bob', workspace_id: 'workspace-bob', kind: 'strategy_version', status: 'validated' },
];

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
  useAuthStore().setUser({ subject: 'alice', workspace: { workspace_id: 'workspace-alice' } } as any);
  read.mockResolvedValue(missingV2);
  getEntity.mockReset();
  confirmRevoke.mockResolvedValue('confirmed');
});

it('loads the trusted profile without creating a grant or inventing limits', async () => {
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
  await flushPromises();
  expect(read).toHaveBeenCalledOnce();
  expect(submitRequest).not.toHaveBeenCalled();
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
    global, props: { taskId: TASK_ONE, artifacts: strategyArtifacts },
  });
  await flushPromises();
  expect(wrapper.text()).toContain('尚未提供可核对的可信请求档案');
  expect(wrapper.find('form').exists()).toBe(false);
  expect(submitRequest).not.toHaveBeenCalled();
  wrapper.unmount();
});

it('creates only a typed pending request for the selected validated strategy version', async () => {
  submitRequest.mockResolvedValue({ reconciled: false, request: {
    request_id: `approval_request_${'1'.repeat(32)}`,
    request_type: 'continuation_consent', status: 'pending',
    owner_principal: 'alice', workspace_id: 'workspace-alice', task_id: TASK_ONE,
    resource_artifact_id: null, content_sha256: 'e'.repeat(64), request_key: '00000000-0000-4000-8000-000000000006',
    created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:00Z',
    conversation_id: `conversation_${'1'.repeat(32)}`,
    confirmed_artifacts: [{ artifact_id: ARTIFACT_STRATEGY, content_sha256: 'a'.repeat(64), kind: 'strategy_version' }],
    execution_profile_id: 'task-ready-read.v1', request_limits: limits,
  } });
  const wrapper = shallowMount(ContinuationPermissionPanel, {
    global, props: { taskId: TASK_ONE, artifacts: strategyArtifacts },
  });
  await flushPromises();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', [ARTIFACT_CODE, ARTIFACT_OTHER_TASK, ARTIFACT_OTHER_SCOPE]);
  wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true);
  await flushPromises();
  expect(wrapper.find('form button[type="submit"]').attributes('disabled')).toBeDefined();
  expect(submitRequest).not.toHaveBeenCalled();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', [ARTIFACT_STRATEGY]);
  await flushPromises();
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  expect(submitRequest).toHaveBeenCalledOnce();
  const [scope, payload] = submitRequest.mock.calls[0];
  expect(scope).toEqual({ ownerPrincipal: 'alice', workspaceId: 'workspace-alice' });
  expect(payload).toMatchObject({
    schema_version: 'byq-product-approval-request.v1',
    request_type: 'continuation_consent',
    task_id: TASK_ONE,
    confirmed_artifact_ids: [ARTIFACT_STRATEGY],
    execution_profile_id: 'task-ready-read.v1',
  });
  expect(payload).not.toHaveProperty('request_key');
  expect(payload).not.toHaveProperty('token_limit');
  expect(payload).not.toHaveProperty('max_turns');
  expect(payload.confirmed_artifact_ids).not.toContain(ARTIFACT_CODE);
  expect(payload.confirmed_artifact_ids).not.toContain(ARTIFACT_OTHER_TASK);
  expect(payload.confirmed_artifact_ids).not.toContain(ARTIFACT_OTHER_SCOPE);
  expect(wrapper.text()).toContain('当前没有创建许可或启动请求');
  wrapper.unmount();
});

it('reports an unknown request without creating a grant or starting continuation', async () => {
  submitRequest.mockRejectedValueOnce(new Error('申请提交结果尚未确认；原申请键已保留'));
  const wrapper = shallowMount(ContinuationPermissionPanel, {
    global, props: { taskId: TASK_ONE, artifacts: strategyArtifacts },
  });
  await flushPromises();
  wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', [ARTIFACT_STRATEGY]);
  wrapper.findComponent({ name: 'ElCheckbox' }).vm.$emit('update:modelValue', true);
  await flushPromises();
  await wrapper.find('form').trigger('submit');
  await flushPromises();
  expect(submitRequest).toHaveBeenCalledOnce();
  expect(wrapper.text()).toContain('原申请键已保留');
  expect(wrapper.text()).not.toContain('已创建许可');
  wrapper.unmount();
});

it('keeps unknown revoke locked until readonly state confirms the exact version is revoked', async () => {
  read.mockResolvedValueOnce(legacy).mockResolvedValueOnce(legacy);
  revoke.mockRejectedValueOnce(new Error('connection closed'));
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
  await flushPromises();
  expect(wrapper.text()).toContain('旧版许可与预算记录仅供查看');
  expect(wrapper.text()).toContain('历史预算记录：可用 400；预留 600；记账 0 token');
  expect(wrapper.find('form').exists()).toBe(false);
  expect(confirmRevoke).not.toHaveBeenCalled();
  await wrapper.findAll('button').find(button => button.text().includes('撤销旧版许可'))!.trigger('click');
  await flushPromises();
  expect(confirmRevoke).toHaveBeenCalledOnce();
  expect(revoke).toHaveBeenCalledWith(TASK_ONE, 4);
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
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
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
  read.mockResolvedValueOnce({ ...missingV2, task_id: TASK_TWO, blocked_reason: 'permission_expired' });
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
  await wrapper.setProps({ taskId: TASK_TWO });
  await flushPromises();
  resolveOld(missingV2);
  await flushPromises();
  expect(wrapper.text()).toContain('许可已到期');
  expect(wrapper.text()).not.toContain('尚未授权后台续接');
  wrapper.unmount();
});

it('late permission read from a previous user and workspace cannot overwrite the current scope', async () => {
  let resolveOld: (value: unknown) => void = () => {};
  read.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  read.mockResolvedValueOnce(missingV2);
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
  useAuthStore().setUser({ subject: 'bob', workspace: { workspace_id: 'workspace-bob' } } as any);
  await flushPromises();
  resolveOld({ ...missingV2, blocked_reason: 'permission_expired' });
  await flushPromises();
  expect(read).toHaveBeenCalledTimes(2);
  expect(wrapper.text()).toContain('尚未授权后台续接');
  expect(wrapper.text()).not.toContain('许可已到期');
  wrapper.unmount();
});

it('does not send a revoke after its confirmation outlives the selected user scope', async () => {
  read.mockResolvedValue({ ...activeV2 });
  let resolveConfirmation: (value: string) => void = () => undefined;
  confirmRevoke.mockReturnValueOnce(new Promise(resolve => { resolveConfirmation = resolve; }));
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: [] } });
  await flushPromises();
  const vm = wrapper.vm as unknown as { revoke: () => Promise<void> };
  const revokeAction = vm.revoke();
  await flushPromises();
  expect(confirmRevoke).toHaveBeenCalledOnce();

  read.mockResolvedValueOnce({ ...missingV2 });
  useAuthStore().setUser({ subject: 'bob', workspace: { workspace_id: 'workspace-bob' } } as any);
  await flushPromises();
  resolveConfirmation('confirmed');
  await revokeAction;

  expect(revoke).not.toHaveBeenCalled();
  expect(wrapper.text()).toContain('尚未授权后台续接');
  wrapper.unmount();
});

it('loads a validated strategy Artifact omitted from the 200-item list by exact Product GET', async () => {
  const cappedArtifacts = Array.from({ length: 200 }, (_, index) => ({
    artifact_id: `artifact_${String(index).padStart(32, '0')}`,
    task_id: TASK_TWO, owner_principal: 'alice', workspace_id: 'workspace-alice',
    kind: 'strategy_version', status: 'validated',
  }));
  const exactArtifact = {
    artifact_id: `artifact_${'e'.repeat(32)}`, task_id: TASK_ONE,
    owner_principal: 'alice', workspace_id: 'workspace-alice',
    kind: 'strategy_version', status: 'validated', content_sha256: 'f'.repeat(64),
  };
  const wrongWorkspaceArtifact = {
    ...exactArtifact,
    artifact_id: `artifact_${'f'.repeat(32)}`,
    workspace_id: 'workspace-bob',
  };
  getEntity.mockResolvedValueOnce(exactArtifact).mockResolvedValueOnce(wrongWorkspaceArtifact);
  const wrapper = shallowMount(ContinuationPermissionPanel, { global, props: { taskId: TASK_ONE, artifacts: cappedArtifacts } });
  await flushPromises();
  expect(wrapper.text()).toContain('策略版本列表最多返回 200 项');
  const vm = wrapper.vm as unknown as {
    exactArtifactId: string;
    lookupExactArtifact: () => Promise<void>;
    eligible: Array<Record<string, unknown>>;
  };
  vm.exactArtifactId = exactArtifact.artifact_id;
  await vm.lookupExactArtifact();
  expect(getEntity).toHaveBeenCalledWith('artifacts', exactArtifact.artifact_id);
  expect(vm.eligible).toContainEqual(exactArtifact);
  vm.exactArtifactId = wrongWorkspaceArtifact.artifact_id;
  await vm.lookupExactArtifact();
  expect(vm.eligible).not.toContainEqual(wrongWorkspaceArtifact);
  expect(wrapper.text()).toContain('与当前用户、工作区、任务或可用策略版本不匹配');
  wrapper.unmount();
});
