# UI Preferences Contract

`ui-preferences.v1` 是 ADR-0024 接受的 public、owner-scoped Product appearance contract。PostgreSQL 为权威；browser 仅经 Gateway Product API 访问。

```json
{
  "schema_version": "ui-preferences.v1",
  "color_mode": "system",
  "accent_theme": "emerald",
  "version": 0,
  "updated_at": null
}
```

封闭 `color_mode` values 为 `system`、`light`、`dark`；封闭 `accent_theme` values 为 `emerald`、`ocean`、`indigo`、`amber`、`graphite`。Unknown fields/values 校验失败。Semantic success、warning、danger、approval、destructive-action 和 A-share market colors 不随 accent 改变。

`GET /api/product/settings/appearance` 返回 authenticated owner 当前 preference 或以上默认 document。`PUT` 接受 `schema_version`、`color_mode`、`accent_theme` 和 `expected_version`。成功 write 递增 `version`；stale expected version 返回 conflict，不覆盖其他 device update。

Pre-mount browser cache 非权威，只可包含 `schema_version`、`color_mode` 和 `accent_theme`；不含 user、tenant、session、credential、model、domain data 或 server version。唯一用途是防止 first-paint color flash。认证后 Backend document 总是取代它。Malformed/unavailable cache 回退到 system/light/emerald，不阻塞 login。

禁用此能力会让 presentation 回到默认 token set；不删除 stored preference，也不改变 Product domain state。
