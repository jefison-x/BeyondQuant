import { createPinia, setActivePinia } from "pinia";
import { shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppSidebar from "./AppSidebar.vue";
import { useAgentStore } from "@/stores/agent";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/agent" }),
  useRouter: () => ({ push }),
}));

describe("AppSidebar", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    push.mockReset();
  });

  it("places the history entry beside the conversation heading", async () => {
    const wrapper = shallowMount(AppSidebar, { props: { isCollapsed: false } });

    expect(wrapper.text()).toContain("投研对话");
    expect(wrapper.text()).not.toContain("最近会话");
    expect(wrapper.findAll("button").filter((button) => button.text() === "历史会话")).toHaveLength(0);

    expect(wrapper.text()).not.toContain("查看全部");
    const history = wrapper.findAll("button").find((button) => button.text() === "历史");
    expect(history).toBeDefined();
    await history?.trigger("click");
    expect(push).toHaveBeenCalledWith({ path: "/agent", query: { history: "recent" } });
  });

  it("shows no more than the latest 20 conversations and lets the route load a selected session", async () => {
    const agent = useAgentStore();
    agent.replaceSessions(Array.from({ length: 25 }, (_, index) => ({
      session_id: `session-${index + 1}`,
      trace_id: `trace-${index + 1}`,
      status: "active",
      title: `会话 ${index + 1}`,
    })));
    agent.hydrateSession("session-2", [{ role: "user", text: "旧内容" }], []);

    const wrapper = shallowMount(AppSidebar, { props: { isCollapsed: false } });
    expect(wrapper.findAll(".history-row")).toHaveLength(20);

    await wrapper.findAll(".history-row")[4].trigger("click");
    expect(push).toHaveBeenCalledWith({ path: "/agent", query: { session: "session-5" } });
    expect(agent.activeSessionId).toBe("session-2");
    expect(agent.messages[0]?.text).toBe("旧内容");
  });
});
