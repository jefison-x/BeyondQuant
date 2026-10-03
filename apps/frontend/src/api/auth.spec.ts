import { afterEach, describe, expect, it, vi } from "vitest";
import { changePassword, PasswordChangeError } from "./auth";

afterEach(() => vi.unstubAllGlobals());

describe("changePassword", () => {
  it("uses the authenticated Product route and accepts only an exact success receipt", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await changePassword("old-secret", "new-secret");
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/change-password", expect.objectContaining({
      method: "POST", credentials: "include", body: JSON.stringify({
        current_password: "old-secret", new_password: "new-secret",
      }),
    }));
  });

  it("treats a lost response as unknown and never retries the write", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("lost response"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(changePassword("old-secret", "new-secret")).rejects.toMatchObject({
      code: "password_change_outcome_unknown",
    } satisfies Partial<PasswordChangeError>);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
