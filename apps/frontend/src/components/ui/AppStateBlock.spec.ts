import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AppStateBlock from "./AppStateBlock.vue";

describe("AppStateBlock", () => {
  it("prioritizes loading, error, empty, then content", async () => {
    const wrapper = mount(AppStateBlock, {
      props: { loading: true, error: "boom", empty: true },
      slots: { default: "content" },
    });
    expect(wrapper.text()).toContain("加载中");
    await wrapper.setProps({ loading: false });
    expect(wrapper.get('[role="alert"]').text()).toBe("boom");
    await wrapper.setProps({ error: "" });
    expect(wrapper.text()).toContain("暂无数据");
    await wrapper.setProps({ empty: false });
    expect(wrapper.text()).toContain("content");
  });
});
