import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth";
import UserSettingsMenu from "./UserSettingsMenu.vue";

const push = vi.fn();

vi.mock("vue-router", () => ({
  useRoute: () => ({ fullPath: "/agent" }),
  useRouter: () => ({ push }),
}));

describe("UserSettingsMenu", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    push.mockReset();
  });

  it("orients the user in one personal workspace without team affordances", () => {
    const auth = useAuthStore();
    auth.setUser({
      subject: "alice",
      role: "user",
      workspace: {
        contract: "personal-workspace.v1",
        workspace_id: "workspace_alice",
        kind: "personal",
        display_name: "Alice 的个人工作区",
        role: "owner",
      },
    });
    const wrapper = mount(UserSettingsMenu, {
      global: {
        stubs: {
          "el-dropdown": { template: "<div><slot /><slot name='dropdown' /></div>" },
          "el-dropdown-menu": { template: "<ul><slot /></ul>" },
          "el-dropdown-item": { template: "<li><slot /></li>" },
          "el-icon": { template: "<i><slot /></i>" },
        },
      },
    });

    expect(wrapper.text()).toContain("Alice 的个人工作区");
    expect(wrapper.text()).toContain("仅你本人可访问 · 无需切换");
    expect(wrapper.text()).not.toMatch(/邀请|成员管理|切换工作区|创建工作区/);
    expect(wrapper.html()).not.toContain("workspace_alice");
  });
});
