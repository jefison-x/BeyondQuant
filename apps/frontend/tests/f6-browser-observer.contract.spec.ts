import { describe, expect, it } from 'vitest';
import { F6_BROWSER_LOGIN_PATH, f6AuthResponse, f6BrowserRoute, f6BrowserWriteAllowed } from './e2e/f6-browser-observer';

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
