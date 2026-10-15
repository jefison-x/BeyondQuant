import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessageBox } from "element-plus";
import { AgentRequestError } from "@/api/agent";
import type { AgentExecutionOptions } from "@/api/agent";
import AgentView from "./AgentView.vue";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const submitTurn = vi.fn();
const cancelSession = vi.fn();
const resumeSession = vi.fn();
const getAgentSession = vi.fn();
const getAgentExecutionOptions = vi.fn();
const updateAgentExecutionOptions = vi.fn();
const createAgentSession = vi.fn();
const deleteAgentSession = vi.fn();
const listAgentSessions = vi.fn();
const updateAgentSession = vi.fn();
const continueApproval = vi.fn();
const streamWorkflowEvents = vi.fn();
const routerHarness = vi.hoisted(() => ({
  route: { path: "/agent", query: {} as Record<string, unknown> },
  proxy: null as any,
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/api/research", () => ({ continueApproval: (...args: unknown[]) => continueApproval(...args) }));

vi.mock("vue-router", async () => {
  const { reactive } = await import("vue");
  routerHarness.replace.mockImplementation((location: { path: string; query?: Record<string, unknown> }) => {
    routerHarness.route.path = location.path;
    routerHarness.route.query = location.query ?? {};
    routerHarness.proxy.path = location.path;
    routerHarness.proxy.query = { ...routerHarness.route.query };
    return Promise.resolve();
  });
  return {
    useRoute: () => {
      routerHarness.proxy = reactive({ path: routerHarness.route.path, query: { ...routerHarness.route.query } });
      return routerHarness.proxy;
    },
    useRouter: () => ({ replace: routerHarness.replace, push: routerHarness.push }),
  };
});

vi.mock("@/api/agent", () => ({
  AGENT_EXECUTION_OPTIONS_SCHEMA: "agent-execution-options.v1",
  AgentRequestError: class AgentRequestError extends Error {
    constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
  },
  cancelSession: (...args: unknown[]) => cancelSession(...args),
  createAgentSession: (...args: unknown[]) => createAgentSession(...args),
  deleteAgentSession: (...args: unknown[]) => deleteAgentSession(...args),
  getAgentSession: (...args: unknown[]) => getAgentSession(...args),
  getAgentExecutionOptions: (...args: unknown[]) => getAgentExecutionOptions(...args),
  listAgentSessions: (...args: unknown[]) => listAgentSessions(...args),
  resumeSession: (...args: unknown[]) => resumeSession(...args),
  streamWorkflowEvents: (...args: unknown[]) => streamWorkflowEvents(...args),
  submitTurn: (...args: unknown[]) => submitTurn(...args),
  updateAgentSession: (...args: unknown[]) => updateAgentSession(...args),
  updateAgentExecutionOptions: (...args: unknown[]) => updateAgentExecutionOptions(...args),
}));

const defaultExecutionOptions = () => ({
  auto_continue: true,
  max_provider_calls: null,
  max_provider_attempts: null,
  max_tool_calls: null,
  max_concurrent_provider_calls: null,
  max_input_bytes_per_call: null,
  max_input_bytes_total: null,
  max_output_tokens_per_call: null,
  max_output_tokens_total: null,
  max_tool_payload_bytes_per_call: null,
  max_tool_payload_bytes_total: null,
  max_continuations: null,
  max_runtime_seconds: null,
  max_no_progress_seconds: null,
  max_child_runtime_seconds: null,
  max_child_no_progress_seconds: null,
});

const executionOptionsRecord = (
  conversationId = "session-1",
  revision = 0,
  options: AgentExecutionOptions = defaultExecutionOptions(),
) => ({
  schema_version: "agent-execution-options.v1" as const,
  conversation_id: conversationId,
  owner_principal: "alice",
  workspace_id: "workspace-alice",
  revision,
  options,
  updated_at: null,
});

describe("AgentView", () => {
  beforeEach(() => {
    routerHarness.route.path = "/agent";
    routerHarness.route.query = {};
    routerHarness.proxy = null;
    routerHarness.replace.mockClear();
    routerHarness.push.mockClear();
    continueApproval.mockReset();
    streamWorkflowEvents.mockReset();
    streamWorkflowEvents.mockImplementation(() => new Promise<void>(() => undefined));
    setActivePinia(createPinia());
    useAuthStore().setUser({
      subject: "alice",
      display_name: "量化小周",
      workspace: {
        contract: "personal-workspace.v1",
        workspace_id: "workspace-alice",
        kind: "personal",
        display_name: "Alice 的个人工作区",
        role: "owner",
      },
    });
    submitTurn.mockReset();
    submitTurn.mockResolvedValue({ status: "accepted" });
    cancelSession.mockReset();
    cancelSession.mockResolvedValue({ status: "cancelled" });
    resumeSession.mockReset();
    resumeSession.mockResolvedValue({ status: "ready" });
    getAgentSession.mockReset();
    getAgentSession.mockResolvedValue({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "测试会话" },
      messages: [{ message_id: "message-1", sequence: 1, role: "user", content: "已有问题", created_at: "2026-08-28T00:00:00Z" }],
      events: [],
    });
    getAgentExecutionOptions.mockReset();
    getAgentExecutionOptions.mockResolvedValue(executionOptionsRecord());
    updateAgentExecutionOptions.mockReset();
    updateAgentExecutionOptions.mockImplementation((_conversationId, payload) => Promise.resolve(
      executionOptionsRecord("session-1", payload.expected_revision + 1, payload.options),
    ));
    createAgentSession.mockReset();
    createAgentSession.mockResolvedValue({ session_id: "session-1", trace_id: "trace-1", title: "测试会话" });
    deleteAgentSession.mockReset();
    deleteAgentSession.mockResolvedValue({ status: "deleted" });
    listAgentSessions.mockReset();
    listAgentSessions.mockResolvedValue({
      sessions: [{ session_id: "session-1", trace_id: "trace-1", title: "测试会话" }],
      total: 1,
    });
    updateAgentSession.mockReset();
    updateAgentSession.mockResolvedValue({ session: {} });
  });

  it("stops unknown approval continuation instead of retrying a write", async () => {
    continueApproval.mockResolvedValue({ approval: { continuation_status: "outcome_unknown" } });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const vm = wrapper.vm as any;
    await vm.retryApprovalContinuation("approval-synthetic");
    expect(continueApproval).toHaveBeenCalledTimes(1);
    expect(vm.error).toContain("不会自动重发");
    expect(vm.approvalContinuationTimer).toBeNull();
    wrapper.unmount();
  });

  it("bounds approval polling even when the service keeps returning queued", async () => {
    continueApproval.mockResolvedValue({ approval: { continuation_status: "queued" } });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const vm = wrapper.vm as any;
    for (let attempt = 0; attempt < 10; attempt++) await vm.retryApprovalContinuation("approval-synthetic");
    expect(continueApproval).toHaveBeenCalledTimes(8);
    expect(vm.error).toContain("核对次数已用尽");
    wrapper.unmount();
  });

  it("ignores approval acknowledgements after the view is unmounted", async () => {
    let resolveReceipt: (value: unknown) => void = () => undefined;
    continueApproval.mockReturnValue(new Promise(resolve => { resolveReceipt = resolve; }));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const vm = wrapper.vm as any;
    const pending = vm.retryApprovalContinuation("approval-synthetic");
    wrapper.unmount();
    resolveReceipt({ approval: { continuation_status: "outcome_unknown" } });
    await pending;
    expect(vm.error).not.toContain("续接结果尚未确认");
    expect(vm.approvalContinuationTimer).toBeNull();
  });

  it("shows the personalized nickname and sends with Ctrl+Enter", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(wrapper.find(".conversation-message.user .message-author").text()).toBe("量化小周");

    (wrapper.vm as unknown as { prompt: string }).prompt = "快捷发送";
    const event = new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, isComposing: true, cancelable: true });
    (wrapper.vm as unknown as { handleComposerKeydown: (event: KeyboardEvent) => void }).handleComposerKeydown(event);
    await flushPromises();

    expect(event.defaultPrevented).toBe(true);
    expect(submitTurn).toHaveBeenCalledWith("session-1", "快捷发送", "");
    expect(wrapper.find(".assistant-processing").exists()).toBe(true);
    expect(wrapper.find(".composer-stop").attributes("aria-label")).toBe("停止本轮");
    expect(wrapper.text()).not.toContain("Ctrl + Enter 发送");
    expect(wrapper.text()).not.toContain("关键执行仍需 BYQ 审批");
  });

  it("does not invent or save an execution option before a conversation exists", async () => {
    listAgentSessions.mockResolvedValueOnce({ sessions: [], total: 0, limit: 100, offset: 0 });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(getAgentExecutionOptions).not.toHaveBeenCalled();
    expect(updateAgentExecutionOptions).not.toHaveBeenCalled();
    expect(wrapper.find(".execution-options-switch").exists()).toBe(false);
    expect(wrapper.text()).toContain("发送第一条消息后才能读取和设置此会话选项");
    wrapper.unmount();
  });

  it("keeps the switch unavailable when the Product API settings read fails", async () => {
    getAgentExecutionOptions.mockRejectedValueOnce(new Error("settings unavailable"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;

    expect(wrapper.find(".execution-options-switch").exists()).toBe(false);
    expect(view.executionOptions).toBe(null);
    expect(wrapper.text()).toContain("自动接续状态未知；未使用本地默认值");
    await view.changeAutoContinue(false);
    expect(updateAgentExecutionOptions).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("changes only auto_continue and preserves every other option at the loaded revision", async () => {
    const currentOptions = { ...defaultExecutionOptions(), max_provider_calls: 19, max_tool_calls: 3 };
    const current = executionOptionsRecord("session-1", 7, currentOptions);
    getAgentExecutionOptions.mockResolvedValueOnce(current);
    let resolveUpdate: (value: unknown) => void = () => undefined;
    updateAgentExecutionOptions.mockReturnValueOnce(new Promise(resolve => { resolveUpdate = resolve; }));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;

    expect(getAgentExecutionOptions).toHaveBeenCalledWith("session-1", "");
    expect(view.executionOptions.options.max_provider_calls).toBe(19);
    const saving = view.changeAutoContinue(false);
    await view.changeAutoContinue(true);
    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(1);
    expect(updateAgentExecutionOptions).toHaveBeenCalledWith("session-1", {
      schema_version: "agent-execution-options.v1",
      expected_revision: 7,
      options: { ...currentOptions, auto_continue: false },
    }, "");

    resolveUpdate(executionOptionsRecord("session-1", 8, { ...currentOptions, auto_continue: false }));
    await saving;
    expect(view.executionOptions.revision).toBe(8);
    expect(view.executionOptions.options.auto_continue).toBe(false);
    expect(view.executionOptions.options.max_provider_calls).toBe(19);
    expect(view.executionOptions.options.max_tool_calls).toBe(3);
    expect(wrapper.text()).toContain("已运行任务的参数快照不变");
    wrapper.unmount();
  });

  it("refreshes authoritative options after a stale revision without replaying the PUT", async () => {
    getAgentExecutionOptions.mockReset();
    getAgentExecutionOptions
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 4, defaultExecutionOptions()))
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 5, { ...defaultExecutionOptions(), auto_continue: false }));
    updateAgentExecutionOptions.mockReset();
    updateAgentExecutionOptions.mockRejectedValueOnce(new AgentRequestError("stale revision", 409));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;

    await view.changeAutoContinue(false);

    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(1);
    expect(getAgentExecutionOptions).toHaveBeenCalledTimes(2);
    expect(view.executionOptions.revision).toBe(5);
    expect(view.executionOptions.options.auto_continue).toBe(false);
    expect(view.executionOptionsError).toContain("请再次操作");
    wrapper.unmount();
  });

  it("re-reads after an unknown PUT outcome and never automatically replays the write", async () => {
    getAgentExecutionOptions.mockReset();
    getAgentExecutionOptions
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 2, defaultExecutionOptions()))
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 3, { ...defaultExecutionOptions(), auto_continue: false }));
    updateAgentExecutionOptions.mockReset();
    updateAgentExecutionOptions.mockRejectedValueOnce(new Error("request outcome unknown"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;

    await view.changeAutoContinue(false);

    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(1);
    expect(getAgentExecutionOptions).toHaveBeenCalledTimes(2);
    expect(view.executionOptions.revision).toBe(3);
    expect(view.executionOptions.options.auto_continue).toBe(false);
    expect(view.executionOptionsError).toContain("设置保存未确认");
    wrapper.unmount();
  });

  it("ignores late settings reads and writes from a conversation after switching IDs", async () => {
    let resolveOldRead: (value: unknown) => void = () => undefined;
    let resolveOldWrite: (value: unknown) => void = () => undefined;
    getAgentExecutionOptions.mockReset();
    getAgentExecutionOptions
      .mockReturnValueOnce(new Promise(resolve => { resolveOldRead = resolve; }))
      .mockResolvedValueOnce(executionOptionsRecord("session-2", 2, { ...defaultExecutionOptions(), auto_continue: false }));
    updateAgentExecutionOptions.mockReset();
    updateAgentExecutionOptions.mockReturnValueOnce(new Promise(resolve => { resolveOldWrite = resolve; }));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;

    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-2", trace_id: "trace-2", title: "另一会话" },
      messages: [], events: [],
    });
    await view.openSession("session-2", false);
    await flushPromises();
    resolveOldRead(executionOptionsRecord("session-1", 8, defaultExecutionOptions()));
    await flushPromises();
    expect(view.executionOptions.conversation_id).toBe("session-2");

    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "原会话" },
      messages: [], events: [],
    });
    getAgentExecutionOptions.mockResolvedValueOnce(executionOptionsRecord("session-1", 8, defaultExecutionOptions()));
    await view.openSession("session-1", false);
    await flushPromises();
    const staleWrite = view.changeAutoContinue(false);
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-2", trace_id: "trace-2", title: "另一会话" },
      messages: [], events: [],
    });
    getAgentExecutionOptions.mockResolvedValueOnce(executionOptionsRecord("session-2", 3, { ...defaultExecutionOptions(), auto_continue: false }));
    await view.openSession("session-2", false);
    await flushPromises();
    resolveOldWrite(executionOptionsRecord("session-1", 9, { ...defaultExecutionOptions(), auto_continue: false }));
    await staleWrite;

    expect(view.executionOptions.conversation_id).toBe("session-2");
    expect(view.executionOptions.revision).toBe(3);
    expect(view.executionOptions.options.auto_continue).toBe(false);
    wrapper.unmount();
  });

  it("keeps saves scoped across A/B/A and rereads after a late write", async () => {
    getAgentExecutionOptions.mockReset();
    getAgentExecutionOptions
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 1))
      .mockResolvedValueOnce(executionOptionsRecord("session-2", 4, { ...defaultExecutionOptions(), auto_continue: false }))
      .mockResolvedValueOnce(executionOptionsRecord("session-1", 1));
    let resolveFirstAWrite: (value: unknown) => void = () => undefined;
    let resolveBWrite: (value: unknown) => void = () => undefined;
    let resolveAReconcile: (value: unknown) => void = () => undefined;
    updateAgentExecutionOptions.mockReset();
    updateAgentExecutionOptions
      .mockReturnValueOnce(new Promise(resolve => { resolveFirstAWrite = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { resolveBWrite = resolve; }))
      .mockImplementation((conversationId, payload) => Promise.resolve(executionOptionsRecord(
        conversationId,
        payload.expected_revision + 1,
        payload.options,
      )));

    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as any;
    const firstAWrite = view.changeAutoContinue(false);
    expect(view.executionOptionsSaving).toBe(true);

    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-2", trace_id: "trace-2", title: "另一会话" },
      messages: [], events: [],
    });
    await view.openSession("session-2", false);
    await flushPromises();
    const bWrite = view.changeAutoContinue(true);
    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(2);
    expect(view.executionOptionsSaving).toBe(true);

    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "原会话" },
      messages: [], events: [],
    });
    await view.openSession("session-1", false);
    await flushPromises();
    expect(view.executionOptionsSaving).toBe(true);
    await view.changeAutoContinue(true);
    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(2);

    getAgentExecutionOptions.mockReturnValueOnce(new Promise(resolve => { resolveAReconcile = resolve; }));
    resolveFirstAWrite(executionOptionsRecord("session-1", 2, { ...defaultExecutionOptions(), auto_continue: false }));
    await flushPromises();
    expect(getAgentExecutionOptions).toHaveBeenCalledTimes(4);
    expect(getAgentExecutionOptions).toHaveBeenLastCalledWith("session-1", "");
    expect(view.executionOptions).toBe(null);
    expect(view.executionOptionsLoading).toBe(true);
    expect(view.executionOptionsSaving).toBe(false);

    resolveAReconcile(executionOptionsRecord("session-1", 2, { ...defaultExecutionOptions(), auto_continue: false }));
    await firstAWrite;
    expect(view.executionOptions.revision).toBe(2);
    expect(view.executionOptions.options.auto_continue).toBe(false);
    expect(view.executionOptionsSavingFor.has("session-2")).toBe(true);
    await view.changeAutoContinue(true);
    expect(updateAgentExecutionOptions).toHaveBeenCalledTimes(3);
    expect(updateAgentExecutionOptions).toHaveBeenLastCalledWith("session-1", {
      schema_version: "agent-execution-options.v1",
      expected_revision: 2,
      options: { ...defaultExecutionOptions(), auto_continue: true },
    }, "");
    expect(view.executionOptions.revision).toBe(3);
    expect(view.executionOptions.options.auto_continue).toBe(true);

    resolveBWrite(executionOptionsRecord("session-2", 5, { ...defaultExecutionOptions(), auto_continue: true }));
    await bWrite;
    expect(getAgentExecutionOptions).toHaveBeenCalledTimes(4);
    expect(view.executionOptions.conversation_id).toBe("session-1");
    expect(view.executionOptions.revision).toBe(3);
    wrapper.unmount();
  });

  it("soft cancel waits for the matching discarded result, then accepts an explicit turn on the same session", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      prompt: string; send: () => Promise<void>; stopCurrentRun: () => Promise<void>;
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };
    view.prompt = "第一轮";
    await view.send();
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 2,
      timestamp: "2026-08-28T00:00:01Z", kind: "session.started", source: "runtime-adapter",
      payload: { run_id: "run-old" } }, 1);
    await view.stopCurrentRun();
    expect(cancelSession).toHaveBeenCalledWith("session-1", "soft", "");
    expect((wrapper.vm as any).error).toContain("只停止当前回复");
    expect((wrapper.vm as any).error).toContain("独立后台任务可能稍后接续");
    expect((wrapper.vm as any).error).toContain("关闭自动接续可阻止后续事件");
    expect((wrapper.vm as any).terminalSessionId).toBe("");
    expect(streamWorkflowEvents).toHaveBeenCalled();
    expect(resumeSession).not.toHaveBeenCalled();
    view.prompt = "继续";
    await view.send();
    expect(submitTurn).toHaveBeenCalledTimes(1);
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 3,
      timestamp: "2026-08-28T00:00:02Z", kind: "session.cancelled", source: "runtime-adapter",
      payload: { mode: "soft", run_id: "run-old" } }, 1);
    await view.send();
    expect(submitTurn).toHaveBeenCalledTimes(1);
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 4,
      timestamp: "2026-08-28T00:00:03Z", kind: "session.result.discarded", source: "runtime-adapter",
      payload: { reason: "soft-cancelled", run_id: "run-old" } }, 1);
    expect((wrapper.vm as any).error).toBe("");
    view.prompt = "明确的新指令";
    await view.send();
    expect(submitTurn).toHaveBeenLastCalledWith("session-1", "明确的新指令", "");
    expect(submitTurn).toHaveBeenCalledTimes(2);
    expect(resumeSession).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("reports settled when matching cancellation events arrive before the cancel response", async () => {
    let resolveCancel: (value: unknown) => void = () => undefined;
    cancelSession.mockReturnValueOnce(new Promise(resolve => { resolveCancel = resolve; }));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      prompt: string; send: () => Promise<void>; stopCurrentRun: () => Promise<void>;
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };
    view.prompt = "本轮请求";
    await view.send();
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 2,
      timestamp: "2026-08-28T00:00:01Z", kind: "session.started", source: "runtime-adapter",
      payload: { run_id: "run-race" } }, 1);
    const pendingCancel = view.stopCurrentRun();
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 3,
      timestamp: "2026-08-28T00:00:02Z", kind: "session.cancelled", source: "runtime-adapter",
      payload: { mode: "soft", run_id: "run-race" } }, 1);
    view.handleEvent({ session_id: "session-1", trace_id: "trace-1", sequence: 4,
      timestamp: "2026-08-28T00:00:03Z", kind: "session.result.discarded", source: "runtime-adapter",
      payload: { reason: "soft-cancelled", run_id: "run-race" } }, 1);
    resolveCancel({ status: "cancelled" });
    await pendingCancel;
    expect((wrapper.vm as any).softCancelPending).toBe(false);
    expect((wrapper.vm as any).stopping).toBe(false);
    expect((wrapper.vm as any).error).toContain("本轮已结算");
    expect((wrapper.vm as any).terminalSessionId).toBe("");
    wrapper.unmount();
  });

  it("replays an unsettled soft cancel as an input gate on the same conversation", async () => {
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "继续中的取消" },
      messages: [],
      events: [
        { session_id: "session-1", trace_id: "trace-1", sequence: 2, timestamp: "2026-08-28T00:00:01Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-replayed" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 3, timestamp: "2026-08-28T00:00:02Z",
          kind: "session.cancelled", source: "runtime-adapter", payload: { mode: "soft", run_id: "run-replayed" } },
      ],
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "后续指令";
    await view.send();
    expect(submitTurn).not.toHaveBeenCalled();
    expect(wrapper.vm).toMatchObject({ softCancelPending: true, terminalSessionId: "" });
    expect(streamWorkflowEvents).toHaveBeenCalled();
    wrapper.unmount();
  });

  it("replays a settled soft cancel as ready for an explicit turn on the same conversation", async () => {
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "已结算的取消" },
      messages: [],
      events: [
        { session_id: "session-1", trace_id: "trace-1", sequence: 2, timestamp: "2026-08-28T00:00:01Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-settled" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 3, timestamp: "2026-08-28T00:00:02Z",
          kind: "session.cancelled", source: "runtime-adapter", payload: { mode: "soft", run_id: "run-settled" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 4, timestamp: "2026-08-28T00:00:03Z",
          kind: "session.result.discarded", source: "runtime-adapter", payload: { reason: "soft-cancelled", run_id: "run-settled" } },
      ],
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect((wrapper.vm as any).softCancelPending).toBe(false);
    expect((wrapper.vm as any).error).toBe("");
    expect(wrapper.find(".composer-stop").exists()).toBe(false);
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "同一会话的新指令";
    await view.send();
    expect(submitTurn).toHaveBeenCalledWith("session-1", "同一会话的新指令", "");
    expect(resumeSession).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps a replayed newer run active when an older run's discard arrives late", async () => {
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "迟到的旧轮结果" },
      messages: [],
      events: [
        { session_id: "session-1", trace_id: "trace-1", sequence: 2, timestamp: "2026-08-28T00:00:01Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-old" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 3, timestamp: "2026-08-28T00:00:02Z",
          kind: "session.cancelled", source: "runtime-adapter", payload: { mode: "soft", run_id: "run-old" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 4, timestamp: "2026-08-28T00:00:03Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-current" } },
        { session_id: "session-1", trace_id: "trace-1", sequence: 5, timestamp: "2026-08-28T00:00:04Z",
          kind: "session.result.discarded", source: "runtime-adapter", payload: { reason: "soft-cancelled", run_id: "run-old" } },
      ],
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "不能打断当前轮";
    await view.send();
    expect(submitTurn).not.toHaveBeenCalled();
    expect((wrapper.vm as any).softCancelPending).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(true);
    wrapper.unmount();
  });

  it("keeps input gated when the soft-cancel request outcome is unknown", async () => {
    cancelSession.mockRejectedValueOnce(new Error("request outcome unknown"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void>; stopCurrentRun: () => Promise<void> };
    view.prompt = "原始输入";
    await view.send();
    await view.stopCurrentRun();
    view.prompt = "不可自动继续";
    await view.send();
    expect(cancelSession).toHaveBeenCalledTimes(1);
    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect((wrapper.vm as any).terminalSessionId).toBe("");
    expect((wrapper.vm as any).softCancelPending).toBe(true);
    wrapper.unmount();
  });

  it("keeps released conversation history while refusing another turn", async () => {
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "旧会话" },
      messages: [{ message_id: "m1", sequence: 1, role: "user", content: "旧消息", created_at: "2026-08-28T00:00:00Z" }],
      events: [
        { session_id: "session-1", trace_id: "trace-1", sequence: 2,
          timestamp: "2026-08-28T00:00:01Z", kind: "session.started", source: "runtime-adapter", payload: {} },
        { session_id: "session-1", trace_id: "trace-1", sequence: 3,
          timestamp: "2026-08-28T00:00:02Z", kind: "session.closed", source: "runtime-adapter", payload: { reason: "released" } },
      ],
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(wrapper.text()).toContain("旧消息");
    expect(wrapper.text()).toContain("请新建会话继续");
    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(false);
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "继续";
    await view.send();
    expect(submitTurn).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("请新建会话继续");
    wrapper.unmount();
  });

  it("stops reconnecting after the Product API reports an ended session", async () => {
    streamWorkflowEvents.mockRejectedValue(new AgentRequestError("ended", 409, "agent_session_interrupted"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(streamWorkflowEvents).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("请新建会话继续");
    wrapper.unmount();
  });

  it("does not resend after a turn is rejected because its session ended", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    submitTurn.mockRejectedValueOnce(new AgentRequestError("ended", 409, "agent_session_interrupted"));
    view.prompt = "旧会话请求";
    await view.send();
    view.prompt = "再次发送";
    await view.send();
    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("请新建会话继续");
    wrapper.unmount();
  });

  it("falls back to 我 when no nickname is available", async () => {
    const auth = useAuthStore();
    auth.setUser({ ...auth.user!, display_name: "" });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(wrapper.find(".conversation-message.user .message-author").text()).toBe("我");
  });

  it("retains maintenance-rejected input without a phantom run or duplicate bubble", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    const agent = useAgentStore();
    const before = [...agent.messages];
    view.prompt = "维护后继续这个问题";
    submitTurn.mockRejectedValueOnce(Object.assign(new Error("小巴正在维护，输入已保留，请稍后重试。"), {
      status: 503, code: "chat_maintenance",
    }));
    await view.send();
    await flushPromises();
    expect(view.prompt).toBe("维护后继续这个问题");
    expect(agent.messages).toEqual(before);
    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(false);
    expect(wrapper.text()).toContain("输入已保留");
    await view.send();
    expect(agent.messages.filter(message => message.text === "维护后继续这个问题")).toHaveLength(1);
    expect(view.prompt).toBe("");
    wrapper.unmount();
  });

  it("keeps an unconfirmed original message and never automatically submits it again", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "核对这个原始研究问题";
    submitTurn.mockRejectedValueOnce(Object.assign(new Error("请先核对原会话，勿重复发送。"), {
      status: 502, code: "prompt_outcome_unknown",
    }));
    await view.send();
    await flushPromises();
    expect(view.prompt).toBe("核对这个原始研究问题");
    expect(useAgentStore().messages.filter(message => message.text === "核对这个原始研究问题")).toHaveLength(1);
    expect(submitTurn).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("勿重复发送");
    wrapper.unmount();
  });

  it("unlocks a failed run, explains the failure, and resumes before retry", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      prompt: string;
      send: () => Promise<void>;
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };

    view.prompt = "第一次请求";
    await view.send();
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 2,
      timestamp: "2026-08-28T00:00:02Z", kind: "session.failed", source: "runtime-adapter",
      payload: { code: "runtime-no-progress-timeout", retryable: true },
    }, 1);
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 3,
      timestamp: "2026-08-28T00:00:03Z", kind: "session.ready", source: "runtime-adapter",
      payload: { status: "ready" },
    }, 1);
    await flushPromises();

    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".run-failure").text()).toContain("没有形成可展示的结论");
    expect(wrapper.find(".run-failure").text()).toContain("避免持续占用");

    view.prompt = "重试请求";
    await view.send();
    expect(resumeSession).toHaveBeenCalledWith("session-1", "");
    expect(submitTurn).toHaveBeenLastCalledWith("session-1", "重试请求", "");
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 4,
      timestamp: "2026-08-28T00:00:04Z", kind: "session.started", source: "runtime-adapter", payload: {},
    }, 1);
    await flushPromises();
    expect(wrapper.find(".run-failure").text()).toContain("没有形成可展示的结论");
    expect(wrapper.find(".run-failure").text()).toContain("后续已发起新一轮");
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 5,
      timestamp: "2026-08-28T00:00:05Z", kind: "session.result", source: "runtime-adapter", payload: {},
    }, 1);
    await flushPromises();
    expect(wrapper.findAll(".run-failure")).toHaveLength(1);
    expect(useAgentStore().messages.every(message => !message.text.includes("没有形成可展示的结论"))).toBe(true);
    wrapper.unmount();
  });

  it("permits an explicit new instruction after a known budget exhaustion without a failed-run resume", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      prompt: string;
      send: () => Promise<void>;
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };

    view.prompt = "第一次请求";
    await view.send();
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 2,
      timestamp: "2026-08-28T00:00:02Z", kind: "session.failed", source: "runtime-adapter",
      payload: { code: "budget-exhausted", retryable: false },
    }, 1);
    await flushPromises();

    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(false);

    view.prompt = "第二次明确指令";
    await view.send();
    expect(resumeSession).not.toHaveBeenCalled();
    expect(submitTurn).toHaveBeenLastCalledWith("session-1", "第二次明确指令", "");
    expect(wrapper.text()).not.toContain("请新建会话继续");
    wrapper.unmount();
  });

  it("does not duplicate output when replay overlaps the live stream", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };
    const event = {
      trace_id: "trace-1", session_id: "session-1", sequence: 2,
      timestamp: "2026-08-28T00:00:02Z", kind: "agent.output.delta", source: "runtime-adapter",
      payload: { delta: "唯一输出" },
    };

    view.handleEvent(event, 1);
    view.handleEvent(event, 1);
    await flushPromises();

    const agentMessages = useAgentStore().messages.filter((message) => message.role === "agent");
    expect(agentMessages).toHaveLength(1);
    expect(agentMessages[0].text).toBe("唯一输出");
  });

  it("keeps live output from a new root separate from the prior assistant message", async () => {
    const marker = "BYQ-NEXT-TURN-20261014-READONLY-7F3A";
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "自动接续" },
      messages: [
        { message_id: "m1", sequence: 1, role: "user", content: "已有请求", created_at: "2026-08-28T00:00:00Z" },
        { message_id: "m2", sequence: 2, role: "assistant", content: marker,
          workflow_sequence: 18, created_at: "2026-08-28T00:00:02Z" },
      ],
      events: [
        { trace_id: "trace-1", session_id: "session-1", sequence: 16, timestamp: "2026-08-28T00:00:01Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-prior" } },
        { trace_id: "trace-1", session_id: "session-1", sequence: 24, timestamp: "2026-08-28T00:00:03Z",
          kind: "session.result", source: "runtime-adapter", payload: { run_id: "run-prior" } },
      ],
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };

    view.handleEvent({ trace_id: "trace-1", session_id: "session-1", sequence: 25,
      timestamp: "2026-08-28T00:00:04Z", kind: "session.started", source: "runtime-adapter",
      payload: { run_id: "run-background" } }, 1);
    view.handleEvent({ trace_id: "trace-1", session_id: "session-1", sequence: 27,
      timestamp: "2026-08-28T00:00:05Z", kind: "agent.output.delta", source: "runtime-adapter",
      payload: { delta: "后台" } }, 1);
    view.handleEvent({ trace_id: "trace-1", session_id: "session-1", sequence: 29,
      timestamp: "2026-08-28T00:00:06Z", kind: "agent.output.delta", source: "runtime-adapter",
      payload: { delta: "接续回答" } }, 1);
    await flushPromises();

    expect(useAgentStore().messages.filter(message => message.role === "agent").map(message => message.text))
      .toEqual([marker, "后台接续回答"]);
    expect(wrapper.findAll(".conversation-message.agent:not(.assistant-processing)")).toHaveLength(2);
    wrapper.unmount();
  });

  it("removes the standalone processing bubble as soon as the final answer starts", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      prompt: string;
      send: () => Promise<void>;
      handleEvent: (event: Record<string, unknown>, generation: number) => void;
    };

    view.prompt = "检查回答收口";
    await view.send();
    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 2,
      timestamp: "2026-08-28T00:00:01Z", kind: "session.started", source: "runtime-adapter", payload: {},
    }, 1);
    expect(wrapper.find(".assistant-processing").exists()).toBe(true);

    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 3,
      timestamp: "2026-08-28T00:00:02Z", kind: "agent.output.delta", source: "runtime-adapter",
      payload: { delta: "这是最终回答" },
    }, 1);
    await flushPromises();

    expect(useAgentStore().messages.at(-1)?.text).toBe("这是最终回答");
    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(true);

    view.handleEvent({
      trace_id: "trace-1", session_id: "session-1", sequence: 4,
      timestamp: "2026-08-28T00:00:03Z", kind: "session.result", source: "runtime-adapter",
      payload: { finish_reason: "completed" },
    }, 1);
    await flushPromises();

    expect(wrapper.find(".assistant-processing").exists()).toBe(false);
    expect(wrapper.find(".composer-stop").exists()).toBe(false);
  });

  it("replays persisted assistant output without duplicating its workflow event", async () => {
    getAgentSession.mockResolvedValue({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "可靠回答" },
      messages: [
        { message_id: "m1", sequence: 1, role: "user", content: "问题", created_at: "2026-08-28T00:00:00Z" },
        { message_id: "m2", sequence: 2, role: "assistant", content: "数据库回答", workflow_sequence: 7, created_at: "2026-08-28T00:00:02Z" },
      ],
      events: [{
        trace_id: "trace-1", session_id: "session-1", sequence: 7,
        timestamp: "2026-08-28T00:00:02Z", kind: "agent.output.delta", source: "runtime-adapter",
        payload: { delta: "数据库回答" },
      }],
    });

    shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    const messages = useAgentStore().messages;
    expect(messages.map((message) => [message.role, message.text])).toEqual([
      ["user", "问题"], ["agent", "数据库回答"],
    ]);
  });

  it("replays assistant rows grouped by their started run without merging roots", async () => {
    const marker = "BYQ-NEXT-TURN-20261014-READONLY-7F3A";
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "自动接续历史" },
      messages: [
        { message_id: "m1", sequence: 1, role: "user", content: "已有请求", created_at: "2026-08-28T00:00:00Z" },
        { message_id: "m2", sequence: 2, role: "assistant", content: marker,
          workflow_sequence: 18, created_at: "2026-08-28T00:00:02Z" },
        { message_id: "m3", sequence: 3, role: "assistant", content: "后台",
          workflow_sequence: 27, created_at: "2026-08-28T00:00:04Z" },
        { message_id: "m4", sequence: 4, role: "assistant", content: "接续",
          workflow_sequence: 29, created_at: "2026-08-28T00:00:05Z" },
        { message_id: "m5", sequence: 5, role: "assistant", content: "回答",
          workflow_sequence: 30, created_at: "2026-08-28T00:00:06Z" },
        { message_id: "m6", sequence: 6, role: "assistant", content: "已经",
          workflow_sequence: 35, created_at: "2026-08-28T00:00:07Z" },
        { message_id: "m7", sequence: 7, role: "assistant", content: "完成",
          workflow_sequence: 36, created_at: "2026-08-28T00:00:08Z" },
      ],
      events: [
        { trace_id: "trace-1", session_id: "session-1", sequence: 16, timestamp: "2026-08-28T00:00:01Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-prior" } },
        { trace_id: "trace-1", session_id: "session-1", sequence: 24, timestamp: "2026-08-28T00:00:03Z",
          kind: "session.result", source: "runtime-adapter", payload: { run_id: "run-prior" } },
        { trace_id: "trace-1", session_id: "session-1", sequence: 25, timestamp: "2026-08-28T00:00:03Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-background" } },
        { trace_id: "trace-1", session_id: "session-1", sequence: 39, timestamp: "2026-08-28T00:00:07Z",
          kind: "session.result", source: "runtime-adapter", payload: { run_id: "run-background" } },
      ],
    });

    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(useAgentStore().messages.map((message) => [message.role, message.text])).toEqual([
      ["user", "已有请求"], ["agent", marker], ["agent", "后台接续回答已经完成"],
    ]);
    expect(wrapper.findAll(".conversation-message.agent:not(.assistant-processing)")).toHaveLength(2);
    wrapper.unmount();
  });

  it("does not merge replayed assistant output when its run boundary is unknown", async () => {
    getAgentSession.mockResolvedValueOnce({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "未知运行边界" },
      messages: [
        { message_id: "m1", sequence: 1, role: "assistant", content: "片段一",
          workflow_sequence: 7, created_at: "2026-08-28T00:00:01Z" },
        { message_id: "m2", sequence: 2, role: "assistant", content: "片段二",
          workflow_sequence: 8, created_at: "2026-08-28T00:00:02Z" },
      ],
      events: [
        { trace_id: "trace-1", session_id: "session-1", sequence: 2, timestamp: "2026-08-28T00:00:00Z",
          kind: "session.started", source: "runtime-adapter", payload: { run_id: "run-prior" } },
        { trace_id: "trace-1", session_id: "session-1", sequence: 4, timestamp: "2026-08-28T00:00:00Z",
          kind: "session.result", source: "runtime-adapter", payload: { run_id: "run-prior" } },
      ],
    });

    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(useAgentStore().messages.filter(message => message.role === "agent").map(message => message.text))
      .toEqual(["片段一", "片段二"]);
    expect(wrapper.findAll(".conversation-message.agent:not(.assistant-processing)")).toHaveLength(2);
    wrapper.unmount();
  });

  it("keeps a new empty conversation local until the first message is sent", async () => {
    listAgentSessions.mockResolvedValueOnce({ sessions: [], total: 0 });
    routerHarness.route.query = { new: "true" };
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(useAgentStore().activeSessionId).toBe("");
    expect(createAgentSession).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("发送第一条消息后保存");

    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "第一次提问";
    await view.send();
    await flushPromises();

    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(submitTurn).toHaveBeenCalledWith("session-1", "第一次提问", "");
    expect(getAgentSession).toHaveBeenCalledTimes(1);
    expect(routerHarness.replace).toHaveBeenCalledWith({ path: "/agent", query: { session: "session-1" } });
    expect(routerHarness.route.query).toEqual({ session: "session-1" });
    expect(submitTurn).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("reloads an existing conversation from its exact CID without creating or sending", async () => {
    routerHarness.route.query = { session: "session-1" };
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(useAgentStore().activeSessionId).toBe("session-1");
    expect(getAgentSession).toHaveBeenCalledTimes(1);
    expect(createAgentSession).not.toHaveBeenCalled();
    expect(submitTurn).not.toHaveBeenCalled();
    expect(routerHarness.replace).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("shows first-session maintenance rejection and preserves the draft without retry", async () => {
    listAgentSessions.mockResolvedValueOnce({ sessions: [], total: 0 });
    createAgentSession.mockRejectedValueOnce(new AgentRequestError("小巴正在维护，请稍后重试。", 503, "chat_maintenance"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "保留这条首次提问";
    await view.send();
    await flushPromises();
    expect(view.prompt).toBe("保留这条首次提问");
    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(submitTurn).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("小巴正在维护，请稍后重试。");
    wrapper.unmount();
  });

  it("shows an unknown first-session creation outcome without automatically creating again", async () => {
    listAgentSessions.mockResolvedValueOnce({ sessions: [], total: 0 });
    createAgentSession.mockRejectedValueOnce(new Error("创建会话结果未知，请核对后再操作。"));
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "不要丢失这条问题";
    await view.send();
    await flushPromises();
    expect(view.prompt).toBe("不要丢失这条问题");
    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(submitTurn).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("创建会话结果未知，请核对后再操作。");
    wrapper.unmount();
  });

  it("permanently deletes a selected history conversation and opens a blank draft", async () => {
    vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as never);
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const session = useAgentStore().sessions[0];
    listAgentSessions.mockResolvedValue({ sessions: [], total: 0 });

    await (wrapper.vm as unknown as {
      deleteHistorySession: (item: typeof session) => Promise<void>;
    }).deleteHistorySession(session);

    expect(deleteAgentSession).toHaveBeenCalledWith("session-1", "");
    expect(useAgentStore().activeSessionId).toBe("");
    expect(useAgentStore().sessions).toEqual([]);
  });

  it("batch archives selected history conversations", async () => {
    vi.spyOn(ElMessageBox, "confirm").mockResolvedValue("confirm" as never);
    listAgentSessions.mockResolvedValue({
      sessions: [
        { session_id: "session-1", trace_id: "trace-1", title: "会话一" },
        { session_id: "session-2", trace_id: "trace-2", title: "会话二" },
      ],
      total: 2,
    });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    const view = wrapper.vm as unknown as {
      showHistory: () => Promise<void>;
      toggleAllHistory: (selected: boolean) => void;
      batchArchiveHistory: () => Promise<void>;
    };
    await view.showHistory();
    view.toggleAllHistory(true);
    await view.batchArchiveHistory();

    expect(updateAgentSession).toHaveBeenCalledTimes(2);
    expect(updateAgentSession).toHaveBeenCalledWith("session-1", { status: "archived" }, "");
    expect(updateAgentSession).toHaveBeenCalledWith("session-2", { status: "archived" }, "");
  });
});
