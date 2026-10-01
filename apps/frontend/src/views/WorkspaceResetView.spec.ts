import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth";
import { WorkspaceResetRequestError } from "@/api/workspaceReset";
import WorkspaceResetView from "./WorkspaceResetView.vue";

const { confirmRuntime, resetRuntime, resetWorkspace, loadAppearance } = vi.hoisted(() => ({
  confirmRuntime: vi.fn(),
  resetRuntime: vi.fn(),
  resetWorkspace: vi.fn(),
  loadAppearance: vi.fn(),
}));

vi.mock("@/stores/appearance", async () => ({
  ...await vi.importActual<typeof import("@/stores/appearance")>("@/stores/appearance"),
  useAppearanceStore: () => ({ load: loadAppearance, $reset: vi.fn() }),
}));
vi.mock("element-plus", () => ({ ElMessageBox: { confirm: confirmRuntime } }));
vi.mock("@/api/workspaceReset", () => ({
  resetCurrentWorkspaceRuntime: resetRuntime,
  resetCurrentWorkspace: resetWorkspace,
  WorkspaceResetRequestError: class extends Error {
    constructor(message: string, readonly status: number, readonly terminal = false) {
      super(message);
    }
  },
}));

describe("WorkspaceResetView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    sessionStorage.clear();
    confirmRuntime.mockReset();
    confirmRuntime.mockResolvedValue(true);
    resetRuntime.mockReset();
    resetWorkspace.mockReset();
    loadAppearance.mockReset();
    loadAppearance.mockResolvedValue(undefined);
    useAuthStore().setUser({
      subject: "alice",
      display_name: "Alice",
      role: "user",
      workspace: {
        contract: "personal-workspace.v1",
        workspace_id: "workspace_alice",
        kind: "personal",
        display_name: "Alice 的个人工作区",
        role: "owner",
      },
    });
  });

  afterEach(() => vi.restoreAllMocks());

  it("explains both reset scopes and preserves the runtime receipt", async () => {
    resetRuntime.mockResolvedValue({
      status: "reset", workspace_id: "workspace_alice", archived_conversation_count: 3,
    });
    const wrapper = mount(WorkspaceResetView);

    expect(wrapper.text()).toContain("任务、生成的研究成果、金融事实和审计记录");
    expect(wrapper.text()).toContain("全局设置、凭据和共享数据源");
    expect(wrapper.text()).toContain("存在未确认的外部操作时，系统会停止重置并保留数据");

    await wrapper.get("button.secondary").trigger("click");
    await flushPromises();

    expect(confirmRuntime).toHaveBeenCalledWith(
      expect.stringContaining("结束当前工作区的运行时会话"),
      "确认重置运行时",
      expect.objectContaining({ confirmButtonText: "确认重置", cancelButtonText: "取消" }),
    );
    expect(resetRuntime).toHaveBeenCalledWith("workspace_alice");
    expect(wrapper.get('[role="status"]').text()).toContain("归档了 3 段对话");
  });

  it("does not call the Product API when runtime reset confirmation is cancelled", async () => {
    confirmRuntime.mockRejectedValue("cancel");
    const wrapper = mount(WorkspaceResetView);

    await wrapper.get("button.secondary").trigger("click");
    await flushPromises();

    expect(confirmRuntime).toHaveBeenCalledOnce();
    expect(resetRuntime).not.toHaveBeenCalled();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
  });

  it("requires the exact phrase and reports the confirmed workspace result", async () => {
    resetWorkspace.mockResolvedValue({
      status: "reset", workspace_id: "workspace_alice", deleted: { research_tasks: 2, artifacts: 1 }, already_empty: false, archive: { reset_id: "a".repeat(32), created_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-08T00:00:00Z", retention_days: 7, row_count: 3, payload_sha256: "b".repeat(64) },
    });
    const wrapper = mount(WorkspaceResetView);
    const confirmButton = wrapper.get("button.danger");

    expect((confirmButton.element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.get("input").setValue("重置工作区 ");
    expect((confirmButton.element as HTMLButtonElement).disabled).toBe(true);
    await wrapper.get("input").setValue("重置工作区");
    expect((confirmButton.element as HTMLButtonElement).disabled).toBe(false);

    await confirmButton.trigger("click");
    await flushPromises();

    const [workspaceId, requestKey] = resetWorkspace.mock.calls[0];
    expect(workspaceId).toBe("workspace_alice");
    expect(requestKey).toMatch(/^[0-9a-f-]{36}$/);
    expect(wrapper.get('[role="status"]').text()).toContain("已清理 3 条记录");
    expect(sessionStorage.getItem(`byq.workspace-reset.idempotency-key.v1:${workspaceId}`)).toBeNull();
  });

  it("reuses the same workspace idempotency key after an uncertain result", async () => {
    resetWorkspace
      .mockRejectedValueOnce(new Error("请求结果尚未确认，请重试。"))
      .mockResolvedValueOnce({
        status: "reset", workspace_id: "workspace_alice", deleted: { experiments: 1 }, already_empty: false, archive: { reset_id: "a".repeat(32), created_at: "2026-10-01T00:00:00Z", expires_at: "2026-10-08T00:00:00Z", retention_days: 7, row_count: 3, payload_sha256: "b".repeat(64) },
      });
    const wrapper = mount(WorkspaceResetView);
    await wrapper.get("input").setValue("重置工作区");
    const confirmButton = wrapper.get("button.danger");

    await confirmButton.trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("请求结果尚未确认");
    expect((confirmButton.element as HTMLButtonElement).disabled).toBe(false);
    const storedKey = sessionStorage.getItem("byq.workspace-reset.idempotency-key.v1:workspace_alice");
    expect(storedKey).toBe(resetWorkspace.mock.calls[0][1]);

    await confirmButton.trigger("click");
    await flushPromises();

    expect(resetWorkspace).toHaveBeenCalledTimes(2);
    expect(resetWorkspace.mock.calls[1][1]).toBe(storedKey);
    expect(sessionStorage.getItem("byq.workspace-reset.idempotency-key.v1:workspace_alice")).toBeNull();
    expect(wrapper.get('[role="status"]').text()).toContain("已清理 1 条记录");
  });

  it("starts a new request after a confirmed terminal blocker", async () => {
    resetWorkspace
      .mockRejectedValueOnce(new WorkspaceResetRequestError("运行中的任务阻止重置", 409, true))
      .mockResolvedValueOnce({ status: "reset", workspace_id: "workspace_alice", deleted: {}, already_empty: true });
    const wrapper = mount(WorkspaceResetView);
    await wrapper.get("input").setValue("重置工作区");
    await wrapper.get("button.danger").trigger("click");
    await flushPromises();

    expect(wrapper.get('[role="alert"]').text()).toContain("运行中的任务阻止重置");
    expect(sessionStorage.getItem("byq.workspace-reset.idempotency-key.v1:workspace_alice")).toBeNull();
    await wrapper.get("button.danger").trigger("click");
    await flushPromises();
    expect(resetWorkspace.mock.calls[1][1]).not.toBe(resetWorkspace.mock.calls[0][1]);
  });
  it("clears old appearance cache after confirmed reset even if readonly refresh fails", async () => {
    localStorage.setItem("byq-ui-preferences.v1", JSON.stringify({schema_version:"ui-preferences.v1",color_mode:"dark",accent_theme:"ocean"}));
    loadAppearance.mockRejectedValue(new Error("network unavailable"));
    resetWorkspace.mockResolvedValue({status:"reset",workspace_id:"workspace_alice",deleted:{},already_empty:true,
      archive:{reset_id:"a".repeat(32),created_at:"2026-10-01T00:00:00Z",expires_at:"2026-10-08T00:00:00Z",retention_days:7,row_count:0,payload_sha256:"b".repeat(64)}});
    const wrapper=mount(WorkspaceResetView);
    await wrapper.get("input").setValue("重置工作区");
    await wrapper.get("button.danger").trigger("click");
    await flushPromises();
    expect(resetWorkspace).toHaveBeenCalledTimes(1);
    expect(document.documentElement.dataset.colorMode).toBe("system");
    expect(JSON.parse(localStorage.getItem("byq-ui-preferences.v1")!)).toMatchObject({color_mode:"system",accent_theme:"emerald"});
    expect(wrapper.get('[role="alert"]').text()).toContain("重置已完成；外观默认状态读取失败");
    expect(wrapper.get('[role="status"]').text()).toContain("归档保留七天");
  });

});
