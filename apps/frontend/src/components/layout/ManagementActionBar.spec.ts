import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ManagementActionBar from "./ManagementActionBar.vue";

describe("ManagementActionBar", () => {
  it("keeps lifecycle context and actions in one labelled region", () => {
    const wrapper = mount(ManagementActionBar, {
      props: { description: "历史证据会保留" },
      slots: {
        status: "<span>已完成</span>",
        default: "<button>归档</button><button>删除</button>",
      },
    });

    const region = wrapper.get('[aria-label="管理操作"]');
    expect(region.text()).toContain("管理操作");
    expect(region.text()).toContain("历史证据会保留");
    expect(region.findAll("button").map((button) => button.text())).toEqual(["归档", "删除"]);
  });
});
