/** Restrict background calls before the public MCP handler invokes a tool. */
import { boundedBody } from './domain-schema-observation.js';

type Handler = { fetch(request: Request, options?: { parsedBody?: unknown }): Promise<Response> };
type Call = { tool: string; arguments: Record<string, unknown>; root_run_id: string };

export function continuationAdmission(handler: Handler,
  admit: (reservation: string, call: Call, request: Request) => Promise<boolean>): Handler {
  return { async fetch(request, options) {
    const reservation = request.headers.get('x-byq-continuation-reservation');
    if (reservation === null) return handler.fetch(request, options);
    if (!/^continuation_[0-9a-f]{32}$/.test(reservation)) return new Response('Invalid continuation identity', { status: 403 });
    if (request.method !== 'POST') return handler.fetch(request, options);
    const body = options?.parsedBody ?? await boundedBody(request);
    if (!body || typeof body !== 'object' || Array.isArray(body)) return new Response('Invalid continuation envelope', { status: 400 });
    const envelope = body as Record<string, unknown>;
    if (envelope.method !== 'tools/call') return handler.fetch(request, { ...options, parsedBody: body });
    const params = envelope.params as Record<string, unknown> | undefined;
    const args = params?.arguments ?? {};
    let allowed = false;
    try {
      if (params && typeof params.name === 'string' && args && typeof args === 'object'
        && !Array.isArray(args)) {
        allowed = await admit(reservation, { tool: params.name, arguments: args as Record<string, unknown>,
          root_run_id: request.headers.get('x-byq-root-run-id') ?? '' }, request);
      }
    } catch { /* No evidence is not permission; never replay an admission. */ }
    if (!allowed) return Response.json({ jsonrpc: '2.0', id: envelope.id ?? null, result: { isError: true,
      content: [{ type: 'text', text: JSON.stringify({ status: 'blocked',
        reason: 'continuation_action_not_admitted', message: 'This background action is outside the active original-task permission. Stop and report the blocker; do not switch tasks or approve it yourself.' }) }] } });
    return handler.fetch(request, { ...options, parsedBody: body });
  } };
}
