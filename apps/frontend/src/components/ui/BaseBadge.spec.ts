import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BaseBadge from "./BaseBadge.vue";

describe("BaseBadge", () => {
  it("renders the label and tone class", () => {
    const wrapper = mount(BaseBadge, { props: { label: "ok", tone: "success" } });
    expect(wrapper.text()).toBe("ok");
    expect(wrapper.classes()).toContain("base-badge");
    expect(wrapper.classes()).toContain("success");
  });
});
