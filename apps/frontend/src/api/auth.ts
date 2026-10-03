export class PasswordChangeError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message); }
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/auth/change-password", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    throw new PasswordChangeError("修改结果尚未确认，请重新登录核对；不要重复提交。", 0, "password_change_outcome_unknown");
  }
  const body = (await response.json().catch(() => ({}))) as {
    status?: unknown; error?: { code?: unknown; message?: unknown };
  };
  if (!response.ok) {
    const code = typeof body.error?.code === "string" ? body.error.code : undefined;
    const messages: Record<string, string> = {
      current_password_invalid: "当前密码不正确。",
      password_policy_invalid: "新密码须为 8 至 256 个字符。",
      password_change_rate_limited: "当前密码尝试次数过多，请稍后再试。",
      password_change_outcome_unknown: "修改结果尚未确认，请重新登录核对；不要重复提交。",
      product_authentication_required: "登录已失效，请重新登录。",
      session_invalid: "登录已失效，请重新登录。",
    };
    throw new PasswordChangeError(messages[code ?? ""] ?? "修改密码失败，请稍后重试。", response.status, code);
  }
  if (body.status !== "ok") {
    throw new PasswordChangeError("修改结果尚未确认，请重新登录核对；不要重复提交。", response.status,
      "password_change_outcome_unknown");
  }
}
