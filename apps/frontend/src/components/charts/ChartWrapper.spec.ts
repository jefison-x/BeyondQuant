import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ setOption: vi.fn(), dispose: vi.fn() }));
vi.mock("echarts/core", () => ({
  use: vi.fn(),
  init: vi.fn(() => ({ setOption: mocks.setOption, clear: vi.fn(), resize: vi.fn(), dispose: mocks.dispose })),
}));
vi.mock("echarts/charts", () => ({ LineChart: {} }));
vi.mock("echarts/components", () => ({
  AriaComponent: {}, GridComponent: {}, LegendComponent: {}, TitleComponent: {}, TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

import ChartWrapper from "./ChartWrapper.vue";

describe("ChartWrapper", () => {
  beforeEach(() => {
    mocks.setOption.mockReset();
    mocks.dispose.mockReset();
    vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  });

  it("exposes an accessible chart name and disables animation for reduced motion", async () => {
    const wrapper = mount(ChartWrapper, { props: { option: { series: [{ type: "line", data: [1, 2] }] }, ariaLabel: "策略权益曲线", summary: "两期权益数据" } });
    await vi.waitFor(() => expect(mocks.setOption).toHaveBeenCalled());
    expect(wrapper.get('[role="img"]').attributes("aria-label")).toBe("策略权益曲线");
    expect(wrapper.get("figcaption").text()).toBe("两期权益数据");
    expect(mocks.setOption.mock.calls.at(-1)?.[0]).toMatchObject({ animation: false, aria: { enabled: true } });
  });

  it("renders named loading and empty states instead of a blank canvas", async () => {
    const wrapper = mount(ChartWrapper, { props: { option: {}, loading: true } });
    expect(wrapper.get('[role="status"]').text()).toContain("正在加载图表");
    await wrapper.setProps({ loading: false, empty: true, emptyMessage: "暂无权益数据" });
    expect(wrapper.text()).toContain("暂无权益数据");
  });
});
