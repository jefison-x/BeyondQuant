import { defineComponent, h, nextTick } from "vue";
import { shallowMount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import AppHeader from "./AppHeader.vue";
import OpsLayout from "./OpsLayout.vue";

const originalWidth = window.innerWidth;

afterEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: originalWidth });
});

describe("OpsLayout", () => {
  it("provides an accessible mobile operations drawer", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 390 });
    const DrawerStub = defineComponent({
      name: "ElDrawer",
      props: { modelValue: Boolean },
      setup(_, { slots }) {
        return () => h("div", slots.default?.());
      },
    });
    const wrapper = shallowMount(OpsLayout, {
      global: { stubs: { RouterView: true, "el-drawer": DrawerStub } },
    });
    await nextTick();

    const header = wrapper.findComponent(AppHeader);
    expect(header.props("showMenu")).toBe(true);
    expect(wrapper.findComponent({ name: "OpsSidebar" }).exists()).toBe(true);

    header.vm.$emit("toggle-menu");
    await nextTick();

    expect(wrapper.findComponent({ name: "ElDrawer" }).props("modelValue")).toBe(true);
  });
});
