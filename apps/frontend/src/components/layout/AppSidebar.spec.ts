import { createPinia, setActivePinia } from "pinia";
import { shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppSidebar from "./AppSidebar.vue";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ path: "/agent" }),
  useRouter: () => ({ push }),
}));

describe("AppSidebar", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    push.mockReset();
  });

  it("uses one conversation section and opens full history from view all", async () => {
    const wrapper = shallowMount(AppSidebar, { props: { isCollapsed: false } });

    expect(wrapper.text()).toContain("投研对话");
    expect(wrapper.text()).not.toContain("最近会话");
    expect(wrapper.findAll("button").filter((button) => button.text() === "历史会话")).toHaveLength(0);

    const viewAll = wrapper.findAll("button").find((button) => button.text() === "查看全部");
    expect(viewAll).toBeDefined();
    await viewAll?.trigger("click");
    expect(push).toHaveBeenCalledWith({ path: "/agent", query: { history: "recent" } });
  });
});
