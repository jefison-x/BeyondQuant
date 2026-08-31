import type { DataCenterStatus } from "@/api/types";

/** Merge only durable task/progress projections during background polling. */
export function mergeDataCenterProgress(
  current: DataCenterStatus,
  next: DataCenterStatus,
): DataCenterStatus {
  return {
    ...current,
    jobs: next.jobs,
    data_demands: next.data_demands,
    data_tasks: next.data_tasks,
    security_master_jobs: next.security_master_jobs,
    automation: {
      ...current.automation,
      worker: next.automation.worker,
      latest_calendar_open_date: next.automation.latest_calendar_open_date,
      latest_complete_session: next.automation.latest_complete_session,
      next_run_at: next.automation.next_run_at,
      jobs: next.automation.jobs,
      run_requests: next.automation.run_requests,
      index_catalog_sync_runs: next.automation.index_catalog_sync_runs,
    },
  };
}
