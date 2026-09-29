import { defineComponent, h } from "vue";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import UserCenterLayout from "./UserCenterLayout.vue";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/user/reset" }),
  useRouter: () => ({ push }),
}));

describe("UserCenterLayout reset navigation", () => {
  it("offers the reset page in desktop links and the mobile section selector", () => {
    const wrapper = mount(UserCenterLayout, {
      global: {
        stubs: {
          RouterView: true,
          RouterLink: defineComponent({
            props: { to: { type: String, required: true } },
            setup(props, { slots }) {
              return () => h("a", { href: props.to }, slots.default?.());
            },
          }),
          "el-select": { props: ["modelValue"], template: "<select :value='modelValue'><slot /></select>" },
          "el-option": { props: ["label", "value"], template: "<option :value='value'>{{ label }}</option>" },
        },
      },
    });

    expect(wrapper.find('a[href="/user/reset"]').text()).toContain("重置工作区");
    expect(wrapper.find('select option[value="/user/reset"]').text()).toBe("重置工作区");
  });
});
