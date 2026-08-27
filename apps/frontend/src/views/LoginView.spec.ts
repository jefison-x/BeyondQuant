import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginView from "./LoginView.vue";

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}));

describe("LoginView browser semantics", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("associates labels and exposes standard password-manager fields", () => {
    const wrapper = mount(LoginView);
    const username = wrapper.get("#username");
    const password = wrapper.get("#password");

    expect(wrapper.get('label[for="username"]').text()).toBe("用户名");
    expect(username.attributes()).toMatchObject({ name: "username", autocomplete: "username" });
    expect(username.attributes("autocapitalize")).toBe("none");
    expect(wrapper.get('label[for="password"]').text()).toBe("密码");
    expect(password.attributes()).toMatchObject({ name: "password", autocomplete: "current-password", type: "password" });
  });
});
