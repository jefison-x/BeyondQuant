import { afterEach, describe, expect, it, vi } from "vitest";
import { disableUser, listUsers } from "./admin";

describe("admin api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists users through product admin api", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ users: [{ user_id: "user_1", username: "alice" }] }), { status: 200 })),
    );
    const result = await listUsers();
    expect(result.users).toHaveLength(1);
  });

  it("disables a user", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ user: { status: "disabled" } }), { status: 200 })),
    );
    const result = await disableUser("user_1");
    expect(result).toMatchObject({ user: { status: "disabled" } });
  });
});
