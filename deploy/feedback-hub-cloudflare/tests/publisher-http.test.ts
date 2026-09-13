import { expect, it } from "vitest";
import { boundedResponse } from "../../../workers/feedback-publisher-cloudflare/src/index";

it("preserves a bounded response and status", async () => {
  const reply = await boundedResponse(async () => new Response('{"ok":true}', {
    status: 201, headers: { "content-type": "application/json" },
  }), 64);
  expect(reply.status).toBe(201);
  expect(await reply.json()).toEqual({ ok: true });
});

it("rejects actual oversized bytes and cancels the producer", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new Uint8Array(65)); },
    cancel() { cancelled = true; },
  });
  await expect(boundedResponse(async () => new Response(body, {
    headers: { "content-length": "1" },
  }), 64)).rejects.toMatchObject({ category: "transport_ambiguous" });
  expect(cancelled).toBe(true);
});

it("bounds missing response headers without waiting for the provider to honor abort", async () => {
  let signal: AbortSignal | undefined;
  await expect(boundedResponse(value => {
    signal = value;
    return new Promise<Response>(() => {});
  }, 64, 50)).rejects.toMatchObject({ category: "transport_ambiguous" });
  expect(signal?.aborted).toBe(true);
});

it("uses the same deadline for a stalled body and releases its stream", async () => {
  let cancelled = false;
  let signal: AbortSignal | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode('{')); },
    cancel() { cancelled = true; },
  });
  await expect(boundedResponse(async value => {
    signal = value;
    return new Response(body);
  }, 64, 50)).rejects.toMatchObject({ category: "transport_ambiguous" });
  expect(signal?.aborted).toBe(true);
  expect(cancelled).toBe(true);
});
