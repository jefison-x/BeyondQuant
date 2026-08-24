import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ManagementWorkspace from "./ManagementWorkspace.vue";

describe("ManagementWorkspace", () => {
  it("renders the shared catalog/detail contract and return action", async () => {
    const wrapper = mount(ManagementWorkspace, {
      props: { eyebrow: "核心资产", title: "策略工作区", description: "不可变谱系", catalogLabel: "策略资产", count: 3 },
      slots: { return: "返回投研对话", catalog: "目录内容", detail: "详情内容" },
      global: { stubs: { ElButton: { template: "<button @click=\"$emit('click')\"><slot /></button>" } } },
    });
    expect(wrapper.text()).toContain("策略工作区");
    expect(wrapper.text()).toContain("目录内容");
    expect(wrapper.text()).toContain("详情内容");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("return")?.length).toBeGreaterThan(0);
  });
});
