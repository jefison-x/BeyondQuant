export async function listUsers(): Promise<{ users: Array<Record<string, unknown>> }> {
  const response = await fetch("/api/product/admin/users", { credentials: "include" });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "admin request failed");
  }
  return (await response.json()) as { users: Array<Record<string, unknown>> };
}

export async function disableUser(userId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`/api/product/admin/users/${encodeURIComponent(userId)}/disable`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? "disable user failed");
  }
  return (await response.json()) as Record<string, unknown>;
}
