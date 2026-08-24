# UI Preferences Contract

`ui-preferences.v1` is the public, owner-scoped Product appearance contract
accepted by ADR-0024. PostgreSQL is authoritative. The browser reaches this
state only through Gateway Product API.

```json
{
  "schema_version": "ui-preferences.v1",
  "color_mode": "system",
  "accent_theme": "emerald",
  "version": 0,
  "updated_at": null
}
```

The closed `color_mode` values are `system`, `light`, and `dark`. The closed
`accent_theme` values are `emerald`, `ocean`, `indigo`, `amber`, and
`graphite`. Unknown fields and values fail validation. Semantic success,
warning, danger, approval, destructive-action, and A-share market colors are
not altered by the accent choice.

`GET /api/product/settings/appearance` returns the authenticated owner's
current preference or the default document above. `PUT` accepts
`schema_version`, `color_mode`, `accent_theme`, and `expected_version`.
Successful writes increment `version`; a stale expected version returns a
conflict rather than overwriting another device's update.

The pre-mount browser cache is non-authoritative and may contain only
`schema_version`, `color_mode`, and `accent_theme`. It contains no user,
tenant, session, credential, model, domain data, or server version. Its sole
purpose is preventing a first-paint color flash. After authentication, the
Backend document always replaces it. A malformed or unavailable cache falls
back to system/light/emerald without blocking login.

Disabling this capability returns presentation to the default token set; it
does not delete the stored preference or alter Product domain state.
