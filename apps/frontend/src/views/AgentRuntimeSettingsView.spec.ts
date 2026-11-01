import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";
import type { AgentExecutionOptions } from "@/api/agent";
import { useAuthStore } from "@/stores/auth";
import AgentRuntimeSettingsView from "./AgentRuntimeSettingsView.vue";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), sessions: vi.fn() }));
vi.mock("@/api/agent", async (original) => ({
  ...await original<typeof import("@/api/agent")>(),
  getAgentExecutionOptions: api.get,
  updateAgentExecutionOptions: api.put,
  listAgentSessions: api.sessions,
}));

function defaults(): AgentExecutionOptions {
  return {
    auto_continue: true, max_provider_calls: null, max_provider_attempts: null,
    max_tool_calls: null, max_concurrent_provider_calls: null,
    max_input_bytes_per_call: null, max_input_bytes_total: null,
    max_output_tokens_per_call: null, max_output_tokens_total: null,
    max_tool_payload_bytes_per_call: null, max_tool_payload_bytes_total: null,
    max_continuations: null, max_runtime_seconds: null, max_no_progress_seconds: null,
    max_child_runtime_seconds: null, max_child_no_progress_seconds: null,
  };
}
function record(owner = "alice", revision = 4, options = defaults()) {
  return { schema_version: "agent-execution-options.v1", scope: "user",
    owner_principal: owner, revision, options, updated_at: null };
}
function login(subject = "alice", workspaceId = "workspace-alice") {
  useAuthStore().setUser({ subject, display_name: subject, workspace: {
    contract: "personal-workspace.v1", workspace_id: workspaceId,
    kind: "personal", display_name: "个人工作区", role: "owner",
  } });
}
function mountSettings() {
  return shallowMount(AgentRuntimeSettingsView, { global: { plugins: [ElementPlus] } });
}

describe("user Agent runtime settings", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    login();
    api.get.mockReset().mockResolvedValue(record());
    api.put.mockReset().mockImplementation((payload) => Promise.resolve(
      record("alice", payload.expected_revision + 1, payload.options),
    ));
    api.sessions.mockReset();
  });

  it("is available without any conversation and shares the current user's scope", async () => {
    const wrapper = mountSettings();
    await flushPromises();
    expect(api.get).toHaveBeenCalledWith("");
    expect(api.sessions).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: "ElSelect" }).exists()).toBe(false);
    expect(wrapper.text()).toContain("本账号所有会话");
    login("alice", "another-workspace");
    await flushPromises();
    expect(api.get).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("keeps parameters unknown after a failed read instead of offering defaults to save", async () => {
    api.get.mockRejectedValue(new Error("network unavailable"));
    const wrapper = mountSettings();
    await flushPromises();
    expect(wrapper.text()).toContain("状态未知");
    expect(wrapper.findComponent({ name: "ElSwitch" }).exists()).toBe(false);
    await (wrapper.vm as any).saveOptions();
    expect(api.put).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("saves one user revision while preserving the other configured limits", async () => {
    const original = { ...defaults(), max_provider_calls: 7, max_output_tokens_per_call: 1200 };
    api.get.mockResolvedValue(record("alice", 9, original));
    const wrapper = mountSettings();
    await flushPromises();
    wrapper.findComponent({ name: "ElSwitch" }).vm.$emit("change", false);
    await (wrapper.vm as any).saveOptions();
    expect(api.put).toHaveBeenCalledExactlyOnceWith({
      schema_version: "agent-execution-options.v1", expected_revision: 9,
      options: { ...original, auto_continue: false },
    }, "");
    expect(wrapper.text()).toContain("适用于所有会话的后续执行");
    wrapper.unmount();
  });

  it("rejects foreign-owner and former conversation-scoped projections", async () => {
    api.get.mockResolvedValue({ ...record("bob"), conversation_id: "old-conversation", scope: undefined });
    const wrapper = mountSettings();
    await flushPromises();
    expect(wrapper.text()).toContain("与当前账户不匹配");
    expect(wrapper.findComponent({ name: "ElSwitch" }).exists()).toBe(false);
    wrapper.unmount();
  });

  it("reconciles a stale or unknown PUT with one GET without replaying the write", async () => {
    api.get.mockResolvedValueOnce(record()).mockResolvedValueOnce(record("alice", 6, { ...defaults(), max_tool_calls: 5 }));
    api.put.mockRejectedValue(new Error("revision conflict"));
    const wrapper = mountSettings();
    await flushPromises();
    wrapper.findComponent({ name: "ElSwitch" }).vm.$emit("change", false);
    await (wrapper.vm as any).saveOptions();
    expect(api.put).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledTimes(2);
    expect((wrapper.vm as any).options.revision).toBe(6);
    expect(wrapper.text()).toContain("已读取最新用户参数");
    wrapper.unmount();
  });

  it("does not let a late read from the previous user populate the new user's form", async () => {
    let oldRead!: (value: ReturnType<typeof record>) => void;
    api.get.mockReturnValueOnce(new Promise(resolve => { oldRead = resolve; }))
      .mockResolvedValueOnce(record("bob", 2, { ...defaults(), auto_continue: false }));
    const wrapper = mountSettings();
    login("bob", "workspace-bob");
    await flushPromises();
    oldRead(record("alice", 10));
    await flushPromises();
    expect((wrapper.vm as any).options.owner_principal).toBe("bob");
    expect((wrapper.vm as any).draftAutoContinue).toBe(false);
    wrapper.unmount();
  });

  it("does not submit an invalid numeric limit", async () => {
    const wrapper = mountSettings();
    await flushPromises();
    (wrapper.vm as any).updateNumericDraft("max_provider_calls", "0");
    await (wrapper.vm as any).saveOptions();
    expect(api.put).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps a late save for the previous user out of the current user's form", async () => {
    let finishSave!: (value: ReturnType<typeof record>) => void;
    api.put.mockReturnValueOnce(new Promise(resolve => { finishSave = resolve; }));
    const wrapper = mountSettings();
    await flushPromises();
    wrapper.findComponent({ name: "ElSwitch" }).vm.$emit("change", false);
    const saving = (wrapper.vm as any).saveOptions();
    api.get.mockResolvedValueOnce(record("bob", 2));
    login("bob", "workspace-bob");
    await flushPromises();
    finishSave(record("alice", 5, { ...defaults(), auto_continue: false }));
    await saving;
    await flushPromises();
    expect((wrapper.vm as any).options.owner_principal).toBe("bob");
    expect((wrapper.vm as any).draftAutoContinue).toBe(true);
    expect(wrapper.text()).not.toContain("用户运行参数已保存");
    wrapper.unmount();
  });
});
