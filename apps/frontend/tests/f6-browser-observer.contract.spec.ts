import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Page } from '@playwright/test';
import { F6_BROWSER_LOGIN_PATH, f6AuthResponse, f6BrowserRoute, f6BrowserWriteAllowed, f6TaskRecordColumn, f6TaskRecordLabel, readF6Snapshot } from './e2e/f6-browser-observer';

describe('current F6 browser authentication boundary', () => {
  it('allows only the actual browser login and safe reads', () => {
    expect(F6_BROWSER_LOGIN_PATH).toBe('/api/auth/login');
    expect(f6BrowserWriteAllowed('POST', F6_BROWSER_LOGIN_PATH)).toBe(true);
    for (const method of ['GET', 'HEAD', 'OPTIONS']) expect(f6BrowserWriteAllowed(method, '/any/read')).toBe(true);
    for (const path of ['/api/product/auth/login', '/api/auth/logout', '/v1/agent/sessions', '/api/auth/login/']) {
      expect(f6BrowserWriteAllowed('POST', path)).toBe(false);
    }
    for (const method of ['PUT', 'DELETE', 'PATCH']) expect(f6BrowserWriteAllowed(method, F6_BROWSER_LOGIN_PATH)).toBe(false);
  });
  it('preserves successful and failing auth status without response payloads', () => {
    for (const status of [200, 401, 403, 502, 503]) {
      expect(f6AuthResponse('POST', F6_BROWSER_LOGIN_PATH, status)).toEqual({ step: 'login', status });
      expect(f6AuthResponse('GET', '/api/auth/me', status)).toEqual({ step: 'me', status });
    }
    for (const status of [0, 600, 200.5, Number.NaN]) expect(f6AuthResponse('POST', F6_BROWSER_LOGIN_PATH, status)).toBeNull();
  });
  it('excludes other methods and resource paths from auth diagnostics', () => {
    expect(f6AuthResponse('GET', F6_BROWSER_LOGIN_PATH, 200)).toBeNull();
    expect(f6AuthResponse('POST', '/api/auth/me', 200)).toBeNull();
    expect(f6AuthResponse('GET', '/api/product/research/tasks/private-id', 200)).toBeNull();
  });
  it('projects only closed route categories', () => {
    expect(f6BrowserRoute('/login')).toBe('login');
    expect(f6BrowserRoute('/agent')).toBe('agent');
    expect(f6BrowserRoute('/user/research')).toBe('research');
    expect(f6BrowserRoute('/unknown/private-id')).toBe('other');
  });
});


describe('current F6 task-record observation', () => {
  const headers = ['任务名称', '研究目标', '任务记录', '研究阶段与下一步', 'Task ID', '任务交接', '后台续接'];
  it('does not classify completed in the actual objective as task completion', () => {
    const cells = ['F6 current task-ready read qualification',
      'Read this exact task and its exact completed signal artifact.', 'planned', '尚未记录研究阶段',
      'task_current', '查看交接', '查看许可'];
    expect(cells.join(' ')).toContain('completed');
    expect(cells[f6TaskRecordColumn(headers)]).toBe(f6TaskRecordLabel('planned'));
    cells[2] = 'completed';
    expect(cells[f6TaskRecordColumn(headers)]).not.toBe(f6TaskRecordLabel('planned'));
  });
  it('maps the Product running status to the public task-record label', () => {
    expect(f6TaskRecordLabel('running')).toBe('未完成');
    expect(f6TaskRecordLabel('completed')).toBe('completed');
  });
  it('rejects absent or ambiguous status columns and malformed authority values', () => {
    expect(() => f6TaskRecordColumn(['任务名称', '研究目标'])).toThrow();
    expect(() => f6TaskRecordColumn([...headers, '任务记录'])).toThrow();
    for (const value of [undefined, null, '', 'completed signal artifact', {}]) {
      expect(() => f6TaskRecordLabel(value)).toThrow();
    }
  });
});


describe('current F6 bounded Product snapshot', () => {
  const ids = { task_id: 'task_current', signal_job_id: 'job_current',
    signal_snapshot_artifact_id: 'artifact_current', conversation_id: 'conversation_current' };
  const page = { evaluate: async (run: (value: typeof ids) => unknown, value: typeof ids) => run(value) } as unknown as Page;
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
  it('uses exactly five concurrent same-origin GETs, one deadline and no redirect', async () => {
    const fetch = vi.fn(async (path: string) => ({ ok: true, json: async () =>
      path.includes('/signal-producer/') ? { job: { job_id: ids.signal_job_id } } : { observed: path } }));
    vi.stubGlobal('fetch', fetch);
    const snapshot = await readF6Snapshot(page, ids);
    expect(snapshot.job).toEqual({ job_id: ids.signal_job_id });
    expect(fetch.mock.calls.map(([path]) => path)).toEqual([
      '/api/product/research/tasks/task_current', '/api/product/signal-producer/jobs/job_current',
      '/api/product/research/artifacts/artifact_current',
      '/api/product/research/tasks/task_current/continuation-permission', '/v1/agent/sessions/conversation_current',
    ]);
    const options = fetch.mock.calls.map(call => (call as unknown as [string, RequestInit])[1]);
    for (const value of options) expect(value).toMatchObject({ method: 'GET', credentials: 'include', redirect: 'error' });
    expect(new Set(options.map(value => value.signal)).size).toBe(1);
    expect(options[0].signal?.aborted).toBe(true);
  });
  it('fails closed on an authority denial and aborts without retry or login', async () => {
    const fetch = vi.fn(async () => ({ ok: false, status: 403 }));
    vi.stubGlobal('fetch', fetch);
    await expect(readF6Snapshot(page, ids)).rejects.toThrow('F6 Product read failed: 403');
    expect(fetch).toHaveBeenCalledTimes(5);
    const options = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(options.signal?.aborted).toBe(true);
  });
  it('aborts every stalled read at the shared two-second deadline without replay', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((_path: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new Error('deadline')), { once: true });
    }));
    vi.stubGlobal('fetch', fetch);
    const result = readF6Snapshot(page, ids);
    const assertion = expect(result).rejects.toThrow('deadline');
    await vi.advanceTimersByTimeAsync(2000);
    await assertion;
    expect(fetch).toHaveBeenCalledTimes(5);
    expect(vi.getTimerCount()).toBe(0);
  });
});
