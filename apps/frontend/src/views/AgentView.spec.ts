import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ElementPlus, { ElMessageBox } from "element-plus";
import AgentView from "./AgentView.vue";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const submitTurn = vi.fn();
const cancelSession = vi.fn();
const resumeSession = vi.fn();
const getAgentSession = vi.fn();
const createAgentSession = vi.fn();
const deleteAgentSession = vi.fn();
const listAgentSessions = vi.fn();
const updateAgentSession = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/agent", query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/api/agent", () => ({
  cancelSession: (...args: unknown[]) => cancelSession(...args),
  createAgentSession: (...args: unknown[]) => createAgentSession(...args),
  deleteAgentSession: (...args: unknown[]) => deleteAgentSession(...args),
  getAgentSession: (...args: unknown[]) => getAgentSession(...args),
  listAgentSessions: (...args: unknown[]) => listAgentSessions(...args),
  resumeSession: (...args: unknown[]) => resumeSession(...args),
  streamWorkflowEvents: vi.fn(() => new Promise<void>(() => undefined)),
  submitTurn: (...args: unknown[]) => submitTurn(...args),
  updateAgentSession: (...args: unknown[]) => updateAgentSession(...args),
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
    getAgentSession.mockReset();
    getAgentSession.mockResolvedValue({
      conversation: { session_id: "session-1", trace_id: "trace-1", title: "测试会话" },
      messages: [{ message_id: "message-1", sequence: 1, role: "user", content: "已有问题", created_at: "2026-08-28T00:00:00Z" }],
      events: [],
    });
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

  it("keeps a new empty conversation local until the first message is sent", async () => {
    listAgentSessions.mockResolvedValueOnce({ sessions: [], total: 0 });
    const wrapper = shallowMount(AgentView, { global: { plugins: [ElementPlus] } });
    await flushPromises();

    expect(useAgentStore().activeSessionId).toBe("");
    expect(createAgentSession).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("发送第一条消息后保存");

    const view = wrapper.vm as unknown as { prompt: string; send: () => Promise<void> };
    view.prompt = "第一次提问";
    await view.send();

    expect(createAgentSession).toHaveBeenCalledTimes(1);
    expect(submitTurn).toHaveBeenCalledWith("session-1", "第一次提问", "");
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
