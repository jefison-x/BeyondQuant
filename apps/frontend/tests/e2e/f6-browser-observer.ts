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
