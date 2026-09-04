import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProductFeedbackContent } from "./types";
import {
  createFeedback,
  getFeedbackAudit,
  getFeedbackOptions,
  listFeedback,
  moderateFeedback,
  submitFeedback,
  updateFeedback,
  withdrawFeedback,
} from "./feedback";

describe("feedback api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("loads only explicitly requested bounded resources", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ schema_version: "product-feedback-options.v1", categories: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await getFeedbackOptions();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/product/feedback/options", expect.objectContaining({ credentials: "include" }));

    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ items: [], total: 0, limit: 12, offset: 0, has_more: false }), { status: 200 }));
    await listFeedback({ status: "all", category: "all", query: "慢", limit: 12, offset: 0 });
    expect(String(fetchMock.mock.calls[1][0])).toContain("limit=12");
    expect(String(fetchMock.mock.calls[1][0])).toContain("query=%E6%85%A2");
  });

  it("requires the caller to pass the reviewed preview hash and explicit confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ feedback: { status: "submitted" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await submitFeedback({ feedback_id: "feedback_" + "a".repeat(32), version: 2 } as never, "b".repeat(64));
    const payload = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(payload).toMatchObject({ expected_version: 2, preview_hash: "b".repeat(64), disclosure_confirmed: true });
  });

  it("keeps every feedback mutation usable when randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0xab);
        return bytes;
      },
    });
    const fetchMock = vi.fn().mockImplementation(async () =>
      new Response(JSON.stringify({ feedback: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const content: ProductFeedbackContent = {
      schema_version: "product-feedback.v1", category: "bug", component: "other", severity: "normal",
      title: "局域网反馈提交", description: "验证普通 HTTP 环境的反馈写操作。", reproduction_steps: [],
      expected_behavior: "请求成功发送", actual_behavior: "", diagnostics: {},
    };
    const item = { feedback_id: `feedback_${"a".repeat(32)}`, version: 2 } as never;

    await createFeedback(content);
    await updateFeedback(item, content);
    await submitFeedback(item, "b".repeat(64));
    await withdrawFeedback(item);
    await moderateFeedback(item, "triage", "已验证");

    expect(fetchMock).toHaveBeenCalledTimes(5);
    for (const [, init] of fetchMock.mock.calls) {
      expect(JSON.parse(String(init.body)).idempotency_key).toBe("abababab-abab-4bab-abab-abababababab");
    }
  });

  it("loads audit only through the dedicated lazy endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ audit: [], total: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await getFeedbackAudit("feedback_" + "a".repeat(32), 20);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/audit?limit=20&offset=20");
  });
});
