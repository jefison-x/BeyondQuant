import type { Page } from '@playwright/test';

/** Closed diagnostics for this F6 browser observer; no payloads or cookies. */
export const F6_BROWSER_LOGIN_PATH = '/api/auth/login';

export function f6BrowserWriteAllowed(method: string, pathname: string): boolean {
  return ['GET', 'HEAD', 'OPTIONS'].includes(method)
    || (method === 'POST' && pathname === F6_BROWSER_LOGIN_PATH);
}

export function f6AuthResponse(method: string, pathname: string, status: number):
  { step: 'login' | 'me'; status: number } | null {
  const step = method === 'POST' && pathname === F6_BROWSER_LOGIN_PATH ? 'login'
    : method === 'GET' && pathname === '/api/auth/me' ? 'me' : null;
  return step && Number.isInteger(status) && status >= 100 && status <= 599 ? { step, status } : null;
}

export function f6BrowserRoute(pathname: string): 'login' | 'agent' | 'research' | 'other' {
  return pathname === '/login' ? 'login' : pathname === '/agent' ? 'agent'
    : pathname === '/user/research' ? 'research' : 'other';
}

/** Read the dedicated task-record column, never classify objective/title text. */
export function f6TaskRecordColumn(headers: string[]): number {
  const indexes = headers.map((text, index) => text.trim() === '任务记录' ? index : -1)
    .filter(index => index >= 0);
  if (indexes.length !== 1) throw new Error('F6 requires one task-record column');
  return indexes[0];
}

export function f6TaskRecordLabel(status: unknown): string {
  if (typeof status !== 'string' || !['planned', 'running', 'completed', 'failed', 'cancelled'].includes(status)) {
    throw new Error('F6 requires a valid Product task status');
  }
  return status === 'running' ? '未完成' : status;
}

// Five existing Product reads share a deadline; no login or business call is retried.
export async function readF6Snapshot(page: Page, currentIds: Record<string, string>) {
  return page.evaluate(async (ids) => {
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 2000);
    const get = async (path: string) => {
      const response = await fetch(path, {
        method: 'GET', credentials: 'include', redirect: 'error', signal: controller.signal,
      });
      if (!response.ok) throw new Error(`F6 Product read failed: ${response.status}`);
      return response.json();
    };
    try {
      const [task, jobBody, artifact, permission, conversation] = await Promise.all([
        get(`/api/product/research/tasks/${encodeURIComponent(ids.task_id)}`),
        get(`/api/product/signal-producer/jobs/${encodeURIComponent(ids.signal_job_id)}`),
        get(`/api/product/research/artifacts/${encodeURIComponent(ids.signal_snapshot_artifact_id)}`),
        get(`/api/product/research/tasks/${encodeURIComponent(ids.task_id)}/continuation-permission`),
        get(`/v1/agent/sessions/${encodeURIComponent(ids.conversation_id)}`),
      ]);
      return { task, job: jobBody.job, artifact, permission, conversation };
    } finally {
      clearTimeout(deadline);
      controller.abort();
    }
  }, currentIds);
}
