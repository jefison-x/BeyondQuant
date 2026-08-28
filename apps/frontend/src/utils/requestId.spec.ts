import { afterEach, describe, expect, it, vi } from "vitest";
import { createRequestId } from "./requestId";

describe("createRequestId", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the native randomUUID implementation when available", () => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => "11111111-1111-4111-8111-111111111111"),
    });

    expect(createRequestId()).toBe("11111111-1111-4111-8111-111111111111");
  });

  it("generates an RFC 4122 UUID when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0xab);
        return bytes;
      },
    });

    expect(createRequestId()).toBe("abababab-abab-4bab-abab-abababababab");
  });

  it("still generates an identifier when the Web Crypto API is absent", () => {
    vi.stubGlobal("crypto", undefined);
    vi.spyOn(Math, "random").mockReturnValue(0);

    expect(createRequestId()).toBe("00000000-0000-4000-8000-000000000000");
  });
});
