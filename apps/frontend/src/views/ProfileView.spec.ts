import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProfileView from "./ProfileView.vue";
import { PasswordChangeError } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";

const changePassword = vi.fn();
const getProfile = vi.fn();
const push = vi.fn();

vi.mock("@/api/auth", () => ({
  changePassword: (...args: unknown[]) => changePassword(...args),
  PasswordChangeError: class PasswordChangeError extends Error {
    constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
  },
}));
vi.mock("@/api/settings", () => ({ getProfile: (...args: unknown[]) => getProfile(...args), updateProfile: vi.fn() }));
vi.mock("@/composables/useUnsavedChanges", () => ({ useUnsavedChanges: vi.fn() }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push }) }));

describe("ProfileView password change", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().setUser({ subject: "alice", role: "user", workspace: {
      contract: "personal-workspace.v1", workspace_id: "workspace_alice", kind: "personal",
      display_name: "Alice 的个人工作区", role: "owner",
    } });
    changePassword.mockReset();
    push.mockReset();
    getProfile.mockResolvedValue({ profile: { display_name: "Alice", preferences: "", default_prompt: "" } });
  });

  it("clears credentials and local identity after exact success, then routes to login", async () => {
    changePassword.mockResolvedValue(undefined);
    const wrapper = shallowMount(ProfileView);
    await flushPromises();
    const vm = wrapper.vm as unknown as { passwordForm: { current: string; next: string; confirm: string }; savePassword: () => Promise<void> };
    vm.passwordForm = { current: "old-secret", next: "new-secret", confirm: "new-secret" };
    await vm.savePassword();
    expect(changePassword).toHaveBeenCalledWith("old-secret", "new-secret");
    expect(vm.passwordForm).toEqual({ current: "", next: "", confirm: "" });
    expect(useAuthStore().user).toBeNull();
    expect(push).toHaveBeenCalledWith({ name: "login" });
  });

  it("locks retry on an unknown response and offers a deliberate login check", async () => {
    changePassword.mockRejectedValue(new PasswordChangeError(
      "修改结果尚未确认，请重新登录核对；不要重复提交。", 503, "password_change_outcome_unknown"));
    const wrapper = shallowMount(ProfileView);
    await flushPromises();
    const vm = wrapper.vm as unknown as { passwordForm: { current: string; next: string; confirm: string };
      savePassword: () => Promise<void>; checkPasswordChangeByLogin: () => Promise<void> };
    vm.passwordForm = { current: "old-secret", next: "new-secret", confirm: "new-secret" };
    await vm.savePassword();
    vm.passwordForm = { current: "old-secret", next: "new-secret", confirm: "new-secret" };
    await vm.savePassword();
    expect(changePassword).toHaveBeenCalledTimes(1);
    expect(useAuthStore().user?.subject).toBe("alice");
    expect(push).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("修改结果尚未确认");
    expect(wrapper.text()).toContain("重新登录核对");
    await vm.checkPasswordChangeByLogin();
    expect(useAuthStore().user).toBeNull();
    expect(push).toHaveBeenCalledWith({ name: "login" });
  });
});
