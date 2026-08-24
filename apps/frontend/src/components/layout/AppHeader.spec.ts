import { shallowMount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import GlobalApprovalCenter from "@/components/agent/GlobalApprovalCenter.vue";
import AppHeader from "./AppHeader.vue";

vi.mock("vue-router", () => ({ useRoute: () => ({ meta: { title: "策略管理" } }) }));

describe("AppHeader", () => {
  it("hosts the single global approval entry in the top-right toolbar", () => {
    const wrapper = shallowMount(AppHeader);

    expect(wrapper.get("h1").text()).toBe("策略管理");
    expect(wrapper.findComponent(GlobalApprovalCenter).exists()).toBe(true);
    expect(wrapper.find(".header-right").findComponent(GlobalApprovalCenter).exists()).toBe(true);
  });
});
