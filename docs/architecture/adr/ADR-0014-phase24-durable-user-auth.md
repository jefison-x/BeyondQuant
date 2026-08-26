# ADR-0014：Phase 24 Durable User Identity 与 Session Authentication

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 24 Product user identity 与 browser session boundary

## 背景

Phase 16-23 使用 opaque `BYQ_PRODUCT_TOKEN` 进行 browser login。Product completion
需要 durable user、password authentication、owner isolation，以及不会把 long-lived
bearer token 放入 browser storage 的 session boundary。

## 决策

1. BYQ Backend 持有 durable `users` table 和 `auth_sessions` table。
2. Password 使用 Python `hashlib.scrypt` 和 per-user random salt 进行 hash。禁止保存
   plaintext、SHA-256 password、MD5 或使用 home-grown crypto。
3. Gateway 签发 HTTP-only `byq_session` cookie，设置 `SameSite=Lax` 和 `Path=/`。
   Cookie value 是 Backend-owned opaque session id。Product API 通过调用 Backend 将
   cookie 解析为 BYQ principal。
4. 旧 `BYQ_PRODUCT_TOKEN` 只保留为 bootstrap/internal compatibility seam，不是普通
   browser login path。
5. User role 为 `admin` 或 `user`。Admin 可以 create/list/disable user 和 revoke session。
   Owner-scoped domain state 绑定到解析后的 principal。

## 后果

- Browser client 不再为 login 将 Product token 存入 localStorage。
- Session expiration/revocation 由 Backend 持有且可审计。
- Product API 可按 authenticated principal 强制 owner isolation。
