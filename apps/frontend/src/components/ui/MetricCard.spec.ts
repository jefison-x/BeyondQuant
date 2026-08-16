import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import MetricCard from "./MetricCard.vue";

describe("MetricCard", () => {
  it("renders label and value", () => {
    const wrapper = mount(MetricCard, { props: { label: "Total Return", value: "12.3" } });
    expect(wrapper.text()).toContain("Total Return");
    expect(wrapper.text()).toContain("12.3");
  });
});
