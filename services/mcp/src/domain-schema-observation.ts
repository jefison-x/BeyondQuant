/** Public Fetch adapter seam; SDK validation remains the execution gate. */
import { domainValidationSchemas } from "./domain-validation-schema.js";
import { safeDomainAdmission } from "./domain-admission.js";

type Handler = { fetch(request: Request, options?: { parsedBody?: unknown }): Promise<Response> };
export type SchemaFailure = {
  action: keyof typeof domainValidationSchemas;
  arguments: Record<string, unknown>;
};

export async function boundedBody(request: Request): Promise<unknown> {
  const reader = request.clone().body?.getReader();
  if (!reader) return undefined;
  const chunks: Uint8Array[] = [];
  let size = 0;
  let complete = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error('MCP body deadline')), 5000);
  });
  try {
    while (true) {
      const chunk = await Promise.race([reader.read(), deadline]);
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 4 * 1024 * 1024) return undefined;
      chunks.push(chunk.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (size > 512 * 1024 && body?.params?.name !== "byq_factor_compute") return undefined;
    complete = true;
    return body;
  } catch {
    return undefined; // Missing proof is never execution permission.
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    // Never await tee cancellation. A rejected request must not leave its
    // untouched branch buffering an unbounded incoming body.
    void reader.cancel().catch(() => undefined);
    if (!complete) void request.body?.cancel().catch(() => undefined);
  }
}

export function observeDomainSchemaFailures(handler: Handler,
  observe: (failure: SchemaFailure, request: Request) => Promise<ReturnType<typeof safeDomainAdmission> | void>): Handler {
  return { async fetch(request, options) {
    let admission: ReturnType<typeof safeDomainAdmission> | void = undefined;
    let callId: unknown;
    if (request.method === "POST") {
      const body = options?.parsedBody ?? await boundedBody(request);
      if (body === undefined) return new Response('Invalid or oversized MCP envelope', { status: 400 });
      options = { ...options, parsedBody: body };
      if (body && typeof body === "object" && !Array.isArray(body)) {
        const envelope = body as Record<string, unknown>;
        const params = envelope.params as Record<string, unknown> | undefined;
        if (envelope.method === "tools/call" && params && typeof params.name === "string"
          && Object.hasOwn(domainValidationSchemas, params.name)) {
          const action = params.name as keyof typeof domainValidationSchemas;
          const args = params.arguments;
          if (args && typeof args === "object" && !Array.isArray(args)
            && !domainValidationSchemas[action].safeParse(args).success) {
            // Observation never invokes the domain handler or repairs inputs.
            admission = await observe({ action, arguments: args as Record<string, unknown> }, request);
            callId = envelope.id;
          }
        }
      }
    }
    const response = await handler.fetch(request, options);
    if (admission?.stop && (typeof callId === "string" || typeof callId === "number")) {
      // SDK schema validation has run and rejected the request. Preserve its
      // error verbatim as tool error content, plus a closed BYQ stop decision.
      // This is never a successful tool result and does not bypass validation.
      const original = await response.text();
      return Response.json({ jsonrpc: "2.0", id: callId, result: { isError: true, content: [
        { type: "text", text: JSON.stringify({ service: "beyondquant-mcp", status: "error", backend: { admission } }) },
        { type: "text", text: original },
      ] } });
    }
    return response;
  } };
}
