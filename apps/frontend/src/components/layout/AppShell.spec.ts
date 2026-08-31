import { defineComponent, h, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AppHeader from "./AppHeader.vue";
import AppShell from "./AppShell.vue";
import { useAuthStore } from "@/stores/auth";

vi.mock("vue-router", () => ({ useRoute: () => ({ meta: {}, path: "/agent" }) }));
const listAgentSessions = vi.fn();
vi.mock("@/api/agent", () => ({ listAgentSessions: (...args: unknown[]) => listAgentSessions(...args) }));

const originalWidth = window.innerWidth;

beforeEach(() => {
  setActivePinia(createPinia());
  listAgentSessions.mockReset();
  listAgentSessions.mockResolvedValue({ sessions: [], total: 0 });
});

afterEach(() => {
  vi.useRealTimers();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
});

describe("AppShell", () => {
  it("uses a keyboard-reachable mobile drawer instead of a bottom navigation", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    const DrawerStub = defineComponent({
      name: "ElDrawer",
      props: { modelValue: Boolean },
      setup(_, { slots }) {
        return () => h("div", slots.default?.());
      },
    });
    const wrapper = shallowMount(AppShell, {
      global: { stubs: { RouterView: true, "el-drawer": DrawerStub } },
    });
    await nextTick();

    const header = wrapper.findComponent(AppHeader);
    expect(header.props("showMenu")).toBe(true);
    expect(wrapper.findComponent({ name: "AppBottomNav" }).exists()).toBe(false);
    expect(wrapper.findComponent({ name: "AppSidebar" }).props("mobile")).toBe(true);

    header.vm.$emit("toggle-menu");
    await nextTick();

    expect(wrapper.findComponent({ name: "ElDrawer" }).props("modelValue")).toBe(true);
  });

  it("renders the collapsible single desktop sidebar", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
    const wrapper = shallowMount(AppShell, { global: { stubs: { RouterView: true } } });
    await nextTick();

    expect(wrapper.findComponent({ name: "AppSidebar" }).props("isCollapsed")).toBe(false);
    expect(wrapper.findComponent(AppHeader).props("showMenu")).toBe(false);
  });

  it("restores recent conversations when a protected page is refreshed", async () => {
    vi.useFakeTimers();
    useAuthStore().setUser({
      subject: "admin",
      workspace: { contract: "personal-workspace.v1", workspace_id: "workspace-admin", kind: "personal", display_name: "Admin", role: "owner" },
    });
    listAgentSessions.mockResolvedValue({
      sessions: [{ session_id: "session-1", trace_id: "trace-1", title: "刷新后恢复" }], total: 1,
    });
    shallowMount(AppShell, { global: { stubs: { RouterView: true } } });
    await vi.runAllTimersAsync();
    await flushPromises();

    expect(listAgentSessions).toHaveBeenCalledWith("", { limit: 20 });
  });

  it("gives the conversation route one internal scroll container", async () => {
    const wrapper = shallowMount(AppShell, { global: { stubs: { RouterView: true } } });
    await nextTick();

    expect(wrapper.get("main").classes()).toContain("content-area--conversation");
  });
});
