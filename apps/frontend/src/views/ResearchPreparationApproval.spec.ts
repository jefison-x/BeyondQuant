import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Approval from "./ResearchPreparationApproval.vue";
import { createResearchPreparation } from "@/api/dataCenter";
import { useAuthStore } from "@/stores/auth";

vi.mock("vue-router", () => ({ useRoute: () => ({ query: { researchPreparation: JSON.stringify({
  symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research",
  data_requirements: { daily_basic: ["pe_ttm"] },
}) } }) }));
vi.mock("@/api/dataCenter", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/dataCenter")>(),
  createResearchPreparation: vi.fn(),
}));

function setUserRole(role: "admin" | "user") {
  const auth = useAuthStore();
  auth.setUser({ subject: "admin-viewer", role, display_name: "viewer", workspace: {
    contract: "personal-workspace.v1", workspace_id: "workspace-viewer", kind: "personal", display_name: "viewer", role: "owner",
  } });
}

describe("research preparation approval handoff", () => {
  afterEach(() => { vi.clearAllMocks(); });

  it("requires explicit administrator confirmation and treats task completion separately from readiness", async () => {
    setActivePinia(createPinia());
    setUserRole("admin");
    vi.mocked(createResearchPreparation).mockResolvedValue({ request_id: "repair-123", status: "completed" });
    const wrapper = mount(Approval);
    expect(wrapper.text()).toContain("不包含会话内容或用户标识");
    expect(wrapper.text()).toContain("后台市场数据按交易日获取");
    expect(createResearchPreparation).not.toHaveBeenCalled();
    const confirm = wrapper.get('input[type="checkbox"]');
    await confirm.setValue(true);
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(createResearchPreparation).toHaveBeenCalledWith({
      symbols: ["600036.SH"], start_date: "20260101", end_date: "20260331", use_case: "research",
      data_requirements: { daily_basic: ["pe_ttm"] },
    });
    expect(wrapper.text()).toContain("准备任务已完成，需复查数据覆盖");
    expect(wrapper.text()).toContain("不证明具体指标都有值");
    wrapper.unmount();
  });

  it("does not submit when the current account is not an administrator", async () => {
    setActivePinia(createPinia());
    setUserRole("user");
    const wrapper = mount(Approval);
    await wrapper.get('input[type="checkbox"]').setValue(true);
    expect((wrapper.get("button").element as HTMLButtonElement).disabled).toBe(true);
    expect(wrapper.text()).toContain("当前账号没有管理员权限");
    expect(createResearchPreparation).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
