import { createPinia, setActivePinia } from "pinia";
import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AdminOpsView from "./AdminOpsView.vue";
import { useAuthStore } from "@/stores/auth";

const getOperationsStatus = vi.fn();
vi.mock("@/api/operations", () => ({
  getOperationsStatus: (...args: unknown[]) => getOperationsStatus(...args),
  updateOperationsBudget: vi.fn(),
}));

describe("AdminOpsView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().token = "admin-test";
    getOperationsStatus.mockReset();
    getOperationsStatus.mockResolvedValue({
      schema_version: "operations.v1",
      services: { gateway: "ready", backend: "ready", runtime_adapter: "ready" },
      database: { engine: "postgresql", status: "ready", name: "byq_domain", server_version: "16", size_bytes: 1, table_count: 1, estimated_rows: 2, domain_counts: [], migration: { single_domain_store: "complete", legacy_sqlite_runtime: false } },
      cache: { kind: "postgresql_market_data", status: "empty", row_count: 0, redis: "not_used", groups: [] },
      sources: { provider: "tushare", credential_metadata: [], configuration_scope: "phase_39", legacy_providers: [], secrets_exposed: false },
      models: { credential_metadata: [], profiles: 0, bindings: 0, secrets_exposed: false },
      agents: { status_groups: [], recent_runs: [] },
      graphs: { projection: "normalized_agent_runs", recent_runs: [], raw_dsh_events: false },
      access: { principal_groups: [], agent_audit: [], operations_audit: [] },
      budget: { policy_id: "product-agent", enabled: false, alert_total_tokens: 400000, alert_requests: 48, version: 1, updated_by: "system", updated_at: "2026-08-22T00:00:00Z" },
      runtime: { schema_version: "runtime-operations.v1", runtime: { status: "ready" }, sessions: { active: 0, active_prompts: 0, status_counts: {} }, usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, reasoning_tokens: 0, model_calls: 0, total_tokens: 0, scope: "adapter_process_lifetime", source: "normalized_dsh_token_usage" }, raw_dsh_events: false },
      observability: { workflow_trace: "normalized", audit: "append_only", raw_dsh_events: false },
    });
  });

  it("loads the admin Product API projection and selects a phase-owned workbench", async () => {
    const wrapper = shallowMount(AdminOpsView, { props: { section: "database" } });
    await flushPromises();
    expect(getOperationsStatus).toHaveBeenCalledWith("admin-test");
    expect(wrapper.findComponent({ name: "DatabaseOperations" }).exists()).toBe(true);
    expect(wrapper.text()).toContain("原始 DSH 事件不可见");
  });

  it("switches sections without exposing a placeholder", async () => {
    const wrapper = shallowMount(AdminOpsView, { props: { section: "budget" } });
    await flushPromises();
    expect(wrapper.findComponent({ name: "BudgetOperations" }).exists()).toBe(true);
    expect(wrapper.text()).not.toContain("尚未接入 BYQ Product API");
  });
});
