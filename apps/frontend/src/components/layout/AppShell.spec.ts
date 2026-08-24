import { defineComponent, h, nextTick } from "vue";
import { shallowMount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import AppHeader from "./AppHeader.vue";
import AppShell from "./AppShell.vue";

vi.mock("vue-router", () => ({ useRoute: () => ({ meta: {}, path: "/agent" }) }));

const originalWidth = window.innerWidth;

afterEach(() => {
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
});
