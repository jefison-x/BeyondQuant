/** Public Fetch adapter seam; SDK validation remains the execution gate. */
import { domainValidationSchemas } from "./domain-validation-schema.js";
import { safeDomainAdmission } from "./domain-admission.js";

type Handler = { fetch(request: Request, options?: { parsedBody?: unknown }): Promise<Response> };
export type SchemaFailure = {
  action: keyof typeof domainValidationSchemas;
  arguments: Record<string, unknown>;
};

async function boundedBody(request: Request): Promise<unknown> {
  const reader = request.clone().body?.getReader();
  if (!reader) return undefined;
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > 512 * 1024) return undefined;
      chunks.push(chunk.value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    return undefined; // Missing proof is never execution permission.
  } finally {
    // A cloned tee must not await cancellation of the untouched original.
    void reader.cancel().catch(() => undefined);
  }
}

export function observeDomainSchemaFailures(handler: Handler,
  observe: (failure: SchemaFailure, request: Request) => Promise<ReturnType<typeof safeDomainAdmission> | void>): Handler {
  return { async fetch(request, options) {
    let admission: ReturnType<typeof safeDomainAdmission> | void = undefined;
    let callId: unknown;
    if (request.method === "POST") {
      const body = options?.parsedBody ?? await boundedBody(request);
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
