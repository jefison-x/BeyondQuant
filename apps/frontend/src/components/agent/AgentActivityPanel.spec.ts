import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import AgentActivityPanel from "./AgentActivityPanel.vue";

describe("AgentActivityPanel", () => {
  it("renders public Chinese phase and state labels without internal terminology", () => {
    const wrapper = shallowMount(AgentActivityPanel, {
      global: {
        stubs: {
          ElTag: { template: "<span><slot /></span>" },
          ElEmpty: true,
        },
      },
      props: {
        activities: [
          {
            sequence: 2,
            timestamp: "2026-08-26T00:00:00Z",
            payload: {
              schema_version: "workflow-activity.v1",
              activity_id: `activity_${"a".repeat(64)}`,
              phase: "select",
              state: "completed",
              label: "读取估值数据",
            },
          },
        ],
      },
    });

    expect(wrapper.text()).toContain("读取估值数据");
    expect(wrapper.text()).toContain("研究数据");
    expect(wrapper.text()).toContain("已完成");
    expect(wrapper.text()).not.toContain("select");
    expect(wrapper.text()).not.toContain("completed");
    expect(wrapper.text()).not.toContain("工具参数");
  });
});
