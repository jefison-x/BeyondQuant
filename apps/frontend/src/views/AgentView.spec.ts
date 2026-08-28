import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus from "element-plus";
import AgentView from "./AgentView.vue";
import { useAuthStore } from "@/stores/auth";

const submitTurn = vi.fn();
const cancelSession = vi.fn();
const resumeSession = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/agent", query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/api/agent", () => ({
  cancelSession: (...args: unknown[]) => cancelSession(...args),
  createAgentSession: vi.fn().mockResolvedValue({ session_id: "session-1", trace_id: "trace-1", title: "测试会话" }),
  getAgentSession: vi.fn().mockResolvedValue({
    conversation: { session_id: "session-1", trace_id: "trace-1", title: "测试会话" },
    messages: [{ message_id: "message-1", sequence: 1, role: "user", content: "已有问题", created_at: "2026-08-28T00:00:00Z" }],
    events: [],
  }),
  listAgentSessions: vi.fn().mockResolvedValue({
    sessions: [{ session_id: "session-1", trace_id: "trace-1", title: "测试会话" }],
    total: 1,
  }),
  resumeSession: (...args: unknown[]) => resumeSession(...args),
  streamWorkflowEvents: vi.fn(() => new Promise<void>(() => undefined)),
  submitTurn: (...args: unknown[]) => submitTurn(...args),
  updateAgentSession: vi.fn(),
}));

describe("AgentView", () => {
  beforeEach(() => {
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
  });

  it("shows the personalized nickname and sends with Ctrl+Enter", async () => {
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(wrapper.find(".conversation-message.user .message-author").text()).toBe("量化小周");

    (wrapper.vm as unknown as { prompt: string }).prompt = "快捷发送";
    const event = new KeyboardEvent("keydown", { key: "Enter", ctrlKey: true, cancelable: true });
    (wrapper.vm as unknown as { handleComposerKeydown: (event: KeyboardEvent) => void }).handleComposerKeydown(event);
    await flushPromises();

    expect(event.defaultPrevented).toBe(true);
    expect(submitTurn).toHaveBeenCalledWith("session-1", "快捷发送", "");
    expect(wrapper.find(".assistant-processing").exists()).toBe(true);
    expect(wrapper.find(".composer-stop").attributes("aria-label")).toBe("停止本轮");
  });

  it("falls back to 我 when no nickname is available", async () => {
    const auth = useAuthStore();
    auth.setUser({ ...auth.user!, display_name: "" });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();
    expect(wrapper.find(".conversation-message.user .message-author").text()).toBe("我");
  });
});
