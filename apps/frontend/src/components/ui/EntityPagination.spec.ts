import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import EntityPagination from "./EntityPagination.vue";

describe("EntityPagination", () => {
  it("hides for one page and exposes an accessible total for multiple pages", () => {
    const onePage = mount(EntityPagination, { props: { total: 20, page: 1, pageSize: 50 } });
    expect(onePage.find("nav").exists()).toBe(false);

    const multiple = mount(EntityPagination, {
      props: { total: 120, page: 1, pageSize: 50, label: "策略分页" },
      global: { stubs: { ElPagination: { template: "<button>next</button>" } } },
    });
    expect(multiple.get("nav").attributes("aria-label")).toBe("策略分页");
    expect(multiple.text()).toContain("共 120 项，第 1 页");
  });
});
